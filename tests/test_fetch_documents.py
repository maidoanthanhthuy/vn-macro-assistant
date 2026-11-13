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


class FakeResponse:
    def __init__(self, content, status=200):
        self.content = content
        self.status_code = status
        self.headers = {"Content-Type": "application/octet-stream"}

    def raise_for_status(self):
        pass


class FakeSession:
    def __init__(self, content=b"PK new"):
        self.content = content
        self.calls = 0

    def get(self, url, headers=None, timeout=None):
        self.calls += 1
        return FakeResponse(self.content)


SETTINGS = fd.FetchSettings(headers={}, retries=0, pause=0)


def no_sleep(_):
    pass


def test_fetch_file_keeps_existing_file(tmp_path):
    (tmp_path / "full_text.docx").write_bytes(b"PK old")
    session = FakeSession()
    old = {"file": "full_text.docx", "status": "ok", "sha256": "x"}
    rec = fd.fetch_file(
        session, "full_text.docx", "https://x/a", tmp_path, old, SETTINGS, no_sleep
    )
    assert rec == old
    rec = fd.fetch_file(
        session, "full_text.docx", "https://x/a", tmp_path, None, SETTINGS, no_sleep
    )
    assert rec["status"] == "ok"
    assert rec["note"] == "file already on disk"
    assert session.calls == 0
    assert (tmp_path / "full_text.docx").read_bytes() == b"PK old"


def test_fetch_file_saves_new_file_and_rejects_bad_content(tmp_path):
    rec = fd.fetch_file(
        FakeSession(b"PK new"), "a.docx", "https://x/a", tmp_path, None, SETTINGS,
        no_sleep,
    )  # fmt: skip
    assert rec["status"] == "ok"
    assert (tmp_path / "a.docx").read_bytes() == b"PK new"
    rec = fd.fetch_file(
        FakeSession(b"<html>"), "b.docx", "https://x/b", tmp_path, None, SETTINGS,
        no_sleep,
    )  # fmt: skip
    assert rec["status"] == "invalid"
    assert not (tmp_path / "b.docx").exists()


def test_fetch_file_without_url_is_error(tmp_path):
    rec = fd.fetch_file(
        FakeSession(), "a.docx", None, tmp_path, None, SETTINGS, no_sleep
    )
    assert rec["status"] == "error"


def test_is_valid_content():
    assert fd.is_valid_content("a.docx", b"PK\x03\x04")
    assert not fd.is_valid_content("a.docx", b"<html>")
    assert fd.is_valid_content("page.html", b"<html>")
    assert not fd.is_valid_content("page.html", b"")
