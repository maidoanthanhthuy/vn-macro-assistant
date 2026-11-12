"""Fetch the original RAG documents listed in data/manual/documents.csv.

Run from the repository root:

    PYTHONPATH=src python -m vnmacro.ingest.fetch_documents
    PYTHONPATH=src python -m vnmacro.ingest.fetch_documents --only nso_report_2026_06

Only rows with verified = yes are fetched. For every document the web page is saved as
page.html; NSO documents also get the full-text .docx linked in `notes`
(full_text.docx).
Files are saved byte for byte to <out-root>/<snapshot date>/<doc_id>/ and are never
overwritten, so a re-run only fetches what is missing. manifest.json records url,
content type, size, SHA-256, fetch time and status of every file.

If a site refuses automated access, the run stops at that document and the error is
written to the manifest. There is no attempt to get around the block.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import re
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import requests

from vnmacro import config
from vnmacro.ingest.common import load_manifest, save_new_file, utc_now, write_manifest

REQUIRED_COLUMNS = ("doc_id", "source", "url", "notes", "verified")
PAGE_FILE = "page.html"
DOCX_FILE = "full_text.docx"
DOCX_URL_RE = re.compile(r"https?://\S+?\.docx\b")
ZIP_MAGIC = b"PK"  # a .docx file is a zip archive


@dataclass(frozen=True)
class FetchSettings:
    """HTTP settings for document downloads."""

    headers: dict[str, str]
    retries: int = config.HTTP_RETRIES
    pause: float = config.DOC_PAUSE_SECONDS
    timeout: float = config.HTTP_TIMEOUT_SECONDS
    block_codes: tuple[int, ...] = config.BLOCK_HTTP_CODES
    block_markers: tuple[str, ...] = config.BLOCK_MARKERS


# ---------- pure helpers ----------


def parse_documents(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    """Check columns and doc_id values; return the rows with whitespace stripped."""
    if rows:
        missing = [c for c in REQUIRED_COLUMNS if c not in rows[0]]
        if missing:
            raise ValueError(f"documents.csv is missing columns: {missing}")
    clean = [{k: (v or "").strip() for k, v in r.items()} for r in rows]
    ids = [r["doc_id"] for r in clean]
    if any(not i for i in ids):
        raise ValueError("documents.csv has a row without doc_id")
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    if dupes:
        raise ValueError(f"Duplicate doc_id in documents.csv: {dupes}")
    return clean


def select_documents(
    docs: list[dict[str, str]], only: Iterable[str] | None = None
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """Split rows into (to fetch, skipped): only verified = yes rows are fetched.

    `only` limits the run to these doc_ids; unknown ids raise ValueError.
    """
    if only is not None:
        only = set(only)
        unknown = only - {d["doc_id"] for d in docs}
        if unknown:
            raise ValueError(f"Unknown doc_id: {sorted(unknown)}")
        docs = [d for d in docs if d["doc_id"] in only]
    selected = [d for d in docs if d["verified"].lower() == "yes"]
    skipped = [d for d in docs if d["verified"].lower() != "yes"]
    return selected, skipped


def docx_url_from_notes(notes: str) -> str | None:
    """Return the first .docx link in a notes string, or None."""
    m = DOCX_URL_RE.search(notes)
    return m.group(0) if m else None


def planned_files(
    doc: dict[str, str], docx_sources: Iterable[str] = config.DOCX_SOURCES
) -> list[tuple[str, str | None]]:
    """List (file name, url) to fetch for one document; url None = link missing."""
    files: list[tuple[str, str | None]] = [(PAGE_FILE, doc["url"] or None)]
    if doc["source"] in set(docx_sources):
        files.append((DOCX_FILE, docx_url_from_notes(doc["notes"])))
    return files


def is_blocked(
    http_status: int | None,
    content: bytes | None,
    block_codes: Iterable[int],
    block_markers: Iterable[str],
) -> bool:
    """True if the response looks like a refusal of automated access."""
    if http_status in set(block_codes):
        return True
    head = (content or b"")[:5000].decode("utf-8", errors="ignore").lower()
    return any(m.lower() in head for m in block_markers)


def is_valid_content(file_name: str, content: bytes) -> bool:
    """A .docx must be a zip archive; a page must not be empty."""
    if file_name.endswith(".docx"):
        return content.startswith(ZIP_MAGIC)
    return len(content) > 0


def describe_content(content: bytes) -> dict[str, Any]:
    """Return size in bytes and SHA-256 of a file's content."""
    return {"size": len(content), "sha256": hashlib.sha256(content).hexdigest()}


# ---------- I/O ----------


def read_documents(path: Path) -> list[dict[str, str]]:
    """Read and check documents.csv."""
    with path.open(encoding="utf-8", newline="") as f:
        return parse_documents(list(csv.DictReader(f)))


