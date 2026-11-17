import datetime as dt
from decimal import Decimal

from vnmacro.eval import run_sql_dev as ev

REFS = """-- Header comment
-- q01: first.
SELECT date, close
FROM daily_prices
LIMIT 1;

-- Reality check: no id, skipped.
SELECT 1;

-- q02: second (comment lines inside are skipped).
-- more comment
WITH a AS (SELECT 1 AS x)
SELECT x FROM a;
"""


def test_select_questions():
    rows = [
        {"id": "q1", "expected_tool": "sql"},
        {"id": "q2", "expected_tool": "rag"},
        {"id": "q3", "expected_tool": "sql+rag"},
        {"id": "q4", "expected_tool": "none"},
    ]
    assert [r["id"] for r in ev.select_questions(rows)] == ["q1", "q3"]


def test_parse_reference_sql():
    refs = ev.parse_reference_sql(REFS)
    assert set(refs) == {"q01", "q02"}
    assert refs["q01"] == "SELECT date, close\nFROM daily_prices\nLIMIT 1;"
    assert refs["q02"].startswith("WITH a AS") and refs["q02"].endswith(";")


def test_key_values_first_and_all():
    cols = ["year", "gdp", "cpi"]
    rows = [(2020, 1, 2), (2021, 3, 4)]
    assert ev.key_values(cols, rows, (("gdp",), "first")) == [("gdp", 1)]
    assert ev.key_values(cols, rows, (("gdp", "cpi"), "all")) == [
        ("gdp", 1), ("cpi", 2), ("gdp", 3), ("cpi", 4)]  # fmt: skip


def test_values_match_numbers():
    assert ev.values_match(Decimal("-48.72"), Decimal("-48.7158942"))  # rounded ref
    assert ev.values_match(Decimal("0.67"), 0.6738544)  # rounding, rel diff > 0.1%
    assert ev.values_match(Decimal("100.0"), 100.05)  # within 0.1%
    assert not ev.values_match(Decimal("100.0"), 100.2)
    assert ev.values_match(21345678, Decimal("21345678.43"))
    assert not ev.values_match(Decimal("15.2"), Decimal("0.152"))  # fraction, not %
    assert not ev.values_match(Decimal("2"), "2")
    assert not ev.values_match(Decimal("1"), True)
    assert not ev.values_match(2, Decimal("2.4"))  # integer ref: no rounding rule


def test_values_match_dates_and_strings():
    d = dt.date(2018, 5, 17)
    assert ev.values_match(d, dt.date(2018, 5, 17))
    assert ev.values_match(d, dt.datetime(2018, 5, 17, 0, 0))
    assert ev.values_match(d, "2018-05-17")
    assert not ev.values_match(d, dt.date(2018, 1, 2))
    assert ev.values_match("WEO October 2026", "weo october 2026 ")
    assert not ev.values_match("VCB", "VCBX")


def test_grade():
    keys = [("pct_change", Decimal("-16.99")), ("start_date", dt.date(2018, 5, 17))]
    rows = [("VHM", dt.date(2018, 5, 17), Decimal("-16.990134"))]
    verdict, found = ev.grade("ok", keys, rows, True)
    assert verdict == "PASS" and found[1] == dt.date(2018, 5, 17)
    wrong = [("VHM", dt.date(2017, 12, 29), Decimal("-20.1"))]
    assert ev.grade("ok", keys, wrong, True)[0] == "CHECK"
    assert ev.grade("cannot_answer", keys, [], True) == ("cannot_answer", [])
    assert ev.grade("ok", [], rows, False) == ("CHECK", [])


def test_find_value_inside_arrays():
    rows = [(2, [dt.date(2022, 9, 22), dt.date(2022, 10, 24)])]
    assert ev.find_value(dt.date(2022, 10, 24), rows, 0.001) == dt.date(2022, 10, 24)


def test_summary_table():
    row = ev.EvalRow(id="q01", question="Câu hỏi dài " * 10, status="ok",
                     verdict="PASS", keys=[("close", Decimal("1269.7100"))],
                     found=[Decimal("1269.71")])  # fmt: skip
    out = ev.summary_table([row], q_chars=20)
    assert out.splitlines()[1].startswith("q01 | Câu hỏi dài Câu hỏi… | ok | PASS")
    assert "close=1269.71" in out


def test_final_verdict_phase4():
    assert ev.final_verdict("q16", "CHECK", ("q16",)) == "phase 4"
    assert ev.final_verdict("q16", "PASS", ("q16",)) == "phase 4"
    assert ev.final_verdict("q16", "error", ("q16",)) == "error"
    assert ev.final_verdict("q02", "CHECK", ("q16",)) == "CHECK"


def test_expected_route():
    assert ev.expected_route("sql") == "sql"
    assert ev.expected_route("sql+rag") == "both"
    assert ev.expected_route("none") == "out_of_scope"
    assert ev.expected_route("web") is None


def test_router_table():
    base = {"question": "q", "expected": "rag", "status": "ok", "notes": []}
    rows = [
        {**base, "id": "q1", "route": "rag", "start": dt.date(2026, 10, 1),
         "end": dt.date(2026, 10, 31), "correct": True},
        {**base, "id": "q2", "route": None, "status": "error", "start": None,
         "end": None, "correct": False, "notes": ["n"]},
    ]  # fmt: skip
    lines = ev.router_table(rows).splitlines()
    assert lines[1] == "q1 | q | rag | rag | 2026-10-01..2026-10-31 | yes"
    assert lines[2] == "q2 | q | rag | error | - (n) | NO"


def test_rag_table():
    base = {"question": "q", "notes": [], "gold": ["d"], "rag_query": None,
            "chunk_rank": None}  # fmt: skip
    rows = [
        {**base, "id": "q1", "filtered": True, "start": dt.date(2026, 10, 1),
         "end": dt.date(2026, 10, 31), "rank": 2, "rag_query": "rq",
         "chunk_rank": 3},
        {**base, "id": "q2", "filtered": False, "start": None, "end": None,
         "rank": None, "gold": [], "notes": ["n"]},
        {**base, "id": "q3", "filtered": True, "start": dt.date(2026, 1, 1),
         "end": dt.date(2026, 1, 31), "rank": None},
    ]  # fmt: skip
    lines = ev.rag_table(rows).splitlines()
    assert lines[1] == "q1 | q | rq | 2026-10-01..2026-10-31 | yes | 2 | 3"
    assert lines[2] == "q2 | q | - | none (n) | n/a (no answer doc) | - | -"
    assert lines[3] == "q3 | q | - | 2026-01-01..2026-01-31 | NO | - | -"


def test_compare_table_and_top_k_counts():
    rows = [
        {"id": "q1", "rag_query": "rq", "start": dt.date(2026, 10, 1),
         "end": dt.date(2026, 10, 31), "graded": True,
         "chunk_rank": {"local": 2, "openai": 7}},
        {"id": "q2", "rag_query": None, "start": None, "end": None, "graded": False,
         "chunk_rank": {"local": None, "openai": None}},
        {"id": "q3", "rag_query": "x", "start": None, "end": None, "graded": True,
         "chunk_rank": {"local": None, "openai": 1}},
    ]  # fmt: skip
    lines = ev.compare_table(rows, ["local", "openai"]).splitlines()
    assert lines[0] == "id | rag_query | period | local | openai"
    assert lines[1] == "q1 | rq | 2026-10-01..2026-10-31 | 2 | 7"
    assert lines[2] == "q2 | - | none | - | -"
    assert ev.top_k_counts(rows, ["local", "openai"], 5) == {
        "local": (1, 2),
        "openai": (1, 2),
    }
