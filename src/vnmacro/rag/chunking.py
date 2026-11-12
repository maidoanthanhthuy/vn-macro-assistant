"""Split processed Markdown documents into chunks for retrieval.

Run from the repository root:

    PYTHONPATH=src python -m vnmacro.rag.chunking
    PYTHONPATH=src python -m vnmacro.rag.chunking --strategy heading_v1 --force

Reads data/processed/documents/<newest snapshot>/*.md and writes
data/processed/chunks/<snapshot>/<strategy>/chunks.jsonl (one JSON object per chunk).

Strategy "heading_v1" (parameters in config.CHUNKING_STRATEGIES):
1. one chunk per heading section;
2. sections longer than max_chars are split at paragraph breaks, and a paragraph that
   is still too long is split at sentence ends (never inside a sentence);
3. sections shorter than min_chars are merged with the next section of the document;
4. no overlap.
Each chunk has a context label (the document's context_label from documents.csv ›
heading path) kept apart from the text; the text sent to the embedding model is
label + blank line + text.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from vnmacro import config

DOC_FIELDS = (
    "source",
    "doc_type",
    "title",
    "context_label",
    "reference_period",
    "published_date",
    "url",
)
HEADING_RE = re.compile(r"^(#{1,6}) (.+)$")
# A sentence ends at . ! ? … (optionally followed by a closing quote or bracket) when
# the next text starts with an upper-case letter, a digit, a quote or an open bracket.
SENTENCE_END_RE = re.compile(r"(?<=[.!?…])[\"”’)\]]?\s+(?=[\"“‘(\[0-9A-ZÀ-ỸĐ])")


@dataclass(frozen=True)
class Section:
    """A heading section: heading path (outer to inner) and its Markdown text."""

    path: tuple[str, ...]
    text: str


# ---------- pure helpers ----------


def parse_front_matter(markdown: str) -> tuple[dict[str, str], str]:
    """Split '---' front matter (key: JSON value) from the body."""
    if not markdown.startswith("---\n"):
        raise ValueError("Missing front matter")
    head, sep, body = markdown[4:].partition("\n---\n")
    if not sep:
        raise ValueError("Unclosed front matter")
    meta = {}
    for line in head.splitlines():
        key, _, value = line.partition(": ")
        meta[key.strip()] = json.loads(value)
    return meta, body.strip("\n")


def context_label(doc_label: str, path: Iterable[str], sep: str) -> str:
    """Join the document's context label and the heading path."""
    if not doc_label:
        raise ValueError("Empty context_label; fill it in data/manual/documents.csv")
    return sep.join([doc_label, *path])


def embedding_text(chunk: dict[str, Any]) -> str:
    """Text sent to the embedding model: context label, blank line, chunk text."""
    return f"{chunk['context']}\n\n{chunk['text']}"


def split_sections(body: str) -> list[Section]:
    """Cut the body at Markdown headings; text before the first heading has path ()."""
    sections: list[Section] = []
    stack: list[tuple[int, str]] = []
    lines: list[str] = []

    def flush() -> None:
        text = "\n".join(lines).strip()
        if text:
            sections.append(Section(tuple(t for _, t in stack), text))

    for line in body.split("\n"):
        m = HEADING_RE.match(line)
        if m:
            flush()
            lines = [line]
            level = len(m.group(1))
            stack = [(lv, t) for lv, t in stack if lv < level] + [(level, m.group(2))]
        else:
            lines.append(line)
    flush()
    return sections


def merge_short_sections(sections: list[Section], min_chars: int) -> list[Section]:
    """Merge each section shorter than min_chars with the next one.

    The merged path is the next section's path when the short section is its parent
    (e.g. a heading with no text of its own), else the short section's path.
    A short last section is merged into the previous one.
    """
    out: list[Section] = []
    pending: Section | None = None
    for sec in sections:
        if pending is not None:
            is_parent = sec.path[: len(pending.path)] == pending.path
            path = sec.path if is_parent else pending.path
            sec = Section(path, f"{pending.text}\n\n{sec.text}")
            pending = None
        if len(sec.text) < min_chars:
            pending = sec
        else:
            out.append(sec)
    if pending is not None:
        if out:
            last = out.pop()
            out.append(Section(last.path, f"{last.text}\n\n{pending.text}"))
        else:
            out.append(pending)
    return out


