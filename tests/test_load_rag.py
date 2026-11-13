from datetime import date

import pytest

from vnmacro.rag import load_rag as lr


@pytest.mark.parametrize(
    "period, start, end",
    [
        ("2026-06", date(2026, 6, 1), date(2026, 6, 30)),
        ("2025-12", date(2025, 12, 1), date(2025, 12, 31)),
        ("2024-02", date(2024, 2, 1), date(2024, 2, 29)),  # leap year
        ("2026-02", date(2026, 2, 1), date(2026, 2, 28)),  # not a leap year
        ("2026-Q1", date(2026, 1, 1), date(2026, 3, 31)),
        ("2025-Q4", date(2025, 10, 1), date(2025, 12, 31)),
        ("2026", date(2026, 1, 1), date(2026, 12, 31)),
    ],
)
def test_period_bounds(period, start, end):
    assert lr.period_bounds(period) == (start, end)


@pytest.mark.parametrize("bad", ["2026-13", "2026-Q5", "26-01", "2026-6", ""])
def test_period_bounds_rejects_bad_format(bad):
    with pytest.raises(ValueError):
        lr.period_bounds(bad)


def doc_row(doc_id, verified="yes", period="2026-Q2"):
    return {
        "doc_id": doc_id, "source": "SBV", "doc_type": "sbv_quarterly_press",
        "title": "T", "context_label": "L", "reference_period": period,
        "published_date": "2026-07-02", "url": "https://x", "notes": "n",
        "verified": verified,
    }  # fmt: skip


def test_build_documents_keeps_verified_and_types_dates():
    rows = [doc_row("a"), doc_row("b", verified="no")]
    docs = lr.build_documents(rows, date(2026, 11, 12))
    assert [d["doc_id"] for d in docs] == ["a"]
    d = docs[0]
    assert set(d) == set(lr.DOC_COLUMNS)
    assert (d["period_start"], d["period_end"]) == (date(2026, 4, 1), date(2026, 6, 30))
    assert d["published_date"] == date(2026, 7, 2)
    assert d["snapshot_date"] == date(2026, 11, 12)


def test_build_chunks_numbers_seq_per_document():
    raw = [
        {"chunk_id": f"{d}_{i}", "doc_id": d, "heading_path": ["H"], "context": "c",
         "text": "t", "char_count": 1, "title": "extra"}
        for d, i in [("a", 1), ("a", 2), ("b", 1), ("a", 3)]
    ]  # fmt: skip
    chunks = lr.build_chunks(raw, "heading_v1")
    assert [c["seq"] for c in chunks] == [1, 2, 1, 3]
    assert all(set(c) == set(lr.CHUNK_COLUMNS) for c in chunks)
    assert {c["strategy"] for c in chunks} == {"heading_v1"}


def test_check_load_flags_count_and_orphans():
    docs = [{"doc_id": "a"}]
    assert lr.check_load(docs, [{"doc_id": "a"}], 1) == []
    problems = lr.check_load(docs, [{"doc_id": "z"}], 2)
    assert len(problems) == 2
    assert "z" in problems[1]
