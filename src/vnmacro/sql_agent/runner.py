"""Database I/O for Text-to-SQL: run a checked query as the reader, write the log."""

from __future__ import annotations

import logging
from typing import Any

from vnmacro import config

log = logging.getLogger(__name__)


class QueryError(Exception):
    """The database rejected or failed a generated query (sent back to the LLM)."""


LOG_COLUMNS: tuple[str, ...] = (
    "run_id", "component", "question", "model", "prompt_version", "status",
    "final_sql", "attempts", "sql_attempts", "error", "row_count", "latency_ms",
    "input_tokens", "cached_input_tokens", "output_tokens", "cost_usd", "request_id",
)  # fmt: skip


def run_select(
    url: str,
    sql: str,
    timeout: str = config.SQL_STATEMENT_TIMEOUT,
    max_rows: int = config.SQL_MAX_ROWS,
) -> tuple[list[str], list[tuple[Any, ...]]]:
    """Run one query as the reader in a READ ONLY transaction, always rolled back.

    Uses the reused connection of vnmacro.db (reconnects once if it was lost).
    """
    import psycopg
    from psycopg import sql as pgsql

    from vnmacro.db import with_connection

    set_timeout = pgsql.SQL("SET LOCAL statement_timeout = {}").format(
        pgsql.Literal(timeout)
    )

    def run(conn: Any) -> tuple[list[str], list[tuple[Any, ...]]]:
        with conn.cursor() as cur:
            cur.execute("BEGIN READ ONLY")
            try:
                cur.execute(set_timeout)
                try:
                    cur.execute(sql)
                except psycopg.Error as e:
                    if conn.broken:  # connection lost: let with_connection retry
                        raise
                    state = f" [{e.sqlstate}]" if e.sqlstate else ""
                    raise QueryError(f"{type(e).__name__}{state}: {e}".strip()) from e
                names = [d.name for d in cur.description or []]
                return names, cur.fetchmany(max_rows)
            finally:
                if not (conn.broken or conn.closed):
                    cur.execute("ROLLBACK")

    return with_connection(url, run)


def write_log(url: str, row: dict[str, Any]) -> None:
    """Insert one app.query_log row as the logger (no RETURNING); warn on failure.

    Columns missing from row (e.g. request_id outside the agent) are inserted as NULL.
    """
    try:
        from psycopg import sql
        from psycopg.types.json import Jsonb

        from vnmacro.db import with_connection

        values = {c: row.get(c) for c in LOG_COLUMNS}
        values["sql_attempts"] = Jsonb(row.get("sql_attempts") or [])
        query = sql.SQL("INSERT INTO app.query_log ({}) VALUES ({})").format(
            sql.SQL(", ").join(map(sql.Identifier, LOG_COLUMNS)),
            sql.SQL(", ").join(sql.Placeholder(c) for c in LOG_COLUMNS),
        )
        with_connection(url, lambda conn: conn.execute(query, values))
    except Exception as e:  # logging must never break the answer
        log.warning("query_log insert failed: %s", e)
