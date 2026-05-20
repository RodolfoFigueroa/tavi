import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

import duckdb
import pandas as pd
from langchain_core.messages import AIMessage, SystemMessage, ToolMessage
from langchain_core.messages.tool import ToolCall
from langchain_core.runnables import RunnableConfig

from tavi.connections import base_llm
from tavi.db import append_to_table, get_session
from tavi.graphs.common import load_prompt_from_name
from tavi.models import Area
from tavi.state import AgentState
from tavi.tools import agent_tools, dynamic_tool_registry
from tavi.tools.static import execute_spatial_query

logger = logging.getLogger(__name__)

_static_tool_registry = {execute_spatial_query.name: execute_spatial_query}

SYSTEM_PROMPT_TEMPLATE = load_prompt_from_name("agent")


agent_llm = base_llm.bind_tools(agent_tools)


def render_system_prompt(
    available_tables: list[str],
    available_table_meta: dict[str, dict],
    areas: list[Area],
) -> str:
    """Render the agent system prompt with dynamic table and area information.

    Substitutes the ``{DYNAMIC_LOCAL_TABLES}`` placeholder in the prompt
    template with per-table Markdown documentation, then appends a section
    listing all pre-resolved geographic areas and their census tract counts.

    Args:
        available_tables: Ordered list of DuckDB table names available to the
            agent.
        available_table_meta: Mapping of table name to metadata dict with key
            ``tool_name``.
        areas: List of resolved ``Area`` dicts (name, code, tracts).

    Returns:
        The fully rendered system prompt string.
    """
    if not available_tables:
        table_docs = "No tool-generated tables are available yet."
    else:
        parts = []
        for tbl in available_tables:
            meta = available_table_meta.get(tbl, {})
            tool_name = meta.get("tool_name", "")
            entry = dynamic_tool_registry.get(tool_name)
            base_desc = entry.description if entry else ""
            col_docs: dict[str, str] = {
                "metropolitan_zone": "Name of the metropolitan zone (VARCHAR).",
            }
            if entry:
                col_docs["cvegeo"] = entry.columns.get(
                    "cvegeo", "Census tract code (VARCHAR)."
                )
                if entry.add_area:
                    col_docs.update(
                        {
                            col: col_desc
                            for col, col_desc in entry.columns.items()
                            if col != "cvegeo"
                        }
                    )
                else:
                    col_docs["value"] = entry.columns.get(entry.column_name, "")
                for key in entry.extra_args_keys:
                    col_docs[key] = entry.extra_args_config[key].get("description", "")
            col_lines = "\n".join(
                f"* `{col}`: {col_desc}" for col, col_desc in col_docs.items()
            )
            parts.append(f"**Table: `{tbl}`** — {base_desc}\n{col_lines}")
        table_docs = "\n\n".join(parts)

    if not areas:
        area_lines = "No geographic areas have been resolved yet."
    else:
        area_lines = "\n".join(
            f"* **{a['name']}** (code: `{a['code']}`): {len(a['tracts'])} census tracts"
            for a in areas
        )

    return SYSTEM_PROMPT_TEMPLATE.replace("{DYNAMIC_LOCAL_TABLES}", table_docs).replace(
        "{RESOLVED_AREAS}", area_lines
    )


def agent_node(state: AgentState) -> dict:
    """LangGraph node: invoke the agent LLM with the current state.

    Renders the system prompt incorporating available tables and areas,
    logs it at DEBUG level, then calls ``agent_llm`` with the full message
    history.

    Args:
        state: Current agent state containing ``messages``,
            ``available_tables``, ``available_table_meta``, and ``areas``.

    Returns:
        A state-patch dict with the LLM's response appended to ``messages``.
    """
    system_content = render_system_prompt(
        state.get("available_tables", []),
        state.get("available_table_meta", {}),
        state.get("areas", []),
    )
    logger.debug(
        "\n%s SYSTEM PROMPT %s\n%s\n%s",
        "=" * 40,
        "=" * 40,
        system_content,
        "=" * 95,
    )
    system = SystemMessage(content=system_content)
    response = agent_llm.invoke([system, *state["messages"]])
    return {"messages": [response]}


def make_table_name(tool_name: str) -> str:
    """Build a DuckDB table name from a tool name.

    Replaces the ``fetch_`` prefix with ``local_``.

    Args:
        tool_name: The dynamic tool name (e.g. ``"fetch_temperatures"``).

    Returns:
        A table name string (e.g. ``"local_temperatures"``).
    """
    return tool_name.replace("fetch_", "local_")


