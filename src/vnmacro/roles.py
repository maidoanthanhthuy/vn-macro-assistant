"""Create/update the database roles for the agent and check them.

Run from the repository root (database running, .env filled in):

    PYTHONPATH=src python -m vnmacro.roles apply   # run sql/roles.sql, set passwords
    PYTHONPATH=src python -m vnmacro.roles check   # connect as each role, try actions
    PYTHONPATH=src python -m vnmacro.roles check --target neon

`--target` picks the database (config.DB_TARGETS): local (default, owner from
POSTGRES_*) or neon (owner NEON_DATABASE_URL, a non-superuser). `apply` connects as the
owner, runs sql/roles.sql and sets the password of every role of the target from
.env. Locally, passwords are hashed (SCRAM) on this machine, so the plain text is never
sent to the server; Neon accepts only plain-text passwords, sent over TLS. Passwords
are never printed or logged. `check` connects with each role's URL and prints one
PASS/FAIL line per action; the logger's test INSERT is rolled back, and the owner
then deletes any leftover test row.
"""

from __future__ import annotations

import argparse
import os
import uuid
from collections.abc import Mapping
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
PROBE_COMPONENT = "roles_check"  # component of the logger's test row
RUN_ID_SLOT = "{run_id}"  # replaced by a fresh uuid4 when the check runs
PROBE_INSERT = (
    "INSERT INTO app.query_log (run_id, component, question, status) "
    f"VALUES ('{RUN_ID_SLOT}', '{PROBE_COMPONENT}', 'probe', 'cannot_answer')"
)
PROBE_CLEANUP = f"DELETE FROM app.query_log WHERE component = '{PROBE_COMPONENT}'"
# role, label, SQL, expected outcome, run in a READ WRITE transaction. The READ WRITE
# rows turn the reader's read-only setting off, so they test the privileges alone.
R, L = config.READER_ROLE, config.LOGGER_ROLE
CHECKS: tuple[tuple[str, str, str, str, bool], ...] = (
    (R, "a. SELECT count(*) FROM daily_prices", "SELECT count(*) FROM daily_prices",
     "ok", False),
    (R, "b. INSERT INTO daily_prices", "INSERT INTO daily_prices (symbol) VALUES ('X')",
     "blocked", False),
    (R, "c. CREATE TABLE", "CREATE TABLE reader_probe (id int)", "blocked", False),
    (R, "d. SELECT FROM rag.chunks", "SELECT count(*) FROM rag.chunks", "ok", False),
    (R, "e. SELECT pg_sleep(10)", "SELECT pg_sleep(10)", "timeout", False),
    (R, "b2. INSERT, read-write transaction",
     "INSERT INTO daily_prices (symbol) VALUES ('X')", "blocked", True),
    (R, "c2. CREATE TABLE, read-write transaction",
     "CREATE TABLE reader_probe (id int)", "blocked", True),
    (R, "c3. CREATE TEMP TABLE, read-write transaction",
     "CREATE TEMP TABLE reader_probe (id int)", "blocked", True),
    (R, "f. SELECT FROM app.query_log", "SELECT count(*) FROM app.query_log",
     "blocked", False),
    (L, "g. INSERT INTO app.query_log (rolled back)", PROBE_INSERT, "ok", False),
    (L, "h. SELECT FROM app.query_log", "SELECT count(*) FROM app.query_log",
     "blocked", False),
    (L, "i. SELECT FROM public.daily_prices",
     "SELECT count(*) FROM public.daily_prices", "blocked", False),
    (L, "j. INSERT INTO public.daily_prices",
     "INSERT INTO public.daily_prices (symbol) VALUES ('X')", "blocked", False),
    (L, "k. SELECT FROM rag.chunks", "SELECT count(*) FROM rag.chunks", "blocked",
     False),
    (L, "l. CREATE TABLE in app", "CREATE TABLE app.logger_probe (id int)", "blocked",
     False),
    (L, "m. CREATE TEMP TABLE", "CREATE TEMP TABLE logger_probe (id int)", "blocked",
     False),
)  # fmt: skip


