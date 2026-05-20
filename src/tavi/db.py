import os
import re
import threading
from pathlib import Path
from urllib.parse import quote_plus

import duckdb
import pandas as pd

_sessions: dict[str, duckdb.DuckDBPyConnection] = {}
_sessions_lock = threading.Lock()

_SAFE_IDENTIFIER_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")

# Install extensions once per process; LOAD is still required per connection.
with duckdb.connect() as _tmp:
    _tmp.execute("INSTALL postgres; INSTALL spatial;")

_DEMOGRAPHICS_VIEW_SQL = (Path(__file__).parents[2] / "config" / "view.sql").read_text()


def get_session(thread_id: str) -> duckdb.DuckDBPyConnection:
    """Return the DuckDB connection for the given thread, creating it if needed.

    On first access, installs and loads the ``postgres`` and ``spatial``
    extensions, then attaches the Postgres database specified by the
    ``POSTGRES_*`` environment variables as ``pg_db``.

    Args:
        thread_id: Unique identifier for the conversation thread. Used as the
            cache key for the in-process connection pool.

    Returns:
        A live DuckDB connection with the Postgres database attached.
    """
    with _sessions_lock:
        if thread_id not in _sessions:
            conn = duckdb.connect()
            conn.execute("LOAD postgres;")
            conn.execute("LOAD spatial;")
            user = quote_plus(os.environ["POSTGRES_USER"])
            password = quote_plus(os.environ["POSTGRES_PASSWORD"])
            host = os.environ["POSTGRES_HOST"]
            port = os.environ["POSTGRES_PORT"]
            db = os.environ["POSTGRES_DB"]
            conn.execute(
                f"ATTACH 'postgresql://{user}:{password}@{host}:{port}/{db}'"
                " AS pg_db (TYPE postgres, READ_ONLY)"
            )
            conn.execute(_DEMOGRAPHICS_VIEW_SQL)
            _sessions[thread_id] = conn
    return _sessions[thread_id]


def close_session(thread_id: str) -> None:
    """Close and remove the DuckDB session for the given thread.

    Closes the DuckDB connection (which also releases the attached PostgreSQL
    connection) and removes it from the session cache. Safe to call if the
    session does not exist.

    Args:
        thread_id: Unique identifier for the conversation thread.
    """
    with _sessions_lock:
        conn = _sessions.pop(thread_id, None)
    if conn is not None:
        conn.close()


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
