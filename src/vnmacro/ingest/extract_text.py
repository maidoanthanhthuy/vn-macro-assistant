"""Extract clean text from the raw RAG documents into one Markdown file per document.

Run from the repository root:

    PYTHONPATH=src python -m vnmacro.ingest.extract_text
    PYTHONPATH=src python -m vnmacro.ingest.extract_text --force --only <doc_id>

Reads the newest snapshot in data/raw/documents/ and data/manual/documents.csv.
NSO reports come from full_text.docx (tables are skipped and counted); web articles come
from page.html using the per-site rules in config.SITE_RULES. Output:
data/processed/documents/<snapshot date>/<doc_id>.md, starting with YAML front matter.
"""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
from collections.abc import Iterable
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from vnmacro import config
from vnmacro.ingest.fetch_documents import (
    DOCX_FILE,
    PAGE_FILE,
    read_documents,
    select_documents,
)
from vnmacro.ingest.load_db import latest_snapshot

INVISIBLE_RE = re.compile("[​‌‍‎‏⁠﻿­]")
SPACES_RE = re.compile(r"[ \t  -  　]+")
PHOTO_CAPTION_RE = re.compile(r"^\(?\s*(ảnh|nguồn ảnh)\s*:", re.IGNORECASE)
RULE_LINE_RE = re.compile(r"^[_\-–—=.*\s]+$")
FIGURE_CAPTION_RE = re.compile(r"^(Hình|Biểu|Bảng)\s+\d+[a-z]?\.", re.IGNORECASE)
HEADING_PATTERNS: tuple[tuple[re.Pattern[str], int, bool], ...] = (
    # (pattern, markdown level, bold required)
    (re.compile(r"^[IVX]+\.\s"), 1, True),
    (re.compile(r"^\d{1,2}\.\s"), 2, True),
    (re.compile(r"^[a-zđ]\)\s"), 3, False),
)
SENTENCE_END = (".", ";", ":", ",")


# ---------- pure helpers: text ----------


def normalize_text(text: str) -> str:
    """NFC, drop invisible marks, collapse spaces per line and repeated blank lines."""
    text = unicodedata.normalize("NFC", text).replace("\r\n", "\n").replace("\r", "\n")
    text = INVISIBLE_RE.sub("", text)
    lines = [SPACES_RE.sub(" ", line).strip() for line in text.split("\n")]
    out: list[str] = []
    for line in lines:
        if line or (out and out[-1]):
            out.append(line)
    while out and not out[-1]:
        out.pop()
    return "\n".join(out)


def is_junk_line(line: str) -> bool:
    """True for photo captions ("Ảnh: ...") and lines made only of rule characters."""
    s = line.strip()
    return bool(s) and (bool(PHOTO_CAPTION_RE.match(s)) or bool(RULE_LINE_RE.match(s)))


def drop_junk_lines(lines: Iterable[str]) -> list[str]:
    """Remove junk lines (see is_junk_line)."""
    return [line for line in lines if not is_junk_line(line)]


def count_headings(markdown: str) -> int:
    """Count Markdown heading lines."""
    return sum(1 for line in markdown.split("\n") if re.match(r"^#{1,6} ", line))


def front_matter(doc: dict[str, str], fields: Iterable[str]) -> str:
    """YAML front matter; values are JSON strings, which are valid YAML."""
    body = "\n".join(
        f"{f}: {json.dumps(doc.get(f, ''), ensure_ascii=False)}" for f in fields
    )
    return f"---\n{body}\n---\n"


# ---------- pure helpers: NSO .docx ----------


def nso_heading_level(
    text: str, bold: bool, max_chars: int = config.NSO_MAX_HEADING_CHARS
) -> int | None:
    """Markdown level for an NSO heading ("I." -> 1, "1." -> 2, "a)" -> 3), else None.

    Roman and digit headings must be fully bold. Letter headings may be plain if they
    do not end like a sentence (one report has a plain "b) Xuất, nhập khẩu hàng hóa").
    """
    s = text.strip()
    if not s or len(s) > max_chars:
        return None
    for pattern, level, bold_required in HEADING_PATTERNS:
        if pattern.match(s):
            if bold or (not bold_required and not s.endswith(SENTENCE_END)):
                return level
            return None
    return None


