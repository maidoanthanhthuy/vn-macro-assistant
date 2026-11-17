"""Document retrieval for the agent: period filter first, then semantic search.

Reuses the Phase 2 embedding code (vnmacro.rag.embed: pinned model, normalized
vectors, exact dot-product scan). With a period, only chunks of documents whose period
overlaps it are searched; if no document overlaps, all documents are searched and a
note says so. Runs as vnmacro_reader (DATABASE_URL_READER). The model is loaded once
per process.

    PYTHONPATH=src python -m vnmacro.agent.retrieve "Lạm phát tháng 10/2026?" \
        --start 2026-10-01 --end 2026-10-31
"""

from __future__ import annotations

import datetime as dt
import functools
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from vnmacro import config

EmbedFn = Callable[[str], tuple[Any, int]]  # text -> (vector, API input tokens)
# (query vector, period start, period end, k) -> rows in RetrievedChunk field order
SearchFn = Callable[[Any, dt.date | None, dt.date | None, int], list[tuple[Any, ...]]]


@dataclass(frozen=True)
class RetrievedChunk:
    """One search hit with what the answer step needs for a citation."""

    text: str
    context_label: str
    title: str
    reference_period: str
    url: str
    score: float
    doc_id: str
    chunk_id: str


@dataclass(frozen=True)
class RetrievalResult:
    """Top-k chunks, whether the period filter was used, and notes for the answer."""

    chunks: list[RetrievedChunk]
    filtered: bool
    notes: tuple[str, ...] = ()
    model: str | None = None  # embedding model of the question (API backend only)
    tokens: int = 0  # API input tokens used to embed the question
    cost_usd: float | None = None  # None for the local model


def vector_coverage_error(
    n_chunks: int, n_vectors: int, backend: str, model_name: str, strategy: str
) -> str | None:
    """Startup error when not every chunk has a vector of the model in use."""
    if n_chunks and n_vectors == n_chunks:
        return None
    return (
        f"Embedding backend {backend!r} ({model_name}) has {n_vectors} vectors for "
        f"{n_chunks} chunks of strategy {strategy!r}. Embed the chunks again: "
        f"PYTHONPATH=src python -m vnmacro.rag.embed --backend {backend} "
        f"--strategy {strategy}"
        + ("" if n_chunks else " (no chunks: run vnmacro.rag.build first)")
    )


def period_args(
    start: dt.date | None, end: dt.date | None
) -> tuple[dt.date, dt.date] | None:
    """Period for the filter (one missing end copies the other); None if unusable."""
    start, end = start or end, end or start
    if start is None or end is None or start > end:
        return None  # the resolver already noted an invalid period
    return start, end


def first_rank(
    chunks: list[RetrievedChunk], ids: tuple[str, ...], field: str = "doc_id"
) -> int | None:
    """1-based rank of the first chunk whose doc_id (or chunk_id) is in ids, or None."""
    for i, c in enumerate(chunks, start=1):
        if getattr(c, field) in ids:
            return i
    return None


@dataclass
class Retriever:
    """Embed the question once, search with the period filter, fall back to all."""

    embed: EmbedFn
    search: SearchFn
    k: int = config.RETRIEVE_TOP_K
    model: str | None = None  # API model name, for the log
    price_per_mtok: float | None = None  # USD per 1M input tokens; None = free/local

    def retrieve(
        self,
        question: str,
        period_start: dt.date | None = None,
        period_end: dt.date | None = None,
        k: int | None = None,
    ) -> RetrievalResult:
        """Top-k chunks for a question, filtered by period when one is given."""
        k = k or self.k
        vec, tokens = self.embed(question)
        cost = None
        if self.price_per_mtok is not None:
            cost = tokens * self.price_per_mtok / 1_000_000
        usage = {"model": self.model, "tokens": tokens, "cost_usd": cost}
        period = period_args(period_start, period_end)
        notes: tuple[str, ...] = ()
        if period:
            rows = self.search(vec, *period, k)
            if rows:
                return RetrievalResult(
                    [RetrievedChunk(*r) for r in rows], True, **usage
                )
            notes = (
                f"No document covers {period[0]}..{period[1]}; "
                "searched all documents instead.",
            )
        rows = self.search(vec, None, None, k)
        return RetrievalResult(
            [RetrievedChunk(*r) for r in rows], False, notes, **usage
        )


# ---------- I/O ----------