def download(
    session: requests.Session,
    url: str,
    settings: FetchSettings,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """GET a URL with retries; a block is reported at once and never retried."""
    res: dict[str, Any] = {"http_status": None, "content_type": None, "error": None}
    for attempt in range(1, settings.retries + 2):
        res["attempts"] = attempt
        try:
            resp = session.get(url, headers=settings.headers, timeout=settings.timeout)
            res["http_status"] = resp.status_code
            res["content_type"] = resp.headers.get("Content-Type")
            if is_blocked(
                resp.status_code,
                resp.content,
                settings.block_codes,
                settings.block_markers,
            ):
                error = f"blocked (HTTP {resp.status_code})"
                return {**res, "status": "blocked", "content": None, "error": error}
            resp.raise_for_status()
            return {**res, "status": "ok", "content": resp.content}
        except requests.RequestException as exc:
            res["error"] = f"{type(exc).__name__}: {exc}"
        finally:
            sleep(settings.pause)
    return {**res, "status": "error", "content": None}


def fetch_file(
    session: requests.Session,
    file_name: str,
    url: str | None,
    doc_dir: Path,
    old_record: dict[str, Any] | None,
    settings: FetchSettings,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Fetch and save one file, or keep the file already saved; return its record."""
    path = doc_dir / file_name
    if path.exists():
        if old_record and old_record.get("status") == "ok":
            return old_record
        return {
            "file": file_name,
            "url": url,
            "status": "ok",
            "note": "file already on disk",
            **describe_content(path.read_bytes()),
        }
    record: dict[str, Any] = {"file": file_name, "url": url}
    if url is None:
        return {**record, "status": "error", "error": "no URL in documents.csv"}
    res = download(session, url, settings, sleep)
    record.update(
        content_type=res["content_type"],
        http_status=res["http_status"],
        attempts=res["attempts"],
        fetched_at=utc_now(),
        status=res["status"],
        error=res["error"],
    )
    if res["status"] == "ok":
        if not is_valid_content(file_name, res["content"]):
            record.update(status="invalid", error="unexpected content; not saved")
        else:
            save_new_file(path, res["content"])
            record.update(describe_content(res["content"]))
    return record


def fetch_document(
    session: requests.Session,
    doc: dict[str, str],
    snapshot_dir: Path,
    old_entry: dict[str, Any] | None,
    settings: FetchSettings,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Fetch all files of one document; stop at the first blocked file."""
    old_files = {f["file"]: f for f in (old_entry or {}).get("files", [])}
    files = []
    for file_name, url in planned_files(doc):
        rec = fetch_file(
            session,
            file_name,
            url,
            snapshot_dir / doc["doc_id"],
            old_files.get(file_name),
            settings,
            sleep,
        )
        files.append(rec)
        if rec["status"] == "blocked":
            break
    statuses = {f["status"] for f in files}
    if "blocked" in statuses:
        status = "blocked"
    else:
        status = "ok" if statuses == {"ok"} else "error"
    return {"source": doc["source"], "status": status, "files": files}


def main(argv: list[str] | None = None) -> None:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(description="Fetch original RAG documents.")
    parser.add_argument("--only", nargs="+", help="only these doc_ids")
    parser.add_argument(
        "--snapshot-date", type=date.fromisoformat, default=date.today()
    )
    parser.add_argument("--documents", type=Path, default=config.DOCUMENTS_FILE)
    parser.add_argument("--out-root", type=Path, default=config.RAW_DOCUMENTS_DIR)
    args = parser.parse_args(argv)
    try:
        selected, skipped = select_documents(read_documents(args.documents), args.only)
    except ValueError as exc:
        parser.error(str(exc))
    for d in skipped:
        print(f"skip {d['doc_id']}: verified = {d['verified'] or '(empty)'}")

    snapshot_dir = args.out_root / args.snapshot_date.isoformat()
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = snapshot_dir / "manifest.json"
    manifest = load_manifest(
        manifest_path,
        {
            "snapshot_date": args.snapshot_date.isoformat(),
            "documents_file": str(args.documents),
            "user_agent": config.DOC_HEADERS["User-Agent"],
            "documents": {},
        },
    )
    settings = FetchSettings(headers=config.DOC_HEADERS)
    session = requests.Session()
    for doc in selected:
        doc_id = doc["doc_id"]
        entry = fetch_document(
            session, doc, snapshot_dir, manifest["documents"].get(doc_id), settings
        )
        manifest["documents"][doc_id] = entry
        write_manifest(manifest_path, manifest)
        print(f"{doc_id:24} {entry['status']}")
        if entry["status"] == "blocked":
            print(f"\nStopped: {doc_id} is blocked by the site. See {manifest_path}")
            break

    bad = [i for i, e in manifest["documents"].items() if e["status"] != "ok"]
    print(f"\nSnapshot: {snapshot_dir}")
    if bad:
        print(f"Not OK: {' '.join(bad)} -> re-run with --only {' '.join(bad)}")


if __name__ == "__main__":
    main()