def nso_blocks_to_markdown(
    blocks: Iterable[tuple[str, bool]],
    max_chars: int = config.NSO_MAX_HEADING_CHARS,
) -> str:
    """Turn (paragraph text, fully bold) pairs into Markdown.

    Figure/table captions ("Hình 3.", "Biểu 1.") are dropped together with the short
    bold lines right after them (caption continuation, units such as "%").
    """
    out: list[str] = []
    in_caption = False
    for raw, bold in blocks:
        text = normalize_text(raw).replace("\n", " ")
        if not text or is_junk_line(text):
            continue
        level = nso_heading_level(text, bold, max_chars)
        if FIGURE_CAPTION_RE.match(text):
            in_caption = True
            continue
        if in_caption and bold and level is None and len(text) <= max_chars:
            continue
        in_caption = False
        out.append(f"{'#' * level} {text}" if level else text)
    return "\n\n".join(out)


# ---------- pure helpers: HTML ----------


def site_rule(url: str, rules: dict[str, dict]) -> dict:
    """Return the extraction rule for a URL's host; raise if there is none."""
    host = urlparse(url).netloc.lower().removeprefix("www.")
    if host not in rules:
        raise KeyError(f"No SITE_RULES entry for {host}")
    return rules[host]


def _is_bold_paragraph(p: Any) -> bool:
    """True if all text of a <p> sits inside <strong>/<b>."""
    text = p.get_text("", strip=True).replace(" ", "")
    bold = "".join(b.get_text("", strip=True) for b in p.find_all(["strong", "b"]))
    return bool(text) and bold.replace(" ", "") == text


def html_to_markdown(html: str | bytes, rule: dict) -> str:
    """Extract the article lead and body as Markdown; sub-headings become '##'."""
    soup = BeautifulSoup(html, "lxml")
    body = soup.select_one(rule["body"])
    if body is None:
        raise ValueError(f"Article body not found: {rule['body']}")
    sapo = soup.select_one(rule["sapo"]) if rule.get("sapo") else None
    parts: list[str] = []
    if sapo is not None and not body.find(lambda t: t is sapo):
        parts.append(sapo.get_text(" ", strip=True))
    for selector in rule.get("drop", []):
        for el in body.select(selector):
            el.decompose()
    for el in body.find_all(["p", "h2", "h3", "h4", "h5", "li"]):
        if el.find_parent(["p", "li"]) is not None:
            continue  # nested; its text is taken with the parent
        text = normalize_text(el.get_text(" ", strip=True)).replace("\n", " ")
        if not text or is_junk_line(text):
            continue
        heading = el.name in ("h2", "h3", "h4", "h5") or (
            el.name == "p" and _is_bold_paragraph(el)
        )
        parts.append(f"## {text}" if heading else text)
    return "\n\n".join(parts)


# ---------- pure helpers: checks ----------


def check_results(
    results: dict[str, dict[str, Any]],
    texts: dict[str, str],
    expected_n: int,
    required: dict[str, str],
    junk_phrases: Iterable[str],
    min_chars: dict[str, int],
) -> list[str]:
    """Return problems found after extraction (empty list = all checks passed)."""
    problems = []
    if len(results) != expected_n:
        problems.append(f"expected {expected_n} documents, got {len(results)}")
    for doc_id, pattern in required.items():
        if doc_id not in texts or not re.search(pattern, texts[doc_id]):
            problems.append(f"{doc_id}: required text not found ({pattern})")
    for doc_id, res in results.items():
        if res["kind"] == "html":
            found = [j for j in junk_phrases if j.lower() in texts[doc_id].lower()]
            if found:
                problems.append(f"{doc_id}: junk phrases left: {found}")
        limit = min_chars.get(res["doc_type"], min_chars["default"])
        if res["chars"] < limit:
            problems.append(f"{doc_id}: only {res['chars']} chars (< {limit}); check")
    return problems


# ---------- I/O ----------


