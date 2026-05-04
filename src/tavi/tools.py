from typing import Annotated

import duckdb
from langchain_core.messages import ToolMessage
from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState

from tavi.state import AgentState


@tool
def execute_spatial_query(
    sql_query: str,
    state: Annotated[dict, InjectedState],
) -> str:
    """Executes a DuckDB query joining PostGIS and local tables."""

    con = duckdb.connect()
    try:
        con.execute("INSTALL spatial; LOAD spatial;")

        # READ from the state: Register any DataFrames currently in memory
        tables_in_memory = state.get("local_tables", {})
        for table_name, df in tables_in_memory.items():
            con.register(table_name, df)

        result_df = con.execute(sql_query).df()
        return result_df.to_string()

    except Exception as e:  # noqa: BLE001
        return f"SQL Error: {e!s}"
    finally:
        con.close()


def execute_tools_node(state: AgentState):
    last_message = state["messages"][-1]
    state_updates = {"messages": [], "local_tables": {}}

    for tool_call in last_message.tool_calls:
        if tool_call["name"] == "fetch_temperatures_by_location":
            region = tool_call["args"]["region_name"]
            df = fetch_temperatures_logic(region)

            state_updates["local_tables"]["local_temps"] = df

            msg = ToolMessage(
                content=f"Success: Temperature data for {region} saved to 'local_temps'.",
                tool_call_id=tool_call["id"],
            )
            state_updates["messages"].append(msg)
    return state_updates


all_tools = [execute_spatial_query]
