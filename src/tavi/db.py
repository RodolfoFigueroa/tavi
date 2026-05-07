import os
import re

import duckdb
import pandas as pd

_sessions: dict[str, duckdb.DuckDBPyConnection] = {}
_SAFE_IDENTIFIER_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


def get_session(thread_id: str) -> duckdb.DuckDBPyConnection:
    """Return the DuckDB connection for the given thread, creating it if needed."""
    if thread_id not in _sessions:
        conn = duckdb.connect()
        conn.execute("INSTALL postgres; LOAD postgres;")
        conn.execute("INSTALL spatial; LOAD spatial;")
        conn.execute(
            f"ATTACH '{os.environ['DATABASE_URL']}' AS pg_db (TYPE postgres, READ_ONLY)"
        )
        _sessions[thread_id] = conn
    return _sessions[thread_id]


def write_dataframe(
    conn: duckdb.DuckDBPyConnection, table_name: str, df: pd.DataFrame
) -> None:
    """Write a DataFrame to a DuckDB table, replacing it if it already exists."""
    if not _SAFE_IDENTIFIER_RE.match(table_name):
        msg = f"Invalid table name: {table_name!r}"
        raise ValueError(msg)
    # Register the DataFrame as a named view so DuckDB can read it,
    # then materialise it into a permanent table.
    conn.register("_incoming_df_", df)
    try:
        sql = (
            f"CREATE OR REPLACE TABLE {table_name}"  # noqa: S608
            " AS SELECT * FROM _incoming_df_"
        )
        conn.execute(sql)
    finally:
        conn.execute("DROP VIEW IF EXISTS _incoming_df_")
