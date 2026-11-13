"""Embed chunks with a pinned sentence-transformers model and store the vectors.

Run from the repository root (after vnmacro.rag.load_rag):

    PYTHONPATH=src python -m vnmacro.rag.embed
    PYTHONPATH=src python -m vnmacro.rag.embed --strategy heading_v1

Model and settings: config.EMBEDDING_MODEL (repo pinned to a Hugging Face commit).
The text sent to the model is chunking.embedding_text(): context + blank line + text.
Vectors are normalized, so the dot product equals cosine similarity.

Vectors are cached in data/processed/embeddings/<model>/<commit>/cache.npz, keyed by
the SHA-256 of the embedded text: a rerun only encodes new or changed chunks. The
vectors of the strategy's chunks are then replaced in rag.chunk_embeddings in one
transaction, followed by checks (one vector per chunk, 1024 dims, norm ~1) and a
retrieval check on seed question q10.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import resource
import time
from pathlib import Path
from typing import Any

import numpy as np

from vnmacro import config
from vnmacro.ingest.load_db import db_connect
from vnmacro.rag.chunking import embedding_text


def model_id(repo: str, revision: str) -> str:
    """Name stored in rag.chunk_embeddings.model_name: repo@commit."""
    return f"{repo}@{revision}"


def text_hash(text: str) -> str:
    """SHA-256 hex digest of the text, used as the cache key."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def missing_keys(keys: list[str], cache: dict[str, np.ndarray]) -> list[str]:
    """Keys not yet in the cache, without duplicates, in first-seen order."""
    return [k for k in dict.fromkeys(keys) if k not in cache]


def check_vectors(vectors: np.ndarray, dim: int, tol: float) -> list[str]:
    """Problems with a (n, dim) matrix: wrong shape, NaN/inf, norm not ~1."""
    if vectors.ndim != 2 or vectors.shape[1] != dim:
        return [f"shape {vectors.shape}, expected (n, {dim})"]
    problems = []
    bad = ~np.isfinite(vectors).all(axis=1)
    if bad.any():
        problems.append(f"{int(bad.sum())} vectors with NaN or inf")
    off = np.abs(np.linalg.norm(vectors, axis=1) - 1.0) > tol
    off &= ~bad
    if off.any():
        problems.append(f"{int(off.sum())} vectors with norm off 1 by more than {tol}")
    return problems


def vector_literal(vector: np.ndarray) -> str:
    """pgvector text form, e.g. '[0.1,0.2]'."""
    return "[" + ",".join(repr(float(x)) for x in vector) + "]"


def answer_chunks(chunks: list[dict[str, Any]], doc_id: str, pattern: str) -> set[str]:
    """chunk_ids of doc_id whose text matches the answer pattern."""
    rx = re.compile(pattern)
    return {
        c["chunk_id"] for c in chunks if c["doc_id"] == doc_id and rx.search(c["text"])
    }


# ---------- I/O ----------


def cache_path(root: Path, repo: str, revision: str) -> Path:
    """Cache file for one model commit."""
    return root / repo.replace("/", "__") / revision / "cache.npz"


def load_cache(path: Path) -> dict[str, np.ndarray]:
    """Read the vector cache (empty if missing)."""
    if not path.exists():
        return {}
    data = np.load(path)
    return dict(zip(data["keys"].tolist(), data["vectors"], strict=True))


