from datetime import date

import pytest

from vnmacro.ingest import load_db as ld

D = date.fromisoformat


def price(symbol, day, close, volume=100, o=None, h=None, low=None):
    return {
        "symbol": symbol,
        "date": D(day),
        "open": o if o is not None else close,
        "high": h if h is not None else close,
        "low": low if low is not None else close,
        "close": close,
        "volume": volume,
    }


def test_parse_kbs_rows_handles_strings_and_numbers():
    raw = [
        {"t": "2026-11-10 07:00", "o": "1719.23", "h": "1743.07", "l": "1714.32",
         "c": "1743.07", "v": "876999156.0"},
        {"t": "2015-01-05 07:00", "o": 545.43, "h": 549.22, "l": 543.78,
         "c": 544, "v": 91834620},
    ]  # fmt: skip
    rows = ld.parse_kbs_rows("VNINDEX", raw)
    assert rows[0]["date"] == D("2026-11-10")
    assert rows[0]["close"] == 1743.07 and isinstance(rows[1]["close"], float)
    assert rows[0]["volume"] == 876999156 and isinstance(rows[0]["volume"], int)


def test_parse_kbs_rows_missing_volume_is_none():
    raw = [{"t": "2026-11-10 07:00", "o": 1, "h": 1, "l": 1, "c": 1, "v": ""}]
    assert ld.parse_kbs_rows("X", raw)[0]["volume"] is None


def test_clean_prices_filters_start_and_applies_fixes():
    rows = [
        price("VNINDEX", "2014-12-31", 1),
        price("VNINDEX", "2016-03-04", 3, volume=999),
        price("VNINDEX", "2018-01-24", 4),
        price("VNINDEX", "2016-03-03", 2),
    ]
    fixes = [
        {"symbol": "VNINDEX", "date": D("2018-01-24"), "action": "drop_row"},
        {"symbol": "VNINDEX", "date": D("2016-03-04"), "action": "null_volume"},
        {"symbol": "VNINDEX", "date": D("2016-03-03"), "action": "known_missing"},
    ]
    out = ld.clean_prices(rows, D("2015-01-01"), fixes)
    assert [r["date"] for r in out] == [D("2016-03-03"), D("2016-03-04")]
    assert out[1]["volume"] is None and out[1]["close"] == 3
    assert rows[1]["volume"] == 999  # input not modified


def test_parse_price_fixes_rejects_unknown_action():
    with pytest.raises(ValueError):
        ld.parse_price_fixes([{"symbol": "X", "date": "2020-01-01", "action": "fix"}])


def test_parse_worldbank_skips_empty_and_old_years():
    payload = [
        {"page": 1},
        [
            {"indicator": {"id": "FR.INR.LEND"}, "date": "2024", "value": None},
            {"indicator": {"id": "FR.INR.LEND"}, "date": "2023", "value": 9.32},
            {"indicator": {"id": "FR.INR.LEND"}, "date": "1999", "value": 10.0},
        ],
    ]
    out = ld.parse_worldbank(payload, 2000)
    assert out == [
        {"indicator_code": "FR.INR.LEND", "year": 2023, "value": 9.32,
         "is_forecast": False, "vintage": None}
    ]  # fmt: skip


@pytest.mark.parametrize(
    "pub, expected",
    [
        ("2026-10-13T02:00:00Z", "WEO October 2026"),
        ("2026-04-14T00:00:00Z", "WEO April 2026"),
    ],
)
def test_weo_vintage(pub, expected):
    assert ld.weo_vintage(pub) == expected


def test_weo_vintage_rejects_unexpected_month():
    with pytest.raises(ValueError):
        ld.weo_vintage("2026-07-01T00:00:00Z")


def test_parse_weo_forecast_flag_and_start_year():
    base = {"INDICATOR": "NGDP_RPCH", "LATEST_ACTUAL_ANNUAL_DATA": "2025",
            "PUBLICATION_DATE": "2026-10-13T02:00:00Z"}  # fmt: skip
    rows = [
        {**base, "TIME_PERIOD": "1999", "OBS_VALUE": "4.8"},
        {**base, "TIME_PERIOD": "2025", "OBS_VALUE": "8.02"},
        {**base, "TIME_PERIOD": "2026", "OBS_VALUE": "8.4"},
        {**base, "TIME_PERIOD": "2027", "OBS_VALUE": ""},
    ]
    out = ld.parse_weo(rows, 2000)
    assert [(r["year"], r["is_forecast"]) for r in out] == [(2025, False), (2026, True)]
    assert {r["vintage"] for r in out} == {"WEO October 2026"}


def test_parse_imf_monthly_skips_empty_rows():
    rows = [
        {"TIME_PERIOD": "1900-M01", "OBS_VALUE": ""},
        {"TIME_PERIOD": "2001-M12", "OBS_VALUE": "40.5"},
    ]
    assert ld.parse_imf_monthly(rows) == {D("2001-12-01"): 40.5}


def test_add_inflation_yoy():
    cpi = {D("2025-01-01"): 100.0, D("2025-02-01"): 101.0, D("2026-01-01"): 105.0}
    out = {r["month"]: r["inflation_yoy"] for r in ld.add_inflation_yoy(cpi)}
    assert out[D("2025-01-01")] is None and out[D("2025-02-01")] is None
    assert out[D("2026-01-01")] == pytest.approx(5.0)


def test_strip_manual_drops_columns_and_empty_strings():
    rows = [{"a": "1", "sector": "", "notes": "x", "verified": "yes"}]
    assert ld.strip_manual(rows) == [{"a": "1", "sector": None}]


