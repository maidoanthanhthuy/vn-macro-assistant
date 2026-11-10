import pytest

from vnmacro.ingest import fetch_imf as imf

CSV = (
    "TIME_PERIOD,OBS_VALUE,PUBLICATION_DATE,LATEST_ACTUAL_ANNUAL_DATA\n"
    "2026,8.4,2026-10-13,2025\n"
    "2024,7.1,2026-10-13,2025\n"
    "2025,,2026-10-13,2025\n"
)


def test_imf_url():
    assert (
        imf.imf_url("https://x/sdmx/3.0", "IMF.RES/WEO", "VNM.NGDP_RPCH.A")
        == "https://x/sdmx/3.0/data/dataflow/IMF.RES/WEO/+/VNM.NGDP_RPCH.A"
    )


def test_summarize_sdmx_rows_skips_empty_values():
    rows = imf.parse_sdmx_csv(CSV)
    assert imf.summarize_sdmx_rows(rows) == {
        "n_rows": 3,
        "n_values": 2,
        "first_period": "2024",
        "last_period": "2026",
    }


def test_series_attributes():
    rows = imf.parse_sdmx_csv(CSV)
    attrs = imf.series_attributes(rows, ["PUBLICATION_DATE", "MISSING"])
    assert attrs == {"PUBLICATION_DATE": "2026-10-13", "MISSING": None}
    rows[0]["PUBLICATION_DATE"] = "2026-04-14"
    assert imf.series_attributes(rows, ["PUBLICATION_DATE"]) == {
        "PUBLICATION_DATE": ["2026-04-14", "2026-10-13"]
    }


def test_is_valid_sdmx_csv():
    assert imf.is_valid_sdmx_csv(CSV)
    assert not imf.is_valid_sdmx_csv("TIME_PERIOD,OBS_VALUE\n")
    assert not imf.is_valid_sdmx_csv("<html>error</html>")
    assert not imf.is_valid_sdmx_csv(None)


def test_select_names():
    assert imf.select_names(["CPI", "WEO"], ["WEO"]) == ["WEO"]
    with pytest.raises(ValueError):
        imf.select_names(["CPI"], ["X"])