def save_cache(path: Path, cache: dict[str, np.ndarray]) -> None:
    """Write the vector cache atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp.npz")
    keys = sorted(cache)
    np.savez(tmp, keys=np.array(keys), vectors=np.stack([cache[k] for k in keys]))
    tmp.replace(path)


def load_model(settings: dict) -> Any:
    """Load the pinned SentenceTransformer on CPU."""
    import torch
    from sentence_transformers import SentenceTransformer

    torch.set_num_threads(settings["num_threads"])
    model = SentenceTransformer(
        settings["repo"], revision=settings["revision"], device="cpu"
    )
    model.max_seq_length = settings["max_seq_length"]
    return model


def encode(model: Any, texts: list[str], batch_size: int) -> np.ndarray:
    """Normalized float32 embeddings, one row per text."""
    return model.encode(
        texts,
        batch_size=batch_size,
        normalize_embeddings=True,
        convert_to_numpy=True,
        show_progress_bar=len(texts) > batch_size,
    ).astype(np.float32)


def peak_rss_mb() -> float:
    """Peak resident memory of this process in MB (Linux reports KB)."""
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024


def fetch_chunks(cur: Any, strategy: str) -> list[dict[str, Any]]:
    """Chunks of one strategy from rag.chunks."""
    cur.execute(
        "SELECT chunk_id, doc_id, context, text FROM chunks "
        "WHERE strategy = %s ORDER BY chunk_id",
        (strategy,),
    )
    cols = [d.name for d in cur.description]
    return [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]


def write_embeddings(
    conn: Any, name: str, strategy: str, rows: list[tuple[str, np.ndarray]]
) -> None:
    """Replace this model's vectors for the strategy's chunks in one transaction."""
    with conn.transaction(), conn.cursor() as cur:
        cur.execute(
            "DELETE FROM chunk_embeddings e USING chunks c "
            "WHERE e.chunk_id = c.chunk_id AND c.strategy = %s AND e.model_name = %s",
            (strategy, name),
        )
        sql = "COPY chunk_embeddings (chunk_id, model_name, embedding) FROM STDIN"
        with cur.copy(sql) as copy:
            for chunk_id, vec in rows:
                copy.write_row([chunk_id, name, vector_literal(vec)])


def db_checks(cur: Any, name: str, strategy: str, dim: int, tol: float) -> list[str]:
    """Print stored-vector stats and return problems."""
    cur.execute(
        "SELECT count(*), count(*) FILTER (WHERE n <> 1) FROM ("
        " SELECT c.chunk_id, count(e.chunk_id) AS n FROM chunks c"
        " LEFT JOIN chunk_embeddings e"
        "  ON e.chunk_id = c.chunk_id AND e.model_name = %s"
        " WHERE c.strategy = %s GROUP BY c.chunk_id) t",
        (name, strategy),
    )
    n_chunks, n_bad = cur.fetchone()
    cur.execute(
        "SELECT count(*), min(vector_dims(embedding)), max(vector_dims(embedding)),"
        " min(vector_norm(embedding)), max(vector_norm(embedding))"
        " FROM chunk_embeddings WHERE model_name = %s",
        (name,),
    )
    n_vec, dmin, dmax, nmin, nmax = cur.fetchone()
    print(f"Chunks ({strategy}): {n_chunks}; without exactly 1 vector: {n_bad}")
    print(f"Vectors: {n_vec}; dims {dmin}-{dmax}; norm {nmin:.6f}-{nmax:.6f}")
    problems = []
    if n_bad:
        problems.append(f"{n_bad} chunks without exactly one vector")
    if (dmin, dmax) != (dim, dim):
        problems.append(f"dims {dmin}-{dmax}, expected {dim}")
    if abs(nmin - 1) > tol or abs(nmax - 1) > tol:
        problems.append(f"norms {nmin:.6f}-{nmax:.6f} not ~1")
    return problems


def search(cur: Any, name: str, strategy: str, query_vec: np.ndarray, k: int) -> list:
    """Top-k chunks by dot product (= cosine for normalized vectors), exact scan."""
    cur.execute(
        "SELECT c.chunk_id, c.context, -(e.embedding <#> %s::vector) AS score"
        " FROM chunk_embeddings e JOIN chunks c USING (chunk_id)"
        " WHERE e.model_name = %s AND c.strategy = %s"
        " ORDER BY e.embedding <#> %s::vector LIMIT %s",
        (vector_literal(query_vec), name, strategy, vector_literal(query_vec), k),
    )
    return cur.fetchall()


def main(argv: list[str] | None = None) -> None:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(description="Embed chunks and store vectors.")
    parser.add_argument("--strategy", default=config.DEFAULT_CHUNKING)
    args = parser.parse_args(argv)
    s = config.EMBEDDING_MODEL
    name = model_id(s["repo"], s["revision"])
    path = cache_path(config.EMBEDDINGS_DIR, s["repo"], s["revision"])

    with db_connect() as conn:
        conn.autocommit = True  # writes commit in their own transaction block
        conn.execute(f"SET search_path = {config.RAG_SCHEMA}, public")
        with conn.cursor() as cur:
            chunks = fetch_chunks(cur, args.strategy)
        if not chunks:
            raise SystemExit(f"No chunks for {args.strategy}; run load_rag first")
        texts = {text_hash(t): t for t in map(embedding_text, chunks)}
        keys = [text_hash(embedding_text(c)) for c in chunks]

        cache = load_cache(path)
        todo = missing_keys(keys, cache)
        print(f"Model: {name}")
        print(f"Chunks: {len(chunks)}; cached: {len(chunks) - len(todo)}; "
              f"to encode: {len(todo)}")  # fmt: skip
        t0 = time.perf_counter()
        model = load_model(s)
        t_load = time.perf_counter() - t0
        t_enc = 0.0
        if todo:
            t1 = time.perf_counter()
            new = encode(model, [texts[k] for k in todo], s["batch_size"])
            t_enc = time.perf_counter() - t1
            problems = check_vectors(new, s["dim"], config.NORM_TOLERANCE)
            if problems:
                raise SystemExit("Bad vectors: " + "; ".join(problems))
            cache.update(zip(todo, new, strict=True))
            save_cache(path, cache)

        write_embeddings(
            conn,
            name,
            args.strategy,
            [(c["chunk_id"], cache[k]) for c, k in zip(chunks, keys, strict=True)],
        )

        print("\n== Checks ==")
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM documents")
            n_docs = cur.fetchone()[0]
            print(f"Documents: {n_docs} (expected {config.EXPECTED_DOCUMENTS})")
            problems = db_checks(
                cur, name, args.strategy, s["dim"], config.NORM_TOLERANCE
            )
            if n_docs != config.EXPECTED_DOCUMENTS:
                problems.append(f"{n_docs} documents")

            rc = config.RETRIEVAL_CHECK
            expected = answer_chunks(
                chunks, rc["doc_id"], config.REQUIRED_TEXT[rc["doc_id"]]
            )
            q = encode(model, [rc["query"]], 1)[0]
            hits = search(cur, name, args.strategy, q, rc["top_k"])
        print(f"\n== Search: {rc['query']} ==")
        for rank, (chunk_id, context, score) in enumerate(hits, 1):
            mark = "  <- q10 answer" if chunk_id in expected else ""
            print(f"{rank}. {score:.4f}  {chunk_id}  {context}{mark}")
        if not expected:
            problems.append("q10 answer chunk not found in chunks")
        elif not expected & {h[0] for h in hits}:
            problems.append(f"q10 answer {sorted(expected)} not in top {rc['top_k']}")

        print("\n== Resources ==")
        print(f"Model load: {t_load:.1f} s; encoding {len(todo)} chunks: {t_enc:.1f} s")
        print(f"Peak RAM (process): {peak_rss_mb():.0f} MB")
        print("\nChecks: all passed" if not problems else "\nChecks FAILED:")
        for p in problems:
            print(f"  - {p}")
        if problems:
            raise SystemExit(1)


if __name__ == "__main__":
    main()