def read_docx_blocks(path: Path) -> tuple[list[tuple[str, bool]], int]:
    """Read body paragraphs in order as (text, fully bold); skip and count tables."""
    from docx import Document
    from docx.text.paragraph import Paragraph

    doc = Document(str(path))
    blocks: list[tuple[str, bool]] = []
    n_tables = 0
    for el in doc.element.body.iterchildren():
        tag = el.tag.rsplit("}", 1)[-1]
        if tag == "tbl":
            n_tables += 1
        elif tag == "p":
            p = Paragraph(el, doc)
            style_bold = bool(p.style is not None and p.style.font.bold)
            runs = [r for r in p.runs if r.text.strip()]
            bold = bool(runs) and all(
                r.bold or (r.bold is None and style_bold) for r in runs
            )
            blocks.append((p.text, bold))
    return blocks, n_tables


def extract_document(doc: dict[str, str], raw_dir: Path) -> tuple[str, dict[str, Any]]:
    """Extract one document; return (Markdown body, stats)."""
    docx_path = raw_dir / DOCX_FILE
    if doc["source"] in config.DOCX_SOURCES:
        blocks, n_tables = read_docx_blocks(docx_path)
        body, kind = nso_blocks_to_markdown(blocks), "docx"
    else:
        rule = site_rule(doc["url"], config.SITE_RULES)
        body = html_to_markdown((raw_dir / PAGE_FILE).read_bytes(), rule)
        n_tables, kind = 0, "html"
    body = normalize_text(body)
    stats = {
        "kind": kind,
        "doc_type": doc["doc_type"],
        "chars": len(body),
        "headings": count_headings(body),
        "tables_dropped": n_tables,
    }
    return body, stats


def main(argv: list[str] | None = None) -> None:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(description="Extract clean text from documents.")
    parser.add_argument("--only", nargs="+", help="only these doc_ids")
    parser.add_argument("--snapshot", help="snapshot date folder (default: newest)")
    parser.add_argument("--documents", type=Path, default=config.DOCUMENTS_FILE)
    parser.add_argument("--raw-root", type=Path, default=config.RAW_DOCUMENTS_DIR)
    parser.add_argument("--out-root", type=Path, default=config.PROCESSED_DOCUMENTS_DIR)
    parser.add_argument("--force", action="store_true", help="overwrite existing .md")
    args = parser.parse_args(argv)

    snapshot = latest_snapshot(args.raw_root, args.snapshot)
    manifest = json.loads((snapshot / "manifest.json").read_text())
    docs, skipped = select_documents(read_documents(args.documents), args.only)
    for d in skipped:
        print(f"skip {d['doc_id']}: verified = {d['verified'] or '(empty)'}")
    out_dir = args.out_root / snapshot.name
    out_dir.mkdir(parents=True, exist_ok=True)

    results: dict[str, dict[str, Any]] = {}
    texts: dict[str, str] = {}
    for doc in docs:
        doc_id = doc["doc_id"]
        entry = manifest["documents"].get(doc_id)
        if not entry or entry["status"] != "ok":
            print(f"{doc_id}: not fetched OK in {snapshot}; skipped")
            continue
        body, stats = extract_document(doc, snapshot / doc_id)
        path = out_dir / f"{doc_id}.md"
        if path.exists() and not args.force:
            stats["written"] = "kept existing (use --force)"
        else:
            content = front_matter(doc, config.FRONT_MATTER_FIELDS) + "\n" + body + "\n"
            path.write_text(content, encoding="utf-8")
            stats["written"] = "written"
        results[doc_id], texts[doc_id] = stats, body

    print(f"\n{'doc_id':24} {'chars':>7} {'headings':>8} {'tables':>6}  file")
    for doc_id, s in results.items():
        print(
            f"{doc_id:24} {s['chars']:>7} {s['headings']:>8} "
            f"{s['tables_dropped']:>6}  {s['written']}"
        )
    expected = config.EXPECTED_DOCUMENTS if args.only is None else len(docs)
    required = {
        k: v
        for k, v in config.REQUIRED_TEXT.items()
        if args.only is None or k in args.only
    }
    problems = check_results(
        results, texts, expected, required, config.JUNK_PHRASES, config.MIN_CHARS
    )
    print(f"\nOutput: {out_dir}")
    print("Checks: all passed" if not problems else "Checks FAILED:")
    for p in problems:
        print(f"  - {p}")


if __name__ == "__main__":
    main()
