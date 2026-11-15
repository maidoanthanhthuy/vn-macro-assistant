import datetime as dt
from decimal import Decimal

from vnmacro.sql_agent import context as ctx


def _table(name: str, full: bool = False) -> ctx.Table:
    return ctx.Table(
        name=name,
        comment=f"{name} comment",
        columns=(
            ctx.Column("day", "date", False, "Trading date."),
            ctx.Column("note", "text", True, None),
        ),
        constraints=("PRIMARY KEY (day)",),
        row_count=2,
        rows=((dt.date(2026, 1, 2), "x" * 50), (dt.date(2026, 1, 1), None)),
        row_columns=("day", "note"),
        rows_order="ordered by day DESC",
        full=full,
    )


def test_format_value():
    assert ctx.format_value(None) == "NULL"
    assert ctx.format_value(True) == "true"
    assert ctx.format_value(dt.date(2026, 9, 1)) == "2026-09-01"
    assert ctx.format_value(Decimal("1E+1")) == "10"
    assert ctx.format_value("a\n  b") == "a b"
    assert ctx.format_value("abcdefghij", max_chars=8) == "abcde..."


def test_format_value_rounds_long_decimals_only():
    assert ctx.format_value(Decimal("5.079654799648559"), decimals=2) == "5.08"
    assert ctx.format_value(Decimal("5.075"), decimals=2) == "5.08"  # half up
    assert ctx.format_value(5.0796, decimals=2) == "5.08"
    assert ctx.format_value(Decimal("107.5"), decimals=2) == "107.5"  # no padding
    assert ctx.format_value(Decimal("32400.00"), decimals=2) == "32400.00"
    assert ctx.format_value(2458, decimals=2) == "2458"
    assert ctx.format_value(Decimal("5.0796")) == "5.0796"  # off by default


def test_format_rows():
    out = ctx.format_rows(["a", "b"], [(1, None), (2, "y")])
    assert out.splitlines() == ["a | b", "1 | NULL", "2 | y"]


def test_clean_constraint():
    assert (
        ctx.clean_constraint(
            "CHECK ((source = ANY (ARRAY['World Bank'::text, 'IMF WEO'::text])))"
        )
        == "CHECK (source IN ('World Bank', 'IMF WEO'))"
    )
    assert ctx.clean_constraint("CHECK ((close > (0)::numeric))") == "CHECK (close > 0)"
    # outer parens wrap separate groups -> must stay
    s = "CHECK ((a > 1) OR (b > 2))"
    assert ctx.clean_constraint(s) == s
    assert ctx.clean_constraint("PRIMARY KEY (symbol, date)") == (
        "PRIMARY KEY (symbol, date)"
    )


def test_sample_order():
    order = ctx.sample_order(["symbol", "date"], "date")
    assert order == [("date", True), ("symbol", False)]
    assert ctx.order_text(order) == "date DESC, symbol"
    assert ctx.sample_order(["code"], None) == [("code", False)]


def test_sample_columns_and_note():
    cols = ["a", "source_url", "b", "notes"]
    assert ctx.sample_columns(cols, ("source_url", "notes")) == ["a", "b"]
    assert ctx.sample_columns(cols) == cols
    order = [("date", True), ("symbol", False)]
    assert ctx.sample_note(order) == "ordered by date DESC, symbol"
    assert ctx.sample_note(order, "date", ("symbol", ("FPT", "VNINDEX"))) == (
        "date = latest, symbol IN (FPT, VNINDEX); ordered by date DESC, symbol"
    )


def test_format_table_sample_vs_full():
    sample = ctx.format_table(_table("t"), max_chars=10)
    assert "## t (2 rows)" in sample
    assert "- note (text, nullable)" in sample
    assert "- day (date): Trading date." in sample
    assert "Sample rows (ordered by day DESC):" in sample
    assert "xxxxxxx..." in sample
    full = ctx.format_table(_table("t", full=True), max_chars=10)
    assert "All rows" in full and "x" * 50 in full  # full tables are not cut


def test_format_table_uses_row_columns_and_decimals():
    t = ctx.Table(
        "p", None, (ctx.Column("a", "numeric", False, None),
                    ctx.Column("notes", "text", True, "Long notes.")),
        (), 1, ((Decimal("1.23456"),),), ("a",), "ordered by a", False,
    )  # fmt: skip
    out = ctx.format_table(t, decimals=2)
    assert "- notes (text, nullable): Long notes." in out  # still described
    assert out.endswith("Sample rows (ordered by a):\na\n1.23")


def test_coverage_groups_only_differing_last():
    last = dt.date(2026, 11, 10)
    groups = (
        ("FPT", dt.date(2017, 1, 3), last, 2458),
        ("OLD", dt.date(2017, 1, 3), dt.date(2020, 5, 4), 800),
    )
    cov = ctx.Coverage("daily_prices", "date", dt.date(2015, 1, 5), last, "symbol",
                       groups, only_differing_last=True)  # fmt: skip
    assert ctx.coverage_groups(cov) == groups[1:]
    out = ctx.format_coverage([cov])
    assert "symbol values with a different last date:" in out
    assert "- OLD: 2017-01-03 .. 2020-05-04 (800 rows)" in out
    assert "FPT" not in out
    # all groups end on the last date -> only the overall line
    same = ctx.Coverage("daily_prices", "date", dt.date(2015, 1, 5), last, "symbol",
                        groups[:1], only_differing_last=True)  # fmt: skip
    assert ctx.format_coverage([same]).splitlines() == [
        "## Data coverage (min .. max)",
        "- daily_prices.date: 2015-01-05 .. 2026-11-10",
    ]


def test_format_coverage():
    cov = ctx.Coverage(
        "daily_prices", "date", dt.date(2015, 1, 5), dt.date(2026, 11, 10), "symbol",
        (("FPT", dt.date(2017, 1, 3), dt.date(2026, 11, 10), 2458),),
    )  # fmt: skip
    out = ctx.format_coverage([cov])
    assert "- daily_prices.date: 2015-01-05 .. 2026-11-10" in out
    assert "  - FPT: 2017-01-03 .. 2026-11-10 (2458 rows)" in out


def test_build_schema_context_is_deterministic_and_sorted():
    tables = [_table("zeta"), _table("alpha")]
    cov = [ctx.Coverage("zeta", "day", 1, 2), ctx.Coverage("alpha", "day", 3, 4)]
    a = ctx.build_schema_context("public", tables, cov)
    b = ctx.build_schema_context("public", list(reversed(tables)), cov[::-1])
    assert a == b
    assert a.index("## alpha") < a.index("## zeta") < a.index("## Data coverage")
    assert a.index("- alpha.day") < a.index("- zeta.day")


def test_size_report():
    assert ctx.size_report("x" * 400, chars_per_token=4) == (
        "400 characters, ~100 tokens (chars / 4)"
    )


def test_clean_constraint_keeps_spaces_after_casts():
    s = "CHECK ((((d = 'cut'::text) AND (n < o)) OR (x = 'a'::character varying)))"
    assert ctx.clean_constraint(s) == "CHECK (((d = 'cut') AND (n < o)) OR (x = 'a'))"
