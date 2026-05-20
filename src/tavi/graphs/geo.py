import pandas as pd
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from tavi.connections import base_llm, engine
from tavi.graphs.common import load_prompt_from_name
from tavi.models import Area
from tavi.state import AgentState
from tavi.tools.static import get_geographic_area_code

geo_llm = base_llm.bind_tools([get_geographic_area_code])


SYSTEM_PROMPT_TEMPLATE = load_prompt_from_name("geo")


def extract_area_node(state: AgentState) -> dict:
    """LangGraph node: extract and resolve geographic areas from the user message.

    Invokes ``geo_llm`` on the latest ``HumanMessage`` to identify area
    names via tool calls. Resolves each name to a metro area code,
    deduplicates against already-known areas in state, and returns the
    updated ``areas`` list.

    Args:
        state: Current agent state containing ``messages`` and ``areas``.

    Returns:
        A state-patch dict with an updated ``areas`` list, or a dict
        containing an error ``AIMessage`` and an empty ``areas`` list when
        no area could be resolved.
    """
    user_message = next(
        m for m in reversed(state["messages"]) if isinstance(m, HumanMessage)
    )
    response = geo_llm.invoke(
        [SystemMessage(content=SYSTEM_PROMPT_TEMPLATE), user_message]
    )

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


def get_census_tracts_from_area_code(area_code: str) -> list[str]:
    """Return the census tract codes (AGEBs) that belong to a metro area.

    Queries the ``census_2020_ageb`` table joined with ``census_2020_mun``
    and filters by the given metro area code.

    Args:
        area_code: Metro area code as returned by
            ``get_geographic_area_code`` (e.g. ``"09.1.01"``).

    Returns:
        A list of ``cvegeo`` strings identifying each census tract in the
        area. Returns an empty list when the area code is not found.
    """
    with engine.connect() as conn:
        results = pd.read_sql(
            """
            SELECT census_2020_ageb.cvegeo FROM census_2020_ageb
            INNER JOIN census_2020_mun
                ON census_2020_ageb.cve_mun = census_2020_mun.cvegeo
            WHERE census_2020_mun.cve_met = %(area_code)s
            """,
            conn,
            params={"area_code": area_code},
        )
    return results["cvegeo"].tolist()


def get_tracts_node(state: AgentState) -> dict:
    """LangGraph node: resolve census tracts for each unresolved area.

    Keeps areas that already have tracts (from a prior turn) unchanged.
    For new areas, calls ``get_census_tracts_from_area_code`` and appends
    warning messages for any areas that return no results.

    Args:
        state: Current agent state containing ``areas``.

    Returns:
        A state-patch dict with an updated ``areas`` list and any warning
        ``AIMessage`` entries appended to ``messages``.
    """
    updated: list[Area] = []
    empty: list[str] = []
    for area in state["areas"]:
        if area["tracts"]:
            updated.append(area)
            continue
        tracts: list[str] = get_census_tracts_from_area_code(area["code"])
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