def handle_dynamic_tool(
    tool_call: ToolCall,
    state: AgentState,
    conn: duckdb.DuckDBPyConnection,
    new_tables: list[str],
    new_table_meta: dict[str, dict],
) -> ToolMessage:
    """Execute a dynamic tool call concurrently across all resolved areas.

    Launches one fetch task per area in a ``ThreadPoolExecutor``, appends
    successful results to a shared DuckDB table via ``append_to_table``,
    records table metadata, and returns a ``ToolMessage`` summarising
    appended rows and any per-area errors.

    Args:
        tool_call: The ``ToolCall`` dict from the AI message, containing
            ``name``, ``id``, and ``args``.
        state: Current agent state, used to access the ``areas`` list.
        conn: Active DuckDB connection for writing result tables.
        new_tables: Mutable list to append newly created table names to.
        new_table_meta: Mutable dict to record metadata for new tables.

    Returns:
        A ``ToolMessage`` addressed to ``tool_call["id"]`` summarising the
        rows appended and any per-area errors.
    """
    tool_name: str = str(tool_call["name"])
    call_id: str = str(tool_call["id"])
    extra_args: dict = tool_call["args"]
    entry = dynamic_tool_registry[tool_name]
    arg_keys = entry.extra_args_keys
    caller = entry.caller
    areas = state.get("areas", [])
    tbl = make_table_name(tool_name)

    def _fetch(area: Area) -> tuple[Area, object]:
        """Fetch data for one area via the tool's caller.

        Args:
            area: The ``Area`` dict whose ``tracts`` list is passed to
                ``caller``.

        Returns:
            A ``(area, DataFrame)`` tuple on success, or
            ``(area, Exception)`` if the caller raises.
        """
        try:
            return area, caller(area["tracts"], extra_args)
        except Exception as exc:  # noqa: BLE001
            return area, exc

    with ThreadPoolExecutor(max_workers=len(areas) or 1) as pool:
        futures = {pool.submit(_fetch, area): area for area in areas}
        results = [future.result() for future in as_completed(futures)]

    created: list[str] = []
    errors: list[str] = []
    for area, outcome in results:
        if isinstance(outcome, Exception):
            errors.append(f"{area['name']}: {outcome}")
        else:
            df = pd.DataFrame(outcome)
            df.insert(0, "metropolitan_zone", area["name"])
            if not entry.add_area:
                df = df.rename(columns={entry.column_name: "value"})
            df = df.assign(**{key: extra_args.get(key) for key in arg_keys})
            append_to_table(conn, tbl, df)
            if tbl not in new_tables:
                new_tables.append(tbl)
            if tbl not in new_table_meta:
                new_table_meta[tbl] = {"tool_name": tool_name}
            created.append(f"Appended {len(df)} rows to `{tbl}` (area={area['name']})")
    content_parts: list[str] = []
    if created:
        content_parts.append("\n".join(created))
    if errors:
        content_parts.append("Errors: " + "; ".join(errors))
    return ToolMessage(
        tool_call_id=call_id,
        content="\n".join(content_parts) or "No data appended.",
    )


def tools_node(state: AgentState, config: RunnableConfig) -> dict:
    """LangGraph node: dispatch all tool calls from the latest AI message.

    Routes dynamic tool names to ``handle_dynamic_tool`` and static tool
    names (e.g. ``execute_spatial_query``) to their ``StructuredTool``
    instances, passing ``config`` so that ``RunnableConfig`` arguments are
    injected automatically. Returns an error ``ToolMessage`` for
    unrecognised tool names.

    Args:
        state: Current agent state containing ``messages``,
            ``available_tables``, and ``available_table_meta``.
        config: LangGraph ``RunnableConfig`` providing the ``thread_id`` used
            to look up the DuckDB session for dynamic tools.

    Returns:
        A state-patch dict with ``ToolMessage`` results appended to
        ``messages``, and updated ``available_tables`` and
        ``available_table_meta``.
    """
    thread_id: str = config["configurable"]["thread_id"]

    new_messages: list[ToolMessage] = []
    new_tables: list[str] = list(state.get("available_tables", []))
    new_table_meta: dict[str, dict] = dict(state.get("available_table_meta", {}))

    last_ai = state["messages"][-1]

    if not isinstance(last_ai, AIMessage):
        err = "Expected the last message to be an AIMessage with tool calls."
        raise TypeError(err)

    for tool_call in last_ai.tool_calls:
        tool_name = tool_call["name"]
        call_id = tool_call["id"]

        if tool_name in dynamic_tool_registry:
            conn = get_session(thread_id)
            new_messages.append(
                handle_dynamic_tool(tool_call, state, conn, new_tables, new_table_meta)
            )

        elif tool_name in _static_tool_registry:
            result = _static_tool_registry[tool_name].invoke(
                tool_call["args"], config=config
            )
            new_messages.append(ToolMessage(tool_call_id=call_id, content=str(result)))

        else:
            new_messages.append(
                ToolMessage(
                    tool_call_id=call_id,
                    content=f"Unknown tool: {tool_name}",
                )
            )

    return {
        "messages": new_messages,
        "available_tables": new_tables,
        "available_table_meta": new_table_meta,
    }
