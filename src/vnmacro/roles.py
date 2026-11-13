"""Create/update the read-only database role for Text-to-SQL and check it.

Run from the repository root (database running, .env filled in):

    PYTHONPATH=src python -m vnmacro.roles apply   # run sql/roles.sql, set password
    PYTHONPATH=src python -m vnmacro.roles check   # connect as the role, try 8 actions

`apply` connects as the owner (POSTGRES_* in .env), runs sql/roles.sql and sets the
password from DB_READER_PASSWORD. The password is hashed (SCRAM) on this machine, so
the plain text is never sent to the server, printed or logged. `check` connects with
DATABASE_URL_READER and prints one PASS/FAIL line per action.
"""

from __future__ import annotations

import argparse
import os
from typing import Any

from vnmacro import config
from vnmacro.ingest.load_db import db_connect

# SQLSTATE codes (PostgreSQL appendix A)
INSUFFICIENT_PRIVILEGE = "42501"
READ_ONLY_TRANSACTION = "25006"
QUERY_CANCELED = "57014"
EXPECTED_STATES: dict[str, set[str | None]] = {
    "ok": {None},
    "blocked": {INSUFFICIENT_PRIVILEGE, READ_ONLY_TRANSACTION},
    "timeout": {QUERY_CANCELED},
}
# label, SQL, expected outcome, run in a READ WRITE transaction. The READ WRITE rows
# turn the read-only setting off, so they test the privileges alone.
CHECKS: tuple[tuple[str, str, str, bool], ...] = (
    ("a. SELECT count(*) FROM daily_prices", "SELECT count(*) FROM daily_prices",
     "ok", False),
    ("b. INSERT INTO daily_prices", "INSERT INTO daily_prices (symbol) VALUES ('X')",
     "blocked", False),
    ("c. CREATE TABLE", "CREATE TABLE reader_probe (id int)", "blocked", False),
    ("d. SELECT FROM rag.chunks", "SELECT count(*) FROM rag.chunks", "blocked", False),
    ("e. SELECT pg_sleep(10)", "SELECT pg_sleep(10)", "timeout", False),
    ("b2. INSERT, read-write transaction",
     "INSERT INTO daily_prices (symbol) VALUES ('X')", "blocked", True),
    ("c2. CREATE TABLE, read-write transaction", "CREATE TABLE reader_probe (id int)",
     "blocked", True),
    ("c3. CREATE TEMP TABLE, read-write transaction",
     "CREATE TEMP TABLE reader_probe (id int)", "blocked", True),
)  # fmt: skip


def verdict(expected: str, sqlstate: str | None) -> bool:
    """True when the outcome (None = success, else SQLSTATE) matches the expectation."""
    return sqlstate in EXPECTED_STATES[expected]


def outcome_text(sqlstate: str | None, error_name: str | None) -> str:
    """Short description of an outcome for the report line."""
    return "succeeded" if sqlstate is None else f"{error_name} ({sqlstate})"


# ---------- I/O ----------


def apply_roles(conn: Any, sql_text: str, role: str, password: str) -> None:
    """Run the roles SQL and set the role password (SCRAM hash) in one transaction."""
    from psycopg import sql

    hashed = conn.pgconn.encrypt_password(
        password.encode(), role.encode(), b"scram-sha-256"
    ).decode()
    with conn.transaction(), conn.cursor() as cur:
        cur.execute(sql_text)
        cur.execute(
            sql.SQL("ALTER ROLE {} PASSWORD {}").format(
                sql.Identifier(role), sql.Literal(hashed)
            )
        )


def run_check(conn: Any, query: str, read_write: bool) -> tuple[str | None, str | None]:
    """Run one query in its own transaction (always rolled back); (SQLSTATE, error)."""
    import psycopg

    try:
        with conn.cursor() as cur:
            if read_write:
                cur.execute("SET TRANSACTION READ WRITE")
            cur.execute(query)
        return None, None
    except psycopg.Error as e:
        return e.sqlstate, type(e).__name__
    finally:
        conn.rollback()


def main(argv: list[str] | None = None) -> None:
    """Command-line entry point."""
    import psycopg
    from dotenv import load_dotenv

    parser = argparse.ArgumentParser(description="Read-only role for Text-to-SQL.")
    parser.add_argument("action", choices=("apply", "check"))
    args = parser.parse_args(argv)
    load_dotenv()

    if args.action == "apply":
        password = os.environ.get("DB_READER_PASSWORD")
        if not password:
            raise SystemExit("DB_READER_PASSWORD is not set in .env")
        with db_connect() as conn:
            apply_roles(
                conn, config.ROLES_SQL.read_text(), config.READER_ROLE, password
            )
        print(f"Role {config.READER_ROLE} created/updated from {config.ROLES_SQL}")
        return

    url = os.environ.get("DATABASE_URL_READER")
    if not url:
        raise SystemExit("DATABASE_URL_READER is not set in .env")
    failed = 0
    with psycopg.connect(url) as conn:
        for label, query, expected, read_write in CHECKS:
            state, name = run_check(conn, query, read_write)
            ok = verdict(expected, state)
            failed += not ok
            print(f"{'PASS' if ok else 'FAIL'}  {label}: {outcome_text(state, name)}")
    if failed:
        raise SystemExit(f"{failed} check(s) failed")


if __name__ == "__main__":
    main()
