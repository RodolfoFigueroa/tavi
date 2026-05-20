import re

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from tavi.db import get_session

_WRITE_OPS_RE = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|CREATE|ALTER)\b", re.IGNORECASE
)

_AREA_MAP: dict[str, str] = {
    "Mexico City": "09.1.01",
    "Monterrey": "19.1.01",
}


@tool
def execute_spatial_query(sql: str, config: RunnableConfig) -> str:
    """Execute a DuckDB SELECT query against available local tables.

    Args:
        sql: A DuckDB-compatible SELECT statement to execute.
        config: LangGraph runnable config; injected automatically and not
            exposed to the LLM. Provides the ``thread_id`` used to look up
            the active DuckDB session.

    Returns:
        Query results formatted as a Markdown table string, or an error
        string if the query contains write operations or raises an exception.
    """
    if _WRITE_OPS_RE.search(sql):
        return "Error: Only SELECT queries are permitted."
    thread_id: str = config["configurable"]["thread_id"]
    conn = get_session(thread_id)
    try:
        return conn.execute(sql).df().to_markdown(index=False)
    except Exception as exc:  # noqa: BLE001
        return f"SQL error: {exc}"


@tool
def get_geographic_area_code(area_name: str) -> str:
    """Return the geographic metro-area code for a known city name.

    Looks up ``area_name`` in a hardcoded mapping of supported cities.

    Args:
        area_name: Human-readable city or metro area name
            (e.g. ``"Mexico City"``).

    Returns:
        The metro area code string (e.g. ``"09.1.01"``), or
        ``"Unknown area"`` if the name is not in the mapping.
    """
    return _AREA_MAP.get(area_name, "Unknown area")
