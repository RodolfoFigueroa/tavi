import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Annotated, Literal

import duckdb
import pandas as pd
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import (
    AIMessage,
    AnyMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.messages.tool import ToolCall
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict

from tavi.db import get_session, write_dataframe
from tavi.tools import (
    DYNAMIC_TOOL_CALLERS,
    DYNAMIC_TOOL_COLUMNS_MAP,
    DYNAMIC_TOOL_DESC_MAP,
    DYNAMIC_TOOL_EXTRA_ARGS_KEYS,
    agent_tools,
    dynamic_tool_names,
    get_census_tracts_from_area_code,
    get_geographic_area_code,
    make_table_name,
)

logger = logging.getLogger(__name__)

_PROMPT_PATH = Path(__file__).parent.parent.parent / "config" / "prompt.md"
_SYSTEM_PROMPT_TEMPLATE = _PROMPT_PATH.read_text(encoding="utf-8")

_WRITE_OPS_RE = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|CREATE|ALTER)\b", re.IGNORECASE
)

_GEO_SYSTEM = (
    "You are a geographic area extractor. "
    "For EVERY geographic area (city, region, etc.) mentioned in the user's message, "
    "call the `get_geographic_area_code` tool once per area. "
    "If the message mentions two cities, make two separate tool calls. "
    "If no geographic area is mentioned at all, respond only with: NO_AREA_FOUND"
)


class Area(TypedDict):
    name: str
    code: str
    tracts: list[str]


class AgentState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    areas: list[Area]
    available_tables: list[str]
    available_table_meta: dict[str, dict]


_llm = ChatAnthropic(model="claude-sonnet-4-6")  # ty:ignore[missing-argument, unknown-argument]
_geo_llm = _llm.bind_tools([get_geographic_area_code])
_agent_llm = _llm.bind_tools(agent_tools)


def _render_system_prompt(
    available_tables: list[str],
    available_table_meta: dict[str, dict],
    areas: list[Area],
) -> str:
    if not available_tables:
        table_docs = "No tool-generated tables are available yet."
    else:
        parts = []
        for tbl in available_tables:
            meta = available_table_meta.get(tbl, {})
            tool_name = meta.get("tool_name", "")
            args = meta.get("args", {})
            area_name = meta.get("area_name", "")
            base_desc = DYNAMIC_TOOL_DESC_MAP.get(tool_name, "")
            summary_parts = [f"{k}={v}" for k, v in args.items()]
            if area_name:
                summary_parts.append(f"area={area_name}")
            args_summary = ", ".join(summary_parts)
            desc = f"{base_desc} ({args_summary})" if args_summary else base_desc
            columns = DYNAMIC_TOOL_COLUMNS_MAP.get(tool_name, {})
            col_lines = "\n".join(
                f"* `{col}`: {col_desc}" for col, col_desc in columns.items()
            )
            parts.append(f"**Table: `{tbl}`** — {desc}\n{col_lines}")
        table_docs = "\n\n".join(parts)

    area_lines = "\n".join(
        f"* **{a['name']}** (code: `{a['code']}`): {len(a['tracts'])} census tracts"
        for a in areas
    )
    areas_section = (
        "\n\n## 5. Pre-Resolved Geographic Areas\n"
        "The following geographic areas have been resolved to census tracts. "
        "When you call a dynamic data tool, it will **automatically** fetch data "
        "for each area and create one DuckDB table per area — "
        "you do **not** need to supply tract codes yourself.\n\n"
        + area_lines
    )

    return (
        _SYSTEM_PROMPT_TEMPLATE.replace("{DYNAMIC_LOCAL_TABLES}", table_docs)
        + areas_section
    )


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------


def extract_area_node(state: AgentState) -> dict:
    user_message = next(
        m for m in reversed(state["messages"]) if isinstance(m, HumanMessage)
    )
    response = _geo_llm.invoke([SystemMessage(content=_GEO_SYSTEM), user_message])

    existing_areas: list[Area] = state.get("areas") or []

    if not response.tool_calls:
        if existing_areas:
            # Follow-up with no new area — keep going with what we have
            return {}
        return {
            "messages": [
                AIMessage(
                    content=(
                        "I'm sorry, but I could not identify a valid geographic area "
                        "in your query. Please mention a specific city or region."
                    )
                )
            ],
            "areas": [],
        }

    existing_codes = {a["code"] for a in existing_areas}
    resolved: list[Area] = list(existing_areas)  # start from existing
    unknown: list[str] = []
    for tool_call in response.tool_calls:
        area_name: str = tool_call["args"]["area_name"]
        result: str = get_geographic_area_code.invoke({"area_name": area_name})
        if result == "Unknown area":
            unknown.append(area_name)
        elif result not in existing_codes:
            resolved.append(Area(name=area_name, code=result, tracts=[]))
            existing_codes.add(result)

    if not resolved:
        names = ", ".join(f"'{n}'" for n in unknown)
        return {
            "messages": [
                AIMessage(
                    content=(
                        f"I'm sorry, but {names} "
                        "could not be found in the database. "
                        "Please try different area names."
                    )
                )
            ],
            "areas": [],
        }

    return {"areas": resolved}


def route_after_geo(state: AgentState) -> Literal["get_tracts", END]:  # ty:ignore[invalid-type-form]
    return "get_tracts" if state.get("areas") else END