def split_sentences(
    text: str, abbreviations: Iterable[str] = config.SENTENCE_ABBREVIATIONS
) -> list[str]:
    """Split a paragraph into sentences; never split after an abbreviation or a
    leading list number such as '1.'."""
    abbr = set(abbreviations)
    parts = SENTENCE_END_RE.split(text.strip())
    out: list[str] = []
    for part in parts:
        if out:
            prev = out[-1]
            last_word = prev.rstrip(".").rsplit(" ", 1)[-1]
            if last_word in abbr or re.fullmatch(r"[0-9IVX]+\.|[a-zđ]\)", prev):
                out[-1] = f"{prev} {part}"
                continue
        out.append(part)
    return [s for s in out if s]


def pack(pieces: list[str], max_chars: int, sep: str) -> list[str]:
    """Greedily join pieces with `sep` into groups of at most max_chars.

    A piece longer than max_chars stays alone in its own group.
    """
    groups: list[str] = []
    for piece in pieces:
        if groups and len(groups[-1]) + len(sep) + len(piece) <= max_chars:
            groups[-1] = f"{groups[-1]}{sep}{piece}"
        else:
            groups.append(piece)
    return groups


def split_long_text(text: str, max_chars: int) -> list[str]:
    """Split text at paragraph breaks, then sentence ends, into parts <= max_chars."""
    if len(text) <= max_chars:
        return [text]
    pieces: list[str] = []
    for para in re.split(r"\n\s*\n", text):
        para = para.strip()
        if not para:
            continue
        if len(para) <= max_chars:
            pieces.append(para)
        else:
            pieces.extend(pack(split_sentences(para), max_chars, " "))
    return pack(pieces, max_chars, "\n\n")


def chunk_document(
    meta: dict[str, str], body: str, params: dict[str, Any]
) -> list[dict[str, Any]]:
    """Chunk one document with the heading strategy; return chunk records."""
    if params.get("overlap_chars", 0) != 0:
        raise ValueError("Only overlap_chars = 0 is supported")
    sections = merge_short_sections(split_sections(body), params["min_chars"])
    chunks = []
    for sec in sections:
        for part in split_long_text(sec.text, params["max_chars"]):
            n = len(chunks) + 1
            chunks.append(
                {
                    "chunk_id": f"{meta['doc_id']}_{n:03d}",
                    "doc_id": meta["doc_id"],
                    "heading_path": list(sec.path),
                    "context": context_label(
                        meta.get("context_label", ""), sec.path, params["context_sep"]
                    ),
                    "text": part,
                    "char_count": len(part),
                    **{f: meta.get(f, "") for f in DOC_FIELDS},
                }
            )
    return chunks


def squash(text: str) -> str:
    """Remove all whitespace (for lossless comparisons)."""
    return re.sub(r"\s+", "", text)


