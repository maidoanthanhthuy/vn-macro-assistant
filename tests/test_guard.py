import pytest

from vnmacro.sql_agent import guard

TABLES = ("symbols", "daily_prices", "indicators", "macro_annual", "cpi_monthly",
          "policy_events")  # fmt: skip


def check(sql: str) -> guard.CheckResult:
    return guard.check_sql(sql, TABLES, max_rows=200)


VALID = [
    "SELECT symbol, close FROM daily_prices WHERE symbol = 'FPT' LIMIT 1",
    "WITH s AS (SELECT symbol FROM symbols) SELECT * FROM s LIMIT 10",
    "SELECT d.close FROM public.daily_prices d JOIN symbols s USING (symbol) LIMIT 5",
    "SELECT year FROM macro_annual UNION SELECT 2026 LIMIT 3",
    "SELECT count(DISTINCT announced_date) FROM policy_events LIMIT 1",
    "SELECT month, inflation_yoy FROM cpi_monthly ORDER BY month DESC LIMIT 1;",
    # look like writes but are not
    "SELECT 'delete from symbols' AS note, 'drop' AS x FROM symbols LIMIT 1",
    "SELECT symbol AS deleted_at, symbol AS update_flag FROM symbols LIMIT 1",
    "-- delete everything\nSELECT 1 AS a FROM symbols /* insert */ LIMIT 1",
    "SELECT x FROM generate_series(1, 3) AS x LIMIT 3",
    "SELECT date FROM daily_prices FETCH FIRST 5 ROWS ONLY",
]


@pytest.mark.parametrize("sql", VALID)
def test_valid_queries_pass(sql):
    res = check(sql)
    assert res.ok, res.error


BLOCKED = {
    "two statements": "SELECT 1 FROM symbols; SELECT 2 FROM symbols",
    "select then drop": "SELECT * FROM symbols; DROP TABLE symbols",
    "not a select": "DELETE FROM symbols",
    "update": "UPDATE symbols SET name = 'x'",
    "values": "VALUES (1)",
    "explain": "EXPLAIN SELECT * FROM symbols",
    "copy": "COPY symbols TO '/tmp/x'",
    "delete in cte": "WITH x AS (DELETE FROM symbols RETURNING *) SELECT * FROM x",
    "update in cte": "WITH x AS (UPDATE symbols SET name = 'a' RETURNING *) "
    "SELECT * FROM x",
    "insert in cte": "WITH x AS (INSERT INTO symbols (symbol) VALUES ('A') "
    "RETURNING *) SELECT * FROM x",
    "select into": "SELECT * INTO new_table FROM symbols",
    "for update": "SELECT * FROM symbols FOR UPDATE",
    "for share": "SELECT * FROM symbols FOR SHARE",
    "pg_sleep": "SELECT pg_sleep(10)",
    "pg_sleep upper": "SELECT PG_SLEEP(10)",
    "pg_sleep quoted": 'SELECT "pg_sleep"(10)',
    "pg_sleep qualified": "SELECT pg_catalog.pg_sleep(10)",
    "pg_sleep as table": "SELECT * FROM pg_sleep(10)",
    "set_config": "SELECT set_config('statement_timeout', '0', false)",
    "pg_read_file": "SELECT pg_read_file('/etc/passwd')",
    "pg_read_binary_file": "SELECT pg_read_binary_file('/etc/passwd')",
    "pg_ls_dir": "SELECT pg_ls_dir('.')",
    "pg_terminate_backend": "SELECT pg_terminate_backend(1)",
    "pg_cancel_backend": "SELECT pg_cancel_backend(1)",
    "lo_import": "SELECT lo_import('/etc/passwd')",
    "lo_export": "SELECT lo_export(1, '/tmp/x')",
    "dblink": "SELECT * FROM dblink('db', 'SELECT 1') AS t(a int)",
    "query_to_xml": "SELECT query_to_xml('DELETE FROM symbols', true, false, '')",
    "blocked in subquery": "SELECT * FROM symbols WHERE symbol = "
    "(SELECT pg_sleep(1)::text)",
    "schema rag": "SELECT * FROM rag.chunks",
    "schema app": "SELECT * FROM app.query_log",
    "schema pg_catalog": "SELECT * FROM pg_catalog.pg_roles",
    "schema information_schema": "SELECT * FROM information_schema.tables",
    "catalog table unqualified": "SELECT * FROM pg_class",
    "rag in subquery": "SELECT * FROM symbols WHERE symbol IN "
    "(SELECT doc_id FROM rag.documents)",
    "database prefix": "SELECT * FROM otherdb.public.symbols",
    "unparsable": "SELEC * FRM symbols",
    "empty": "  ;  ",
}


@pytest.mark.parametrize("name", list(BLOCKED))
def test_evasions_are_blocked(name):
    res = check(BLOCKED[name])
    assert not res.ok, name
    assert res.error


def test_cte_name_is_not_a_table_bypass():
    # a CTE may shadow nothing outside public: schema-qualified names still fail
    assert not check("WITH chunks AS (SELECT 1) SELECT * FROM rag.chunks").ok


def test_limit_added_when_missing():
    res = check("SELECT symbol FROM symbols")
    assert res.ok and res.sql.endswith("LIMIT 200")
    assert res.notes == ("LIMIT was missing; set to 200.",)


def test_limit_lowered_when_too_large():
    res = check("SELECT symbol FROM symbols LIMIT 5000")
    assert res.ok and res.sql.endswith("LIMIT 200")
    assert "LIMIT 5000 lowered to 200" in res.notes[0]


def test_limit_kept_and_sql_unchanged_when_ok():
    sql = "SELECT symbol\nFROM symbols  -- keep me\nLIMIT 7"
    res = check(sql + ";")
    assert res.ok and res.sql == sql and res.notes == ()


def test_non_literal_limit_replaced():
    for sql in ("SELECT 1 FROM symbols LIMIT ALL",
                "SELECT 1 FROM symbols LIMIT (SELECT 1000)"):  # fmt: skip
        res = check(sql)
        assert res.ok and res.sql.endswith("LIMIT 200"), sql


def test_union_limit_applies_to_whole_query():
    res = check("SELECT 1 AS a FROM symbols UNION SELECT 2 FROM symbols")
    assert res.ok and res.sql.endswith("LIMIT 200")


def test_is_blocked_function_prefixes():
    assert guard.is_blocked_function("pg_advisory_lock")
    assert guard.is_blocked_function("LO_UNLINK")
    assert not guard.is_blocked_function("count")
    assert not guard.is_blocked_function("date_trunc")
