from datetime import date, datetime, timedelta, timezone

from vnmacro.ingest import fetch_vietcap as fv

VN = timezone(timedelta(hours=7))


def ts(*args: int) -> int:
    return int(datetime(*args, tzinfo=VN).timestamp())


def test_vietcap_body():
    body = fv.vietcap_body("HNXIndex", date(2026, 11, 9), date(2026, 11, 13))
    assert body["symbols"] == ["HNXIndex"] and body["timeFrame"] == "ONE_DAY"
    assert body["countBack"] == 6  # 5 weekdays + 1
    assert body["to"] == ts(2026, 11, 14)  # midnight after the end date, VN time


def test_vietcap_closes_uses_local_date():
    # midnight VN time is still the previous day in UTC
    payload = [{"t": [ts(2026, 11, 9), str(ts(2026, 11, 10))], "c": ["1650.5", 1660]}]
    closes = fv.vietcap_closes(payload)
    assert closes == {"2026-11-09": 1650.5, "2026-11-10": 1660.0}
    assert fv.summarize_closes(closes)["first_date"] == "2026-11-09"


def test_vietcap_closes_bad_payload():
    assert fv.vietcap_closes(None) == {}
    assert fv.vietcap_closes([]) == {}
    assert fv.summarize_closes({})["n_rows"] == 0
