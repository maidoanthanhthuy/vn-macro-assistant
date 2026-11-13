"""Load documents and chunks into the rag schema.

Run from the repository root (after sql/rag_schema.sql and vnmacro.rag.chunking):

    PYTHONPATH=src python -m vnmacro.rag.load_rag
    PYTHONPATH=src python -m vnmacro.rag.load_rag --strategy heading_v1

Reads data/manual/documents.csv (verified rows) and
data/processed/chunks/<newest snapshot>/<strategy>/chunks.jsonl, then empties and
refills rag.documents and rag.chunks in one transaction. Emptying cascades to
rag.chunk_embeddings, so run vnmacro.rag.embed afterwards (unchanged chunks come
from the local cache and are not re-encoded).
"""

from __future__ import annotations

import argparse
import calendar
import json
import re
from collections.abc import Iterable
from datetime import date
from pathlib import Path
from typing import Any

from vnmacro import config
from vnmacro.ingest.load_db import db_connect, read_csv
from vnmacro.rag.chunking import latest_dir

Row = dict[str, Any]

DOC_COLUMNS = (
    "doc_id", "source", "doc_type", "title", "context_label", "reference_period",
    "period_start", "period_end", "published_date", "url", "snapshot_date",
)  # fmt: skip
CHUNK_COLUMNS = (
    "chunk_id", "doc_id", "strategy", "seq", "heading_path", "context", "text",
    "char_count",
)  # fmt: skip
PERIOD_RE = re.compile(r"^(\d{4})(?:-(0[1-9]|1[0-2])|-Q([1-4]))?$")


def period_bounds(reference_period: str) -> tuple[date, date]:
    """First and last day of 'YYYY-MM' (month), 'YYYY-Qn' (quarter) or 'YYYY' (year)."""
    m = PERIOD_RE.fullmatch(reference_period)
    if not m:
        raise ValueError(f"Bad reference_period: {reference_period!r}")
    year, month, quarter = int(m[1]), m[2], m[3]
    if month:
        first = last = int(month)
    elif quarter:
        last = int(quarter) * 3
        first = last - 2
    else:
        first, last = 1, 12
    return date(year, first, 1), date(year, last, calendar.monthrange(year, last)[1])


def build_documents(rows: Iterable[Row], snapshot_date: date) -> list[Row]:
    """Typed rag.documents rows from verified documents.csv rows."""
    out = []
    for r in rows:
        if r["verified"] != "yes":
            continue
        start, end = period_bounds(r["reference_period"])
        out.append(
            {
                **{c: r[c] for c in DOC_COLUMNS[:6]},
                "period_start": start,
                "period_end": end,
                "published_date": date.fromisoformat(r["published_date"]),
                "url": r["url"],
                "snapshot_date": snapshot_date,
            }
        )
    return out


def build_chunks(chunks: Iterable[Row], strategy: str) -> list[Row]:
    """rag.chunks rows; seq is the 1-based position of the chunk within its document."""
    seen: dict[str, int] = {}
    out = []
    for c in chunks:
        seen[c["doc_id"]] = seen.get(c["doc_id"], 0) + 1
        out.append(
            {
                **{k: c[k] for k in ("chunk_id", "doc_id", "context", "text")},
                "strategy": strategy,
                "seq": seen[c["doc_id"]],
                "heading_path": list(c["heading_path"]),
                "char_count": c["char_count"],
            }
        )
    return out


def check_load(docs: list[Row], chunks: list[Row], expected_docs: int) -> list[str]:
    """Blocking problems: wrong document count or chunks of unknown documents."""
    problems = []
    if len(docs) != expected_docs:
        problems.append(f"{len(docs)} documents, expected {expected_docs}")
    known = {d["doc_id"] for d in docs}
    orphans = sorted({c["doc_id"] for c in chunks} - known)
    if orphans:
        problems.append(f"chunks for unknown documents: {', '.join(orphans)}")
    return problems


# ---------- I/O ----------


def read_jsonl(path: Path) -> list[Row]:
    """Read one JSON object per line."""
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def load_rag(conn: Any, docs: list[Row], chunks: list[Row]) -> dict[str, int]:
    """Empty and reload rag.documents and rag.chunks in one transaction."""
    schema = config.RAG_SCHEMA
    with conn.transaction(), conn.cursor() as cur:
        cur.execute(f"TRUNCATE {schema}.documents CASCADE")
        for table, cols, rows in (
            ("documents", DOC_COLUMNS, docs),
            ("chunks", CHUNK_COLUMNS, chunks),
        ):
            sql = f"COPY {schema}.{table} ({', '.join(cols)}) FROM STDIN"
            with cur.copy(sql) as copy:
                for r in rows:
                    copy.write_row([r[c] for c in cols])
        counts = {}
        for table in ("documents", "chunks"):
            cur.execute(f"SELECT count(*) FROM {schema}.{table}")
            counts[table] = cur.fetchone()[0]
    return counts


def main(argv: list[str] | None = None) -> None:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(description="Load documents and chunks.")
    parser.add_argument("--strategy", default=config.DEFAULT_CHUNKING)
    parser.add_argument("--snapshot", help="snapshot date folder (default: newest)")
    args = parser.parse_args(argv)

    snap_dir = latest_dir(config.CHUNKS_DIR, args.snapshot)
    raw_chunks = read_jsonl(snap_dir / args.strategy / "chunks.jsonl")
    docs = build_documents(
        read_csv(config.DOCUMENTS_FILE), date.fromisoformat(snap_dir.name)
    )
    chunks = build_chunks(raw_chunks, args.strategy)
    problems = check_load(docs, chunks, config.EXPECTED_DOCUMENTS)
    if problems:
        raise SystemExit("Load stopped:\n  - " + "\n  - ".join(problems))

    with db_connect() as conn:
        counts = load_rag(conn, docs, chunks)
    print(f"Snapshot {snap_dir.name}, strategy {args.strategy}")
    print(f"rag.documents: {counts['documents']} (expected {len(docs)})")
    print(f"rag.chunks:    {counts['chunks']} (chunks.jsonl: {len(raw_chunks)})")
    if counts["documents"] != len(docs) or counts["chunks"] != len(raw_chunks):
        raise SystemExit("Row counts do not match the input")


if __name__ == "__main__":
    main()