_SEARCH_SQL = """
SELECT c.text, d.context_label, d.title, d.reference_period, d.url,
       -(e.embedding OPERATOR(rag.<#>) %(q)s::rag.vector) AS score, d.doc_id, c.chunk_id
FROM rag.chunk_embeddings e
JOIN rag.chunks c USING (chunk_id)
JOIN rag.documents d USING (doc_id)
WHERE e.model_name = %(model)s AND c.strategy = %(strategy)s
  AND (%(start)s::date IS NULL
       OR (d.period_start <= %(end)s::date AND d.period_end >= %(start)s::date))
ORDER BY e.embedding OPERATOR(rag.<#>) %(q)s::rag.vector
LIMIT %(k)s
"""


_COVERAGE_SQL = """
SELECT (SELECT count(*) FROM rag.chunks WHERE strategy = %(strategy)s),
       (SELECT count(*) FROM rag.chunk_embeddings e JOIN rag.chunks c USING (chunk_id)
        WHERE c.strategy = %(strategy)s AND e.model_name = %(model)s)
"""


def db_vector_counts(url: str, model_name: str, strategy: str) -> tuple[int, int]:
    """(chunks of the strategy, vectors of the model for them), as the reader."""
    import psycopg

    with psycopg.connect(url) as conn:
        conn.read_only = True
        row = conn.execute(
            _COVERAGE_SQL, {"strategy": strategy, "model": model_name}
        ).fetchone()
    return int(row[0]), int(row[1])


def db_search(
    url: str,
    model_name: str,
    strategy: str,
    vec: Any,
    start: dt.date | None,
    end: dt.date | None,
    k: int,
) -> list[tuple[Any, ...]]:
    """Exact dot-product search in a read-only transaction as the reader."""
    import psycopg

    from vnmacro.rag.embed import vector_literal

    params = {
        "q": vector_literal(vec),
        "model": model_name,
        "strategy": strategy,
        "start": start,
        "end": end,
        "k": k,
    }
    with psycopg.connect(url) as conn:
        conn.read_only = True
        return [tuple(r) for r in conn.execute(_SEARCH_SQL, params).fetchall()]


@functools.cache
def get_retriever(
    strategy: str = config.DEFAULT_CHUNKING, backend: str | None = None
) -> Retriever:
    """Retriever for one embedding backend (default: EMBEDDING_BACKEND), cached.

    Stops with SystemExit when not every chunk has a vector of that backend's model.
    "local" loads the pinned model once; "openai" embeds each question with the API
    (no torch needed) and reports its tokens and cost.
    """
    import os

    from dotenv import load_dotenv

    from vnmacro.rag.embed import Encoder, backend_from_env, backend_settings, model_id

    load_dotenv()
    url = os.environ.get("DATABASE_URL_READER")
    if not url:
        raise SystemExit("DATABASE_URL_READER is not set in .env")
    backend = backend or backend_from_env()
    settings = backend_settings(backend)
    name = model_id(settings["repo"], settings["revision"])
    error = vector_coverage_error(
        *db_vector_counts(url, name, strategy), backend, name, strategy
    )
    if error:
        raise SystemExit(error)
    encoder = Encoder(backend, settings)
    if backend == "local":
        encoder.encode(["warm-up"])  # load the model now, not on the first question

    def embed(text: str) -> tuple[Any, int]:
        before = encoder.tokens
        vec = encoder.encode([text])[0]
        return vec, encoder.tokens - before

    api_model = settings.get("api_model")
    return Retriever(
        embed=embed,
        search=lambda vec, s, e, k: db_search(url, name, strategy, vec, s, e, k),
        model=api_model,
        price_per_mtok=config.EMBEDDING_PRICES_USD_PER_MTOK.get(api_model or ""),
    )


def retrieve(
    question: str,
    period_start: dt.date | None = None,
    period_end: dt.date | None = None,
    k: int = config.RETRIEVE_TOP_K,
) -> RetrievalResult:
    """Top-k document chunks for a question (see module docstring)."""
    return get_retriever().retrieve(question, period_start, period_end, k)


def main(argv: list[str] | None = None) -> None:
    """Print the top-k chunks for one question."""
    import argparse

    parser = argparse.ArgumentParser(description="Retrieve document chunks.")
    parser.add_argument("question")
    parser.add_argument("--start", type=dt.date.fromisoformat)
    parser.add_argument("--end", type=dt.date.fromisoformat)
    parser.add_argument("-k", type=int, default=config.RETRIEVE_TOP_K)
    args = parser.parse_args(argv)
    res = retrieve(args.question, args.start, args.end, args.k)
    print(f"filtered: {res.filtered}   notes: {list(res.notes)}")
    for i, c in enumerate(res.chunks, start=1):
        print(f"{i}. {c.score:.4f} {c.chunk_id} [{c.reference_period}] {c.title}")
        print(f"   {c.context_label} | {c.url}")
        print(f"   {' '.join(c.text.split())[:150]}")


if __name__ == "__main__":
    main()
