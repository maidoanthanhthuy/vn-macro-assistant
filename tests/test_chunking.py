import pytest

from vnmacro.rag import chunking as ch

PARAMS = {"max_chars": 120, "min_chars": 30, "overlap_chars": 0, "context_sep": " › "}
META = {
    "doc_id": "d1",
    "source": "NSO",
    "doc_type": "nso_monthly_report",
    "title": "Báo cáo T6",
    "context_label": "Cục Thống kê – Báo cáo tháng 6/2026",
    "reference_period": "2026-06",
    "published_date": "2026-07-03",
    "url": "https://x/d1",
}


def test_parse_front_matter():
    meta, body = ch.parse_front_matter(
        '---\ndoc_id: "d1"\ntitle: "A: B"\n---\n\nBody\n'
    )
    assert meta == {"doc_id": "d1", "title": "A: B"}
    assert body == "Body"


def test_context_label_requires_document_label():
    assert ch.context_label("L", ["I. A", "1. B"], " › ") == "L › I. A › 1. B"
    assert ch.context_label("L", [], " › ") == "L"
    with pytest.raises(ValueError):
        ch.context_label("", ["I. A"], " › ")


def test_split_sections_tracks_heading_path():
    body = (
        "Intro.\n\n# I. A\n\n## 1. B\n\nText b.\n\n"
        "## 2. C\n\nText c.\n\n# II. D\n\nText d."
    )
    secs = ch.split_sections(body)
    assert [s.path for s in secs] == [
        (),
        ("I. A",),
        ("I. A", "1. B"),
        ("I. A", "2. C"),
        ("II. D",),
    ]
    assert secs[2].text == "## 1. B\n\nText b."


def test_merge_short_sections_uses_child_path_and_merges_tail():
    secs = [
        ch.Section(("I. A",), "# I. A"),
        ch.Section(("I. A", "1. B"), "## 1. B\n\n" + "x" * 40),
        ch.Section(("I. A", "2. C"), "## 2. C\n\nshort"),
    ]
    out = ch.merge_short_sections(secs, min_chars=30)
    assert len(out) == 1
    assert out[0].path == ("I. A", "1. B")
    assert out[0].text.startswith("# I. A\n\n## 1. B") and out[0].text.endswith("short")


def test_split_sentences_keeps_numbers_abbreviations_and_decimals():
    text = "CPI giảm 0,39%. Giá xăng giảm 10,05%. TP. Hồ Chí Minh tăng. 1. Mục một."
    assert ch.split_sentences(text) == [
        "CPI giảm 0,39%.",
        "Giá xăng giảm 10,05%.",
        "TP. Hồ Chí Minh tăng.",
        "1. Mục một.",
    ]


def test_split_long_text_never_cuts_inside_a_sentence():
    s1, s2, s3 = "A" * 50 + ".", "B" * 50 + ".", "C" * 50 + "."
    para = f"{s1} {s2} {s3}"
    parts = ch.split_long_text(f"Short para.\n\n{para}", max_chars=120)
    assert all(len(p) <= 120 for p in parts)
    assert ch.squash("".join(parts)) == ch.squash(f"Short para.{para}")
    for s in (s1, s2, s3):
        assert any(s in p for p in parts)


def test_split_long_text_keeps_overlong_sentence_whole():
    long_sentence = "X" * 200 + "."
    assert ch.split_long_text(long_sentence, max_chars=120) == [long_sentence]


def test_chunk_document_is_lossless_and_labels_context():
    body = (
        "# I. GIÁ\n\n## 5. Chỉ số giá\n\n"
        + "CPI tháng Sáu giảm 0,39%. " * 6
        + "\n\n"
        + "Nhóm giao thông giảm 4,85%. " * 3
    )
    chunks = ch.chunk_document(META, body, PARAMS)
    assert ch.squash("".join(c["text"] for c in chunks)) == ch.squash(body)
    assert all(c["char_count"] <= PARAMS["max_chars"] for c in chunks)
    assert chunks[0]["chunk_id"] == "d1_001"
    assert chunks[0]["context"] == (
        "Cục Thống kê – Báo cáo tháng 6/2026 › I. GIÁ › 5. Chỉ số giá"
    )
    assert chunks[0]["title"] == "Báo cáo T6"
    assert ch.embedding_text(chunks[0]).startswith(chunks[0]["context"] + "\n\n")


def test_chunk_document_rejects_overlap():
    with pytest.raises(ValueError):
        ch.chunk_document(META, "text", {**PARAMS, "overlap_chars": 50})


def test_check_chunks_flags_lost_text_and_wrong_context():
    chunks = [
        {"chunk_id": "d1_001", "doc_id": "d1", "context": "T › quý 2/2026",
         "text": "CPI giảm do giá xăng dầu", "char_count": 40},
    ]  # fmt: skip
    problems, _ = ch.check_chunks(
        chunks,
        {"d1": "CPI giảm do giá xăng dầu. Thêm chữ."},
        PARAMS,
        {"d1": "giá xăng dầu"},
        {"d1": "tháng 6/2026"},
    )
    assert any("do not add up" in p for p in problems)
    assert any("lacks" in p for p in problems)
