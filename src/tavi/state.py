from typing import Annotated, TypedDict

from langgraph.graph.message import add_messages


def merge_tables(existing_tables: dict | None, new_tables: dict | None) -> dict:
    if existing_tables is None:
        existing_tables = {}
    if new_tables is None:
        new_tables = {}
    # Combine the two dictionaries
    return {**existing_tables, **new_tables}


class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    local_tables: Annotated[dict, merge_tables]
