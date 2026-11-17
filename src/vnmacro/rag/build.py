"""Rebuild the RAG tables: load documents and chunks, embed them, check vectors.

Run from the repository root (needs requirements-embed.txt):

    PYTHONPATH=src python -m vnmacro.rag.build
    PYTHONPATH=src python -m vnmacro.rag.build --strategy heading_v1

Runs vnmacro.rag.load_rag, then vnmacro.rag.embed (load_rag empties
rag.chunk_embeddings, so the order matters), then checks that every chunk of the
strategy has exactly one vector of the chosen backend (--backend local | openai).
load_rag deletes every stored vector, so run it once per backend you deploy.
"""

from __future__ import annotations

import argparse

from vnmacro import config
from vnmacro.ingest.load_db import db_connect
from vnmacro.rag import embed, load_rag


def main(argv: list[str] | None = None) -> None:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(description="Load chunks, embed, check.")
    parser.add_argument("--strategy", default=config.DEFAULT_CHUNKING)
    parser.add_argument("--snapshot", help="snapshot date folder (default: newest)")
    parser.add_argument(
        "--backend", choices=sorted(config.EMBEDDING_BACKENDS), default="local"
    )
    args = parser.parse_args(argv)
    snapshot = ["--snapshot", args.snapshot] if args.snapshot else []

    print("== 1/3 load_rag ==")
    load_rag.main(["--strategy", args.strategy, *snapshot])
    print("\n== 2/3 embed ==")
    embed.main(["--strategy", args.strategy, "--backend", args.backend])

    print("\n== 3/3 final check ==")
    s = config.EMBEDDING_BACKENDS[args.backend]
    with db_connect() as conn:
        conn.execute(f"SET search_path = {config.RAG_SCHEMA}, public")
        with conn.cursor() as cur:
            problems = embed.db_checks(
                cur,
                embed.model_id(s["repo"], s["revision"]),
                args.strategy,
                s["dim"],
                config.NORM_TOLERANCE,
            )
    if problems:
        raise SystemExit("Build FAILED:\n  - " + "\n  - ".join(problems))
    print("Build OK: every chunk has exactly one vector")


if __name__ == "__main__":
    main()
