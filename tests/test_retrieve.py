import datetime as dt

from vnmacro.agent.retrieve import RetrievedChunk, Retriever, first_rank, period_args

D = dt.date


def row(doc_id, score=0.5):
    return ("text", "label", "title", "2026-10", "url", score, doc_id, doc_id + "_1")


def make(results):
    """Retriever whose search returns results[(start, end)] and records its calls."""
    calls = []

    def search(vec, start, end, k):
        calls.append((vec, start, end, k))
        return results.get((start, end), [])

    return Retriever(embed=lambda q: f"vec:{q}", search=search, k=5), calls


def test_period_args():
    assert period_args(None, None) is None
    assert period_args(D(2026, 1, 1), None) == (D(2026, 1, 1), D(2026, 1, 1))
    assert period_args(None, D(2026, 1, 31)) == (D(2026, 1, 31), D(2026, 1, 31))
    assert period_args(D(2026, 2, 1), D(2026, 1, 1)) is None


def test_filtered_search_used_when_documents_overlap():
    period = (D(2026, 10, 1), D(2026, 10, 31))
    r, calls = make({period: [row("nso_report_2026_10")]})
    res = r.retrieve("q", *period)
    assert res.filtered and res.notes == ()
    assert calls == [("vec:q", *period, 5)]
    c = res.chunks[0]
    assert isinstance(c, RetrievedChunk) and c.doc_id == "nso_report_2026_10"
    assert (c.context_label, c.title, c.url, c.score) == ("label", "title", "url", 0.5)


def test_fallback_to_all_documents_with_note():
    r, calls = make({(None, None): [row("sbv_press_2026_q2")]})
    res = r.retrieve("q", D(2023, 1, 1), D(2023, 12, 31), k=3)
    assert not res.filtered and len(res.notes) == 1
    assert "2023-01-01..2023-12-31" in res.notes[0]
    assert [c[1:] for c in calls] == [
        (D(2023, 1, 1), D(2023, 12, 31), 3),
        (None, None, 3),
    ]
    assert res.chunks[0].doc_id == "sbv_press_2026_q2"


def test_no_period_searches_all_once():
    r, calls = make({(None, None): [row("a")]})
    res = r.retrieve("q")
    assert not res.filtered and res.notes == () and len(calls) == 1


def test_first_rank():
    chunks = [RetrievedChunk(*row(d)) for d in ("a", "b", "c")]
    assert first_rank(chunks, ("c", "b")) == 2
    assert first_rank(chunks, ("z",)) is None
    assert first_rank(chunks, ()) is None
    assert first_rank(chunks, ("b_1",), "chunk_id") == 2
