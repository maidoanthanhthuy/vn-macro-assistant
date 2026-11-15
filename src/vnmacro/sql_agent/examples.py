"""Few-shot SQL examples for the LLM (prompts/sql_examples.md).

Check every example against the database as the read-only role (database running,
.env filled in):

    PYTHONPATH=src python -m vnmacro.sql_agent.examples
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from vnmacro import config

_EXAMPLE_RE = re.compile(r"^Question: (.+?)\n+```sql\n(.*?)\n```", re.M | re.S)


def parse_examples(text: str) -> list[tuple[str, str]]:
    """Extract (question, sql) pairs from the examples markdown, in file order."""
    return [(q.strip(), s.strip()) for q, s in _EXAMPLE_RE.findall(text)]


def load_sql_examples(path: Path = config.SQL_EXAMPLES_FILE) -> str:
    """Return the examples file verbatim (the text that goes into the prompt)."""
    return path.read_text(encoding="utf-8")


def run_example(conn: Any, query: str, n_preview: int) -> tuple[list[str], list[tuple]]:
    """Run one query in a rolled-back transaction; (column names, first rows)."""
    try:
        with conn.cursor() as cur:
            cur.execute(query)
            names = [d.name for d in cur.description]
            return names, cur.fetchall()[:n_preview] if n_preview else cur.fetchall()
    finally:
        conn.rollback()


def main(n_preview: int = 3) -> None:
    """Run every example as the read-only role; print status, row count and rows."""
    import psycopg
    from dotenv import load_dotenv

    from vnmacro.sql_agent.context import format_rows

    load_dotenv()
    url = os.environ.get("DATABASE_URL_READER")
    if not url:
        raise SystemExit("DATABASE_URL_READER is not set in .env")
    failed = 0
    with psycopg.connect(url) as conn:
        conn.read_only = True
        for i, (question, query) in enumerate(parse_examples(load_sql_examples()), 1):
            try:
                names, rows = run_example(conn, query, 0)
            except psycopg.Error as e:
                failed += 1
                print(f"[{i}] ERROR {type(e).__name__}: {e}".strip())
                continue
            print(f"[{i}] OK, {len(rows)} row(s): {question}")
            print(format_rows(names, rows[:n_preview]), end="\n\n")
    if failed:
        raise SystemExit(f"{failed} example(s) failed")


if __name__ == "__main__":
    main()