def get_tracts_node(state: AgentState) -> dict:
    updated: list[Area] = []
    empty: list[str] = []
    for area in state["areas"]:
        if area["tracts"]:
            # Already resolved in a prior turn — keep as-is
            updated.append(area)
            continue
        tracts: list[str] = get_census_tracts_from_area_code.invoke(
            {"area_code": area["code"]}
        )
        if tracts:
            updated.append(Area(name=area["name"], code=area["code"], tracts=tracts))
        else:
            empty.append(area["name"])

    messages = []
    if empty:
        names = ", ".join(f"'{n}'" for n in empty)
        messages.append(
            AIMessage(
                content=f"No census tracts found for {names}; skipping those areas."
            )
        )
    if not updated:
        messages.append(
            AIMessage(
                content="No census tracts were found for any area. Cannot proceed."
            )
        )
    return {"areas": updated, "messages": messages} if messages else {"areas": updated}


def route_after_tracts(state: AgentState) -> Literal["agent", END]:  # ty:ignore[invalid-type-form]
    return "agent" if any(a["tracts"] for a in state.get("areas", [])) else END


def agent_node(state: AgentState) -> dict:
    system_content = _render_system_prompt(
        state.get("available_tables", []),
        state.get("available_table_meta", {}),
        state.get("areas", []),
    )
    print("\n" + "=" * 40 + " SYSTEM PROMPT " + "=" * 40)  # noqa: T201
    print(system_content)  # noqa: T201
    print("=" * 95 + "\n")  # noqa: T201
    system = SystemMessage(content=system_content)
    response = _agent_llm.invoke([system, *state["messages"]])
    return {"messages": [response]}


def route_after_agent(state: AgentState) -> Literal["tools", END]:  # ty:ignore[invalid-type-form]
    last = state["messages"][-1]
    if hasattr(last, "tool_calls") and last.tool_calls:
        return "tools"
    return END


def _handle_dynamic_tool(
    tool_call: ToolCall,
    state: AgentState,
    conn: duckdb.DuckDBPyConnection,
    new_tables: list[str],
    new_table_meta: dict[str, dict],
) -> ToolMessage:
    tool_name: str = str(tool_call["name"])
    call_id: str = str(tool_call["id"])
    extra_args: dict = tool_call["args"]
    arg_keys = DYNAMIC_TOOL_EXTRA_ARGS_KEYS[tool_name]
    caller = DYNAMIC_TOOL_CALLERS[tool_name]
    areas = state.get("areas", [])

    def _fetch(area: Area) -> tuple[Area, object]:
        """Fetch data for one area; returns (area, DataFrame) or (area, Exception)."""
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
        tbl = make_table_name(tool_name, extra_args, arg_keys, area["name"])
        if isinstance(outcome, Exception):
            errors.append(f"{area['name']}: {outcome}")
        else:
            df = pd.DataFrame(outcome)
            write_dataframe(conn, tbl, df)
            if tbl not in new_tables:
                new_tables.append(tbl)
            new_table_meta[tbl] = {
                "tool_name": tool_name,
                "args": extra_args,
                "area_name": area["name"],
            }
            created.append(f"`{tbl}` ({len(df)} rows, area={area['name']})")
    content_parts: list[str] = []
    if created:
        content_parts.append("Created tables: " + ", ".join(created))
    if errors:
        content_parts.append("Errors: " + "; ".join(errors))
    return ToolMessage(
        tool_call_id=call_id,
        content="\n".join(content_parts) or "No tables created.",
    )


def tools_node(state: AgentState, config: RunnableConfig) -> dict:
    thread_id: str = config["configurable"]["thread_id"]
    conn = get_session(thread_id)

    new_messages: list[ToolMessage] = []
    new_tables: list[str] = list(state.get("available_tables", []))
    new_table_meta: dict[str, dict] = dict(state.get("available_table_meta", {}))

    last_ai = state["messages"][-1]
    for tool_call in last_ai.tool_calls:  # ty:ignore[unresolved-attribute]
        tool_name: str = tool_call["name"]
        call_id: str = tool_call["id"]  # ty:ignore[invalid-assignment]

        if tool_name == "execute_spatial_query":
            sql: str = tool_call["args"]["sql"]
            if _WRITE_OPS_RE.search(sql):
                new_messages.append(
                    ToolMessage(
                        tool_call_id=call_id,
                        content="Error: Only SELECT queries are permitted.",
                    )
                )
                continue
            try:
                result_df = conn.execute(sql).df()
                new_messages.append(
                    ToolMessage(
                        tool_call_id=call_id,
                        content=result_df.to_markdown(index=False),
                    )
                )
            except Exception as exc:  # noqa: BLE001
                new_messages.append(
                    ToolMessage(
                        tool_call_id=call_id,
                        content=f"SQL error: {exc}",
                    )
                )

        elif tool_name in dynamic_tool_names:
            new_messages.append(
                _handle_dynamic_tool(
                    tool_call, state, conn, new_tables, new_table_meta
                )
            )

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


# ---------------------------------------------------------------------------
# Graph
# ---------------------------------------------------------------------------

_builder = StateGraph(AgentState)  # ty:ignore[invalid-argument-type]

_builder.add_node("extract_area", extract_area_node)
_builder.add_node("get_tracts", get_tracts_node)
_builder.add_node("agent", agent_node)
_builder.add_node("tools", tools_node)

_builder.add_edge(START, "extract_area")
_builder.add_conditional_edges("extract_area", route_after_geo)
_builder.add_conditional_edges("get_tracts", route_after_tracts)
_builder.add_conditional_edges("agent", route_after_agent)
_builder.add_edge("tools", "agent")

app = _builder.compile(checkpointer=MemorySaver())
