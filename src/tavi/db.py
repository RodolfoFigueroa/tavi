import os
import re

import duckdb
import pandas as pd

_sessions: dict[str, duckdb.DuckDBPyConnection] = {}

_SAFE_IDENTIFIER_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


def get_session(thread_id: str) -> duckdb.DuckDBPyConnection:
    """Return the DuckDB connection for the given thread, creating it if needed.

    On first access, installs and loads the ``postgres`` and ``spatial``
    extensions, then attaches the Postgres database specified by the
    ``DATABASE_URL`` environment variable as ``pg_db``.

    Args:
        thread_id: Unique identifier for the conversation thread. Used as the
            cache key for the in-process connection pool.

    Returns:
        A live DuckDB connection with the Postgres database attached.
    """
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
    """Write a DataFrame to a DuckDB table, replacing it if it already exists.

    Validates the table name against a safe-identifier pattern, registers the
    DataFrame as a temporary view, materialises it into a permanent DuckDB
    table via ``CREATE OR REPLACE TABLE``, then drops the temporary view.

    Args:
        conn: Active DuckDB connection to write into.
        table_name: Name of the target table. Must match
            ``^[a-zA-Z_][a-zA-Z0-9_]*$``.
        df: DataFrame whose contents will populate the table.

    Raises:
        ValueError: If ``table_name`` contains characters outside the allowed
            safe-identifier pattern.
    """
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


def append_to_table(
    conn: duckdb.DuckDBPyConnection, table_name: str, df: pd.DataFrame
) -> None:
    """Append a DataFrame to a DuckDB table, creating it if it does not exist.

    Validates the table name against a safe-identifier pattern, registers the
    DataFrame as a temporary view, then either inserts into the existing table
    or creates it from the incoming data.

    Args:
        conn: Active DuckDB connection to write into.
        table_name: Name of the target table. Must match
            ``^[a-zA-Z_][a-zA-Z0-9_]*$``.
        df: DataFrame whose contents will be appended to the table.

    Raises:
        ValueError: If ``table_name`` contains characters outside the allowed
            safe-identifier pattern.
    """
    if not _SAFE_IDENTIFIER_RE.match(table_name):
        msg = f"Invalid table name: {table_name!r}"
        raise ValueError(msg)
    conn.register("_incoming_df_", df)
    try:
        row = conn.execute(
            "SELECT count(*) FROM duckdb_tables() WHERE table_name = ?",
            [table_name],
        ).fetchone()
        count = row[0] if row else 0
        if count:
            conn.execute(f"INSERT INTO {table_name} SELECT * FROM _incoming_df_")  # noqa: S608
        else:
            conn.execute(
                f"CREATE TABLE {table_name} AS SELECT * FROM _incoming_df_"  # noqa: S608
            )
    finally:
        conn.execute("DROP VIEW IF EXISTS _incoming_df_")