def role_settings(
    role_env: Mapping[str, tuple[str, str]], env: Mapping[str, str], index: int
) -> tuple[dict[str, str], list[str]]:
    """Pick one .env value per role (0 = password, 1 = URL); (values, missing names)."""
    values, missing = {}, []
    for role, names in role_env.items():
        value = env.get(names[index], "")
        if value:
            values[role] = value
        else:
            missing.append(names[index])
    return values, missing


def verdict(expected: str, sqlstate: str | None) -> bool:
    """True when the outcome (None = success, else SQLSTATE) matches the expectation."""
    return sqlstate in EXPECTED_STATES[expected]


def outcome_text(sqlstate: str | None, error_name: str | None) -> str:
    """Short description of an outcome for the report line."""
    return "succeeded" if sqlstate is None else f"{error_name} ({sqlstate})"


# ---------- I/O ----------


def owner_connect(target: dict) -> Any:
    """Owner connection of a target: its URL variable, or POSTGRES_* when None."""
    import psycopg

    if target["owner_url_env"] is None:
        return db_connect()
    url = os.environ.get(target["owner_url_env"])
    if not url:
        raise SystemExit(f"Not set in .env: {target['owner_url_env']}")
    return psycopg.connect(url)


def apply_roles(
    conn: Any, sql_text: str, passwords: Mapping[str, str], hash_passwords: bool = True
) -> None:
    """Run the roles SQL and set each role password in one transaction.

    With hash_passwords the password is sent as a SCRAM hash made on this machine;
    without it (Neon accepts only plain text) it is sent as is, over the TLS connection.
    """
    from psycopg import sql

    with conn.transaction(), conn.cursor() as cur:
        cur.execute(sql_text)
        for role, password in passwords.items():
            value = password
            if hash_passwords:
                value = conn.pgconn.encrypt_password(
                    password.encode(), role.encode(), b"scram-sha-256"
                ).decode()
            cur.execute(
                sql.SQL("ALTER ROLE {} PASSWORD {}").format(
                    sql.Identifier(role), sql.Literal(value)
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

    parser = argparse.ArgumentParser(description="Database roles for the agent.")
    parser.add_argument("action", choices=("apply", "check"))
    parser.add_argument("--target", choices=sorted(config.DB_TARGETS), default="local")
    args = parser.parse_args(argv)
    load_dotenv()
    target = config.DB_TARGETS[args.target]

    if args.action == "apply":
        passwords, missing = role_settings(target["roles"], os.environ, 0)
        if missing:
            raise SystemExit(f"Not set in .env: {', '.join(missing)}")
        with owner_connect(target) as conn:
            apply_roles(
                conn, config.ROLES_SQL.read_text(), passwords, target["hash_passwords"]
            )
        print(f"Roles {', '.join(passwords)} created/updated from {config.ROLES_SQL}")
        return

    urls, missing = role_settings(target["roles"], os.environ, 1)
    if missing:
        raise SystemExit(f"Not set in .env: {', '.join(missing)}")
    failed = 0
    for role, url in urls.items():
        with psycopg.connect(url) as conn:
            for check_role, label, query, expected, read_write in CHECKS:
                if check_role != role:
                    continue
                query = query.replace(RUN_ID_SLOT, str(uuid.uuid4()))
                state, name = run_check(conn, query, read_write)
                ok = verdict(expected, state)
                failed += not ok
                print(
                    f"{'PASS' if ok else 'FAIL'}  {role} {label}: "
                    f"{outcome_text(state, name)}"
                )
    with owner_connect(target) as conn, conn.cursor() as cur:
        leftover = cur.execute(PROBE_CLEANUP).rowcount
    ok = leftover == 0
    failed += not ok
    print(f"{'PASS' if ok else 'FAIL'}  owner g2. test rows left in app.query_log: "
          f"{leftover} (deleted)")  # fmt: skip
    if failed:
        raise SystemExit(f"{failed} check(s) failed")


if __name__ == "__main__":
    main()
