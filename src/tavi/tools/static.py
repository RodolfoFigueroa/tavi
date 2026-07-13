"""
Security model
--------------
SQL validation is performed in two layers before any query reaches DuckDB:

1. **Regex pre-filter** (fast, cheap): rejects obvious write keywords.
2. **AST interceptor via sqlglot** (authoritative): parses the query into
   an abstract syntax tree and rejects anything that is not a single SELECT
   statement, blocks file-access functions (read_csv, read_parquet, …),
   and rejects multi-statement payloads used for SQL injection.

If either layer rejects the query it is never sent to DuckDB.
"""

import re

import sqlglot
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from sqlglot import exp

from tavi.db import get_session

# ---------------------------------------------------------------------------
# Layer 1 – fast regex pre-filter (defence-in-depth, not the primary guard)
# ---------------------------------------------------------------------------

_WRITE_OPS_RE = re.compile(r"\b(INSERT|UPDATE|DELETE|DROP|CREATE|ALTER)\b", re.IGNORECASE)
_EXTERNAL_READ_RE = re.compile(
    r"\b(read_csv|read_csv_auto|read_parquet|read_json|read_json_auto"
    r"|read_text|scan_csv|scan_parquet|glob)\s*\(",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Layer 2 – AST interceptor (authoritative)
# ---------------------------------------------------------------------------

# Statement types that are never allowed at the root or nested inside a query.
_BLOCKED_STATEMENT_TYPES = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Drop,
    exp.Create,
    exp.Alter,
    exp.Command,
    exp.Copy,
)

# AST node types that represent filesystem or network reads.
_BLOCKED_NODE_TYPES = (
    exp.ReadCSV,  # read_csv('/path')
    exp.ReadParquet,  # read_parquet('s3://...')
)

# Function names not recognised as first-class sqlglot nodes (Anonymous nodes).
_BLOCKED_ANONYMOUS_FUNCTIONS: frozenset[str] = frozenset(
    {
        "read_json",
        "read_json_auto",
        "read_text",
        "scan_csv",
        "scan_parquet",
        "glob",
        "httpfs",
    }
)


def _validate_ast(sql: str) -> tuple[bool, str]:
    """Validate *sql* against the AST-based security policy.

    Args:
        sql: Raw SQL string submitted by the LLM.

    Returns:
        A ``(is_safe, reason)`` tuple. ``is_safe`` is ``True`` only when the
        query is a single, read-only ``SELECT`` statement with no forbidden
        nodes anywhere in its syntax tree.
    """
    try:
        statements = sqlglot.parse(sql, dialect="duckdb")
    except sqlglot.errors.ParseError as exc:
        return False, f"SQL parse error: {exc}"

    real = [s for s in statements if s is not None]

    if not real:
        return False, "Empty or unparseable query"

    # Reject multi-statement payloads (classic SQL injection vector).
    if len(real) > 1:
        return False, "Multiple statements are not allowed"

    stmt = real[0]

    # Root must be a SELECT.
    if isinstance(stmt, _BLOCKED_STATEMENT_TYPES):
        return False, f"Forbidden statement type: {type(stmt).__name__}"
    if not isinstance(stmt, exp.Select):
        return False, f"Only SELECT is allowed at root, got: {type(stmt).__name__}"

    # Walk the full syntax tree looking for dangerous nodes.
    for node in stmt.walk():
        if isinstance(node, _BLOCKED_NODE_TYPES):
            return False, f"Forbidden file-access function: {type(node).__name__}"
        if isinstance(node, exp.Anonymous):
            if node.name.lower() in _BLOCKED_ANONYMOUS_FUNCTIONS:
                return False, f"Forbidden function: {node.name}"
        # Catch destructive operations nested inside subqueries.
        if isinstance(node, _BLOCKED_STATEMENT_TYPES):
            return False, f"Forbidden nested operation: {type(node).__name__}"

    return True, "OK"


# ---------------------------------------------------------------------------
# Area map
# ---------------------------------------------------------------------------

_AREA_MAP: dict[str, str] = {
    "Mexico City": "09.1.01",
    "Monterrey": "19.1.01",
    "Guadalajara": "14.1.01",
}

# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@tool
def execute_spatial_query(sql: str, config: RunnableConfig) -> str:
    """Execute a DuckDB SELECT query against available local tables.

    The query is validated through two security layers before reaching DuckDB:
    a fast regex pre-filter and a full AST inspection with sqlglot. Any query
    that is not a single, read-only SELECT statement is rejected with an error
    message — the rejection reason is intentionally generic to avoid leaking
    internal schema details.

    Args:
        sql: A DuckDB-compatible SELECT statement to execute.
        config: LangGraph runnable config; injected automatically and not
            exposed to the LLM. Provides the ``thread_id`` used to look up
            the active DuckDB session.

    Returns:
        Query results formatted as a Markdown table string, or a safe error
        string if validation fails or the query raises an exception.
    """
    # Layer 1 – regex (fast rejection of obvious write operations)
    if _WRITE_OPS_RE.search(sql):
        return "Error: Only SELECT queries are permitted."
    if _EXTERNAL_READ_RE.search(sql):
        return "Error: External file access is not permitted."

    # Layer 2 – AST (authoritative structural validation)
    is_safe, reason = _validate_ast(sql)
    if not is_safe:
        return f"Error: Query rejected by security policy."

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
