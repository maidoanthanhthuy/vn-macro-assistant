import pytest

from vnmacro.ingest import fetch_documents as fd

HEADER = "doc_id,source,doc_type,url,notes,verified\n"


def row(doc_id, verified="yes", source="NSO", notes=""):
    return {"doc_id": doc_id, "source": source, "url": f"https://x/{doc_id}",
            "notes": notes, "verified": verified}  # fmt: skip


def test_read_documents_parses_quoted_fields(tmp_path):
    path = tmp_path / "documents.csv"
    path.write_text(
        HEADER + 'a,NSO,report,"https://x/a/","full text: https://x/a.docx",yes\n',
        encoding="utf-8",
    )
    docs = fd.read_documents(path)
    assert docs[0]["url"] == "https://x/a/"
    assert docs[0]["notes"] == "full text: https://x/a.docx"


def test_parse_documents_rejects_missing_column():
    with pytest.raises(ValueError, match="verified"):
        fd.parse_documents([{"doc_id": "a", "source": "NSO", "url": "", "notes": ""}])


def test_parse_documents_rejects_duplicate_ids():
    with pytest.raises(ValueError, match="Duplicate"):
        fd.parse_documents([row("a"), row("a")])


def test_select_documents_keeps_only_verified_yes():
    rows = [row("a"), row("b", " no "), row("c", "YES"), row("d", "")]
    docs = fd.parse_documents(rows)
    selected, skipped = fd.select_documents(docs)
    assert [d["doc_id"] for d in selected] == ["a", "c"]
    assert [d["doc_id"] for d in skipped] == ["b", "d"]


def test_select_documents_only_and_unknown_id():
    docs = [row("a"), row("b", "no"), row("c")]
    selected, skipped = fd.select_documents(docs, only=["b", "c"])
    assert ([d["doc_id"] for d in selected], [d["doc_id"] for d in skipped]) == (
        ["c"],
        ["b"],
    )
    with pytest.raises(ValueError, match="zzz"):
        fd.select_documents(docs, only=["zzz"])


def test_planned_files_adds_docx_for_nso_only():
    nso = row("a", notes="checked; full text: https://x/T6.2026.docx; section 5a")
    assert fd.planned_files(nso) == [
        ("page.html", "https://x/a"),
        ("full_text.docx", "https://x/T6.2026.docx"),
    ]
    assert fd.planned_files(row("b", source="SBV")) == [("page.html", "https://x/b")]
    assert fd.planned_files(row("c"))[1] == ("full_text.docx", None)


def test_is_blocked_by_code_or_marker():
    codes, markers = (403,), ("Request Rejected",)
    assert fd.is_blocked(403, b"", codes, markers)
    assert fd.is_blocked(200, b"<title>Request Rejected</title>", codes, markers)
    assert not fd.is_blocked(200, b"<html>ok</html>", codes, markers)
