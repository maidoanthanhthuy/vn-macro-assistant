from datetime import date

import pytest
import requests

from vnmacro.ingest import fetch_kbs as fk

NO_PAUSE = fk.FetchSettings(pause=0.0, retries=2)


class FakeResponse:
    def __init__(self, status_code: int, body: bytes = b"{}"):
        self.status_code = status_code
        self.content = body

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        import json

        return json.loads(self.content)


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls += 1
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def test_kbs_params_uses_dd_mm_yyyy():
    assert fk.kbs_params(date(2017, 1, 2), date(2026, 11, 10)) == {
        "sdate": "02-01-2017",
        "edate": "10-11-2026",
    }


def test_build_and_select_jobs():
    jobs = fk.build_jobs(
        ["FPT", "VCB"],
        ["VNINDEX"],
        date(2017, 1, 1),
        date(2015, 1, 1),
        date(2026, 1, 1),
    )
    assert [(j.symbol, j.kind, j.start.year) for j in jobs] == [
        ("FPT", "stocks", 2017),
        ("VCB", "stocks", 2017),
        ("VNINDEX", "index", 2015),
    ]
    assert [j.symbol for j in fk.select_jobs(jobs, ["vnindex"])] == ["VNINDEX"]
    with pytest.raises(ValueError):
        fk.select_jobs(jobs, ["XYZ"])


def test_summarize_payload_unsorted_and_missing():
    payload = {"data_day": [{"t": "2024-01-03 07:00"}, {"t": "2024-01-02 07:00"}]}
    assert fk.summarize_payload(payload) == {
        "n_rows": 2,
        "first_date": "2024-01-02",
        "last_date": "2024-01-03",
    }
    assert fk.summarize_payload({"data_day": None})["n_rows"] == 0
    assert fk.summarize_payload(None)["first_date"] is None


def test_weekdays_and_truncation():
    mon, sun = date(2026, 11, 9), date(2026, 11, 15)
    assert fk.weekdays_between(mon, sun) == 5
    assert fk.weekdays_between(date(2026, 11, 14), date(2026, 11, 14)) == 0
    assert fk.weekdays_between(sun, mon) == 0
    assert fk.looks_truncated(4, mon, sun, min_ratio=0.9)
    assert not fk.looks_truncated(5, mon, sun, min_ratio=0.9)


def test_year_ranges_and_combine():
    ranges = fk.year_ranges(date(2024, 6, 1), date(2026, 3, 5))
    assert ranges[0] == (date(2024, 6, 1), date(2024, 12, 31))
    assert ranges[-1] == (date(2026, 1, 1), date(2026, 3, 5))
    assert len(ranges) == 3
    combined = fk.combine_summaries(
        [
            {"n_rows": 2, "first_date": "2024-06-03", "last_date": "2024-12-31"},
            {"n_rows": 0, "first_date": None, "last_date": None},
        ]
    )
    assert combined == {
        "n_rows": 2,
        "first_date": "2024-06-03",
        "last_date": "2024-12-31",
    }


def test_fetch_with_retry_recovers():
    session = FakeSession(
        [requests.ConnectionError("down"), FakeResponse(500), FakeResponse(200)]
    )
    res = fk.fetch_with_retry(session, "u", {}, NO_PAUSE, sleep=lambda s: None)
    assert res["error"] is None and res["attempts"] == 3 and session.calls == 3


def test_fetch_with_retry_gives_up():
    session = FakeSession([FakeResponse(500)] * 3)
    res = fk.fetch_with_retry(session, "u", {}, NO_PAUSE, sleep=lambda s: None)
    assert res["error"] and res["payload"] is None and session.calls == 3


def test_get_or_fetch_never_overwrites(tmp_path):
    path = tmp_path / "FPT.json"
    path.write_bytes(b'{"data_day": [{"t": "2024-01-02 07:00"}]}')
    session = FakeSession([])  # any call would fail
    status, summary, record = fk.get_or_fetch(
        session, "u", date(2024, 1, 1), date(2024, 1, 5), path, NO_PAUSE
    )
    assert (status, summary["n_rows"], record, session.calls) == (
        "existing",
        1,
        None,
        0,
    )
    with pytest.raises(FileExistsError):
        fk.save_new_file(path, b"{}")


def test_get_or_fetch_saves_raw_bytes(tmp_path):
    body = b'{"data_day": [{"t": "2024-01-02 07:00", "c": "1"}]}'
    path = tmp_path / "FPT.json"
    status, _, record = fk.get_or_fetch(
        FakeSession([FakeResponse(200, body)]),
        "u",
        date(2024, 1, 1),
        date(2024, 1, 5),
        path,
        NO_PAUSE,
        sleep=lambda s: None,
    )
    assert status == "ok" and record["file"] == "FPT.json"
    assert path.read_bytes() == body
