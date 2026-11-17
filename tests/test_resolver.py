import datetime as dt

from vnmacro.agent.resolver import (
    DataCoverage,
    as_date,
    data_coverage,
    resolve_period,
)
from vnmacro.agent.router import RouteDecision
from vnmacro.sql_agent.context import Coverage

D = dt.date
COV = DataCoverage(
    sql=(D(2000, 1, 1), D(2026, 11, 10)),
    rag=(D(2025, 10, 1), D(2026, 12, 31)),
    latest_report=(D(2026, 10, 1), D(2026, 10, 31)),
)


def dec(route="rag", time_ref="specific", start=None, end=None):
    return RouteDecision(route, time_ref, start, end, "r")


def test_as_date():
    assert as_date(2024) == D(2024, 1, 1)
    assert as_date(2024, end=True) == D(2024, 12, 31)
    assert as_date(D(2024, 5, 2), end=True) == D(2024, 5, 2)


def test_data_coverage():
    coverage = [
        Coverage("daily_prices", "date", D(2015, 1, 5), D(2026, 11, 10)),
        Coverage("macro_annual", "year", 2000, 2031),
    ]
    docs = [
        ("nso_monthly_report", "2026-09", D(2026, 9, 1), D(2026, 9, 30)),
        ("nso_monthly_report", "2026-10", D(2026, 10, 1), D(2026, 10, 31)),
        ("sbv_directive", "2026", D(2026, 1, 1), D(2026, 12, 31)),
    ]
    cov = data_coverage(coverage, docs, "nso_monthly_report")
    assert cov.sql == (D(2000, 1, 1), D(2031, 12, 31))
    assert cov.rag == (D(2026, 1, 1), D(2026, 12, 31))
    assert cov.latest_report == (D(2026, 10, 1), D(2026, 10, 31))
    assert data_coverage(coverage, docs[2:], "nso_monthly_report").latest_report is None


def test_latest_uses_newest_report_for_rag_and_both():
    for route in ("rag", "both"):
        res = resolve_period(dec(route, "latest"), COV)
        assert (res.start, res.end, res.notes) == (D(2026, 10, 1), D(2026, 10, 31), ())


def test_latest_sql_left_open_and_missing_report_noted():
    res = resolve_period(dec("sql", "latest"), COV)
    assert (res.start, res.end) == (None, None)
    no_report = DataCoverage(COV.sql, COV.rag, None)
    res = resolve_period(dec("rag", "latest"), no_report)
    assert res.start is None and res.notes


def test_none_and_out_of_scope_give_open_period():
    assert resolve_period(dec("sql", "none", D(2024, 1, 1)), COV).start is None
    res = resolve_period(dec("out_of_scope", "specific", D(2024, 1, 1)), COV)
    assert (res.start, res.end, res.notes) == (None, None, ())
    res = resolve_period(dec("explain", "specific", D(2024, 1, 1)), COV)
    assert (res.start, res.end, res.notes) == (None, None, ())


def test_specific_inside_coverage_has_no_notes():
    res = resolve_period(dec("rag", "specific", D(2026, 6, 1), D(2026, 6, 30)), COV)
    assert (res.start, res.end, res.notes) == (D(2026, 6, 1), D(2026, 6, 30), ())


def test_one_missing_date_copies_the_other():
    res = resolve_period(dec("sql", "specific", D(2024, 3, 15), None), COV)
    assert (res.start, res.end) == (D(2024, 3, 15), D(2024, 3, 15))
    res = resolve_period(dec("sql", "range"), COV)
    assert res.start is None and res.notes


def test_start_after_end_is_rejected():
    res = resolve_period(dec("sql", "range", D(2024, 12, 31), D(2024, 1, 1)), COV)
    assert (res.start, res.end) == (None, None)
    assert "after" in res.notes[0]


def test_outside_coverage_is_noted_per_source():
    res = resolve_period(dec("rag", "specific", D(2023, 1, 1), D(2023, 12, 31)), COV)
    assert res.start == D(2023, 1, 1)
    assert len(res.notes) == 1 and "outside the rag data" in res.notes[0]
    res = resolve_period(dec("both", "range", D(2025, 1, 1), D(2025, 12, 31)), COV)
    assert len(res.notes) == 1 and "partly outside the rag data" in res.notes[0]
    res = resolve_period(dec("sql", "range", D(2026, 1, 1), D(2026, 12, 31)), COV)
    assert "partly outside the sql data" in res.notes[0]