def check_chunks(
    chunks: list[dict[str, Any]],
    bodies: dict[str, str],
    params: dict[str, Any],
    required_text: dict[str, str],
    required_context: dict[str, str],
) -> tuple[list[str], list[str]]:
    """Return (problems, warnings) for a set of chunks."""
    problems, warnings = [], []
    by_doc: dict[str, list[dict[str, Any]]] = {}
    for c in chunks:
        by_doc.setdefault(c["doc_id"], []).append(c)
    for doc_id, body in bodies.items():
        joined = "".join(c["text"] for c in by_doc.get(doc_id, []))
        if squash(joined) != squash(body):
            problems.append(f"{doc_id}: chunks do not add up to the document text")
    for doc_id, pattern in required_text.items():
        hits = [c for c in by_doc.get(doc_id, []) if re.search(pattern, c["text"])]
        want = required_context.get(doc_id, "")
        if not hits:
            problems.append(f"{doc_id}: required text not found in any chunk")
        elif not all(want in c["context"] for c in hits):
            problems.append(f"{doc_id}: answer chunk context lacks '{want}'")
    for c in chunks:
        n = c["char_count"]
        if n > params["max_chars"]:
            single = len(split_sentences(c["text"])) == 1
            note = "single sentence, allowed" if single else "NOT a single sentence"
            (warnings if single else problems).append(
                f"{c['chunk_id']}: {n} chars > {params['max_chars']} ({note})"
            )
        elif n < params["min_chars"]:
            warnings.append(f"{c['chunk_id']}: {n} chars < {params['min_chars']}")
    return problems, warnings


# ---------- I/O ----------


def latest_dir(root: Path, wanted: str | None = None) -> Path:
    """Return root/<wanted> or the newest dated sub-folder of root."""
    if wanted:
        return root / wanted
    dated = sorted(
        p
        for p in root.iterdir()
        if p.is_dir() and re.fullmatch(r"\d{4}-\d{2}-\d{2}", p.name)
    )
    if not dated:
        raise FileNotFoundError(f"No dated folder in {root}")
    return dated[-1]


def main(argv: list[str] | None = None) -> None:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(description="Chunk processed documents.")
    parser.add_argument("--strategy", default=config.DEFAULT_CHUNKING)
    parser.add_argument("--snapshot", help="snapshot date folder (default: newest)")
    parser.add_argument("--in-root", type=Path, default=config.PROCESSED_DOCUMENTS_DIR)
    parser.add_argument("--out-root", type=Path, default=config.CHUNKS_DIR)
    parser.add_argument("--force", action="store_true", help="overwrite chunks.jsonl")
    args = parser.parse_args(argv)
    if args.strategy not in config.CHUNKING_STRATEGIES:
        parser.error(f"Unknown strategy: {args.strategy}")
    params = config.CHUNKING_STRATEGIES[args.strategy]

    in_dir = latest_dir(args.in_root, args.snapshot)
    out_path = args.out_root / in_dir.name / args.strategy / "chunks.jsonl"
    if out_path.exists() and not args.force:
        parser.error(f"{out_path} exists; use --force to overwrite")

    chunks: list[dict[str, Any]] = []
    bodies: dict[str, str] = {}
    for md in sorted(in_dir.glob("*.md")):
        meta, body = parse_front_matter(md.read_text(encoding="utf-8"))
        bodies[meta["doc_id"]] = body
        chunks.extend(chunk_document(meta, body, params))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        for c in chunks:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")

    print(f"{'doc_id':24} {'chunks':>6} {'min':>5} {'median':>6} {'max':>5}")
    for doc_id in bodies:
        sizes = [c["char_count"] for c in chunks if c["doc_id"] == doc_id]
        print(
            f"{doc_id:24} {len(sizes):>6} {min(sizes):>5} "
            f"{statistics.median(sizes):>6.0f} {max(sizes):>5}"
        )
    sizes = [c["char_count"] for c in chunks]
    print(
        f"{'ALL':24} {len(sizes):>6} {min(sizes):>5} "
        f"{statistics.median(sizes):>6.0f} {max(sizes):>5}"
    )
    problems, warnings = check_chunks(
        chunks, bodies, params, config.REQUIRED_TEXT, config.REQUIRED_CONTEXT
    )
    print(f"\nOutput: {out_path}")
    print("Checks: all passed" if not problems else "Checks FAILED:")
    for p in problems:
        print(f"  - {p}")
    print(f"Warnings: {len(warnings)}")
    for w in warnings:
        print(f"  - {w}")


if __name__ == "__main__":
    main()
