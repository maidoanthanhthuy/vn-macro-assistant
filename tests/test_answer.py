import json
from decimal import Decimal

import pytest

from vnmacro.agent.answer import (
    Answerer,
    DraftAnswer,
    SQLData,
    answer_footer,
    build_sources,
    format_input,
    parse_draft,
    render,
    sql_tables,
)
from vnmacro.agent.retrieve import RetrievedChunk
from vnmacro.llm import LLMResponse

PRICES = {"m": {"input": 0.10, "cached_input": 0.01, "output": 0.50}}


def chunk(doc_id, n=1):
    return RetrievedChunk(
        f"text {doc_id}", f"label {doc_id}", f"Title {doc_id}", "2026-10",
        f"https://x/{doc_id}", 0.5, doc_id, f"{doc_id}_{n:03d}",
    )  # fmt: skip


SQL_OK = SQLData(
    "ok",
    "WITH t AS (SELECT * FROM daily_prices) SELECT * FROM t JOIN symbols USING (s)",
    ["symbol", "pct_change"],
    [("VCB", Decimal("-2.93"))],
    notes="adjusted prices",
)


def draft_json(**kw):
    data = {
        "short_answer": "VCB giảm 2,93%.",
        "explanations": [
            {"term": "giá điều chỉnh", "explanation": "Giá đã điều chỉnh."}
        ],
        "used_documents": [1],
        "suggestion": None,
        "declined": False,
    }
    return json.dumps({**data, **kw})


def test_format_input_contains_all_parts():
    text = format_input("Q?", "both", ["Period used: x."], SQL_OK, [chunk("d")])
    assert text.startswith("Question: Q?\n\nRoute: both")
    assert "- Period used: x." in text
    assert "symbol | pct_change\nVCB | -2.93" in text
    assert "Notes: adjusted prices" in text
    assert "[1] label d (period 2026-10)\ntext d" in text


def test_format_input_empty_and_cannot_answer():
    empty = SQLData("ok", "SELECT 1", ["x"], [])
    assert "Rows: none (empty result)" in format_input("Q", "sql", [], empty, [])
    cannot = SQLData("cannot_answer", None, [], [], reason="no data")
    text = format_input("Q", "sql", [], cannot, [])
    assert "status: cannot_answer" in text and "no data" in text
    assert "Document excerpts" not in text and "System notes" not in text


def test_parse_draft_filters_document_numbers():
    d = parse_draft(draft_json(used_documents=[3, 1, 1, 9, 0]), n_chunks=3)
    assert d.used_documents == [1, 3]
    assert d.explanations == [("giá điều chỉnh", "Giá đã điều chỉnh.")]
    d = parse_draft(draft_json(explanations=[{"term": "", "explanation": "x"}]), 1)
    assert d.explanations == []


@pytest.mark.parametrize(
    "content",
    ["nope", draft_json(short_answer=" "), json.dumps({"short_answer": "x"}),
     draft_json(explanations=[{"term": "a"}]), draft_json(extra=1),
     draft_json(declined="yes"), draft_json(suggestion=3)],
)  # fmt: skip
def test_parse_draft_rejects(content):
    with pytest.raises(ValueError):
        parse_draft(content, 1)


def test_parse_draft_reads_suggestion_and_declined():
    d = parse_draft(draft_json(suggestion="  Q?  ", declined=True), 1)
    assert (d.suggestion, d.declined) == ("Q?", True)
    assert parse_draft(draft_json(suggestion=" "), 1).suggestion is None


def test_answer_footer():
    draft = DraftAnswer("x", [], [], suggestion="VN-Index 2025?")
    assert answer_footer("explain", draft, "SCOPE", "NOTE", "Thử") == [
        "NOTE",
        "Thử: “VN-Index 2025?”",
    ]
    no_suggestion = DraftAnswer("x", [], [])
    assert answer_footer("explain", no_suggestion, "S", "N", "Thử", "D?") == [
        "N",
        "Thử: “D?”",
    ]
    assert answer_footer("out_of_scope", DraftAnswer("x", [], []), "SCOPE") == ["SCOPE"]
    declined = DraftAnswer("x", [], [], declined=True)
    assert answer_footer("sql", declined, "SCOPE") == ["SCOPE"]
    assert answer_footer("sql", DraftAnswer("x", [], []), "SCOPE") == []
    assert answer_footer("out_of_scope", declined, "") == []


def test_sql_tables_skips_ctes_and_duplicates():
    assert sql_tables(SQL_OK.sql) == ["daily_prices", "symbols"]
    assert sql_tables(None) == []


def test_build_sources():
    labels = {"daily_prices": "prices"}
    chunks = [chunk("a", 1), chunk("a", 2), chunk("b")]
    lines = build_sources(SQL_OK, chunks, [1, 2, 3], labels)
    assert lines == [
        "Bảng `daily_prices`: prices",  # symbols has no label: not a source
        "Title a (kỳ 2026-10): https://x/a",
        "Title b (kỳ 2026-10): https://x/b",
    ]
    empty = SQLData("ok", "SELECT * FROM daily_prices", ["x"], [])
    assert build_sources(empty, chunks, [], labels) == []


def test_render():
    text = render(DraftAnswer("Ngắn.", [("t", "e")], []), ["src"])
    assert text == (
        "**Trả lời ngắn**\nNgắn.\n\n**Giải thích thêm**\n- **t**: e\n\n**Nguồn**\n- src"
    )
    assert render(DraftAnswer("Ngắn.", [], []), []) == "**Trả lời ngắn**\nNgắn."
    text = render(DraftAnswer("A.", [], []), [], ["F1", "F2"], title="Giải thích")
    assert text == "**Giải thích**\nA.\n\nF1\n\nF2"


def make(reply):
    logs = []

    def llm(messages):
        if isinstance(reply, Exception):
            raise reply
        return reply

    answerer = Answerer(
        "FIXED", "v", "m", llm, logs.append, prices=PRICES, scope_text="SCOPE"
    )
    return answerer, logs


def test_answerer_ok_and_logged():
    a, logs = make(LLMResponse(draft_json(), 100, 0, 20))
    res = a.answer("Q", "both", [], SQL_OK, [chunk("d")])
    assert res.status == "ok" and "**Nguồn**" in res.text
    assert res.sources[-1] == "Title d (kỳ 2026-10): https://x/d"
    assert logs[0]["component"] == "answer" and logs[0]["status"] == "ok"
    assert logs[0]["sql_attempts"][0]["used_documents"] == [1]
    assert logs[0]["answer_text"] == res.text
    assert res.cost_usd == pytest.approx((100 * 0.10 + 20 * 0.50) / 1e6)


def test_answerer_error_gives_fallback_text():
    a, logs = make(RuntimeError("down"))
    res = a.answer("Q", "rag", [], None, [])
    assert res.status == "error" and res.text and "RuntimeError" in res.error
    assert logs[0]["status"] == "error" and logs[0]["error"]


def test_answerer_explain_adds_note_and_suggestion():
    reply = draft_json(used_documents=[], suggestion="Q2?")
    a, logs = make(LLMResponse(reply, 10, 0, 5))
    res = a.answer("Đầu cơ là gì?", "explain", [], None, [])
    assert res.text.startswith("**Giải thích**")
    assert "Q2?" in res.text and "SCOPE" not in res.text
    assert logs[0]["sql_attempts"][0]["suggestion"] == "Q2?"


def test_answerer_declined_appends_scope():
    a, _ = make(LLMResponse(draft_json(used_documents=[], declined=True), 10, 0, 5))
    res = a.answer("VNG?", "sql", [], None, [])
    assert res.text.endswith("\n\nSCOPE")
