import json

import pytest

from vnmacro.ingest import fetch_worldbank as wb
from vnmacro.ingest.common import HttpSettings


def page(n: int, pages: int, rows):
    return [{"page": n, "pages": pages, "per_page": 2, "total": 3}, rows]


class FakeResponse:
    def __init__(self, payload):
        self.status_code = 200
        self.content = json.dumps(payload).encode()

    def raise_for_status(self) -> None:
        pass

    def json(self):
        return json.loads(self.content)


class FakeSession:
    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.params = []

    def get(self, url, params=None, headers=None, timeout=None):
        self.params.append(params)
        return FakeResponse(self.payloads.pop(0))


def test_wb_params():
    assert wb.wb_params(2000, 2026, 100, 2) == {
        "format": "json",
        "date": "2000:2026",
        "per_page": "100",
        "page": "2",
    }


def test_parse_wb_page():
    assert wb.parse_wb_page(page(1, 3, [{"date": "2024"}])) == {
        "pages": 3,
        "rows": [{"date": "2024"}],
    }
    assert wb.parse_wb_page(page(1, 0, None)) == {"pages": 1, "rows": []}
    error = [{"message": [{"id": "120", "value": "Invalid value"}]}]
    assert wb.parse_wb_page(error) is None
    assert wb.parse_wb_page(None) is None


def test_summarize_wb_rows_skips_nulls():
    rows = [
        {"date": "2025", "value": None},
        {"date": "2024", "value": 6.1},
        {"date": "2000", "value": 6.8},
    ]
    assert wb.summarize_wb_rows(rows) == {
        "n_rows": 3,
        "n_values": 2,
        "first_period": "2000",
        "last_period": "2024",
    }


def test_select_codes():
    assert wb.select_codes(["A", "B"], None) == ["A", "B"]
    assert wb.select_codes(["A", "B"], ["B"]) == ["B"]
    with pytest.raises(ValueError):
        wb.select_codes(["A"], ["Z"])


def test_fetch_indicator_reads_all_pages(tmp_path):
    session = FakeSession(
        [
            page(
                1, 2, [{"date": "2025", "value": 1.0}, {"date": "2024", "value": 2.0}]
            ),
            page(2, 2, [{"date": "2023", "value": None}]),
        ]
    )
    entry, calls = wb.fetch_indicator(
        "X.Y",
        tmp_path,
        session,
        HttpSettings(pause=0.0),
        2023,
        2025,
        per_page=2,
        sleep=lambda s: None,
    )
    assert [p["page"] for p in session.params] == ["1", "2"]
    assert entry["files"] == ["X.Y_p1.json", "X.Y_p2.json"]
    assert (entry["status"], entry["pages"], entry["n_rows"], entry["n_values"]) == (
        "ok",
        2,
        3,
        2,
    )
    assert len(calls) == 2