def test_first_dates_and_build_symbols():
    prices = [price("FPT", "2017-01-04", 1), price("FPT", "2017-01-03", 1)]
    firsts = ld.first_dates(prices)
    assert firsts == {"FPT": D("2017-01-03")}
    out = ld.build_symbols([{"symbol": "FPT", "aliases": None}], firsts)
    assert out == [{"symbol": "FPT", "aliases": "", "first_date": D("2017-01-03")}]


def test_type_policy_events():
    row = {"announced_date": "2023-06-16", "effective_date": "2023-06-19",
           "old_rate": "5.0", "new_rate": "4.5"}  # fmt: skip
    out = ld.type_policy_events([row])[0]
    assert out["effective_date"] == D("2023-06-19") and out["new_rate"] == 4.5


def test_check_unverified():
    tables = {"symbols": [{"verified": "yes"}, {"verified": "no"}]}
    assert ld.check_unverified(tables) == [
        "symbols: rows not verified = yes (CSV lines [3])"
    ]


def test_check_symbols():
    prices = [price("A", "2020-01-01", 1), price("B", "2020-01-01", 1)]
    assert ld.check_symbols(prices, [{"symbol": "A"}, {"symbol": "B"}], 2) == []
    errors = ld.check_symbols(prices, [{"symbol": "A"}, {"symbol": "C"}], 2)
    assert len(errors) == 2


def test_check_duplicate_ohlcv_flags_copied_row():
    prices = [
        price("VNINDEX", "2018-01-22", 1087.42, o=1066.86),
        price("VNINDEX", "2018-01-24", 1087.42, o=1066.86),
        price("VNINDEX", "2018-01-25", 1087.42, o=1066.86, volume=5),
    ]
    assert ld.check_duplicate_ohlcv(prices) == [
        "VNINDEX 2018-01-24 repeats the OHLCV of 2018-01-22"
    ]


def test_check_duplicate_keys():
    prices = [price("A", "2020-01-01", 1), price("A", "2020-01-01", 2)]
    assert len(ld.check_duplicate_keys(prices)) == 1


def test_check_stock_units():
    prices = [price("FPT", "2020-01-01", 50.9), price("VNINDEX", "2020-01-01", 900)]
    assert len(ld.check_stock_units(prices, {"FPT"}, 1000)) == 1
    assert ld.check_stock_units(prices[1:], {"FPT"}, 1000) == []  # index ignored


def test_check_yoy():
    cpi = [{"month": D("2026-09-01"), "inflation_yoy": 5.0797}]
    assert ld.check_yoy(cpi, {D("2026-09-01"): 5.07965}, 0.01) == []
    assert len(ld.check_yoy(cpi, {D("2026-09-01"): 5.1}, 0.01)) == 1
    assert len(ld.check_yoy(cpi, {D("2026-08-01"): 4.0}, 0.01)) == 2


def test_warn_big_moves_uses_exchange_band():
    prices = [
        price("A", "2020-01-01", 100),
        price("A", "2020-01-02", 107.05),  # +7.05%: within HOSE 7% + 0.1 tolerance
        price("A", "2020-01-03", 115),  # +7.4%: beyond
        price("H", "2020-01-01", 100),
        price("H", "2020-01-02", 108),  # +8%: within HNX 10%
        price("H", "2020-01-03", 120),  # +11.1%: beyond
    ]
    bands = {"HOSE": 7.0, "HNX": 10.0}
    out = ld.warn_big_moves(prices, {"A": "HOSE", "H": "HNX"}, bands, 0.1)
    assert [w.split(":")[0] for w in out] == ["A 2020-01-03", "H 2020-01-03"]


def test_warn_date_mismatch_respects_ranges_and_known_missing():
    symbols = [
        {"symbol": "IDX", "exchange": "HOSE", "asset_type": "index"},
        {"symbol": "STK", "exchange": "HOSE", "asset_type": "stock"},
        {"symbol": "HNX", "exchange": "HNX", "asset_type": "index"},
    ]
    days = ["2020-01-01", "2020-01-02", "2020-01-03", "2020-01-06"]
    prices = [price("IDX", d, 1) for d in days]
    prices += [price("STK", d, 1) for d in ["2020-01-02", "2020-01-06"]]
    prices += [price("HNX", "2020-01-07", 1)]
    out = ld.warn_date_mismatch(prices, symbols, set())
    # 2020-01-01 is before STK's first date, so only 2020-01-03 is reported
    assert out == ["STK missing 1 date(s) present in IDX: 2020-01-03"]
    assert ld.warn_date_mismatch(prices, symbols, {("STK", D("2020-01-03"))}) == []


def test_warn_wb_latest():
    macro = [{"indicator_code": "FR.INR.LEND", "year": 2022}]
    inds = [
        {"indicator_code": "FR.INR.LEND", "source": "World Bank",
         "notes": "Lags 2-3 years: latest year 2023."},
        {"indicator_code": "NGDP_RPCH", "source": "IMF WEO",
         "notes": "latest year 2030"},
    ]  # fmt: skip
    assert ld.warn_wb_latest(macro, inds) == [
        "FR.INR.LEND: latest year 2022 is older than the noted 2023"
    ]
    assert ld.noted_latest_year("no year here") is None


def test_table_stats_and_report():
    tables = {name: [] for name in ld.TABLE_ORDER}
    tables["cpi_monthly"] = [{"month": D("2001-12-01")}, {"month": D("2026-09-01")}]
    stats = ld.table_stats(tables)
    assert ("cpi_monthly", 2, D("2001-12-01"), D("2026-09-01")) in stats
    report = ld.build_report({"KBS": "x"}, stats, [], ["w1"], "DRY RUN")
    assert "Blocking checks failed: 0" in report and "- w1" in report
