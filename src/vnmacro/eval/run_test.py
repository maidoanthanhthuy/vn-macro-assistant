"""Official test-set run: full agent vs RAG-only, graded by an LLM.

Every question is answered twice: by the full agent (router -> resolver -> RAG / SQL ->
answer) and by the RAG-only baseline (search all documents, no router, no period
filter, no SQL -> same answer step). Each answer gets one LLM grade (prompts/grade.md).

    PYTHONPATH=src python -m vnmacro.eval.run_test

The test set is run once, for the official score: the command refuses to run when
results already exist in the output folder (use --force only to redo a broken run).
Try it on the dev set first:

    PYTHONPATH=src python -m vnmacro.eval.run_test \
        --questions eval/seed_questions.csv --out eval/runs/dev_check --prefix dev

Outputs in --out: <prefix>_results.jsonl (one row per question and mode),
<prefix>_summary.json and .md, human_check.md (10 random answers from both modes,
without grades or mode) and human_check_key.json (mode of each human-check item).
"""

from __future__ import annotations

import csv
import json
import random
import time
from collections import Counter
from pathlib import Path
from typing import Any

from vnmacro import config
from vnmacro.eval.grade import VERDICTS
from vnmacro.eval.run_sql_dev import expected_route

MODES: tuple[str, ...] = ("agent", "rag_only")
ROUTES: tuple[str, ...] = ("sql", "rag", "both", "out_of_scope")


# ---------- pure helpers ----------


def _mean(values: list[float]) -> float:
    """Mean of a list (0 for an empty list)."""
    return sum(values) / len(values) if values else 0.0


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Verdict counts per mode (total and per expected route), router accuracy, cost."""
    out: dict[str, Any] = {"modes": {}}
    for mode in MODES:
        mrows = [r for r in rows if r["mode"] == mode]
        if not mrows:
            continue
        by_route = {
            route: dict(Counter(r["verdict"] for r in mrows if r["expected"] == route))
            for route in ROUTES
        }
        info: dict[str, Any] = {
            "n": len(mrows),
            "verdicts": dict(Counter(r["verdict"] for r in mrows)),
            "by_route": {k: v for k, v in by_route.items() if v},
            "mean_latency_ms": round(_mean([r["latency_ms"] for r in mrows])),
            "mean_cost_usd": _mean([r["cost_usd"] or 0.0 for r in mrows]),
            "total_cost_usd": sum(r["cost_usd"] or 0.0 for r in mrows),
            "errors": sum(r["status"] != "ok" for r in mrows),
        }
        if mode == "agent":
            info["router_correct"] = sum(r["route"] == r["expected"] for r in mrows)
        out["modes"][mode] = info
    out["grading_cost_usd"] = sum(r["grade_cost_usd"] or 0.0 for r in rows)
    out["grading_errors"] = sum(r["verdict"] is None for r in rows)
    return out


def _counts(c: dict[str | None, int], n: int) -> str:
    """'correct a (x%) / partial b (y%) / wrong c (z%)' for one group."""
    parts = [f"{v} {c.get(v, 0)} ({c.get(v, 0) / n:.0%})" for v in VERDICTS]
    if c.get(None):
        parts.append(f"not graded {c[None]}")
    return " / ".join(parts)


def summary_markdown(summary: dict[str, Any], meta: dict[str, Any]) -> str:
    """Human-readable summary of an official run."""
    lines = [f"# Test-set results ({meta['date']})", ""]
    lines += [f"- {k}: {v}" for k, v in meta.items() if k != "date"]
    for mode, info in summary["modes"].items():
        n = info["n"]
        lines += ["", f"## {mode}", "", f"- All {n}: {_counts(info['verdicts'], n)}"]
        for route, c in info["by_route"].items():
            k = sum(c.values())
            lines.append(f"- {route} ({k}): {_counts(c, k)}")
        if "router_correct" in info:
            rc = info["router_correct"]
            lines.append(f"- Router accuracy: {rc}/{n} ({rc / n:.0%})")
        lines.append(
            f"- Mean time {info['mean_latency_ms']} ms, mean cost "
            f"${info['mean_cost_usd']:.6f}, total ${info['total_cost_usd']:.6f}, "
            f"errors {info['errors']}"
        )
    lines += [
        "",
        f"Grading cost ${summary['grading_cost_usd']:.6f} "
        f"(errors {summary['grading_errors']}).",
    ]
    return "\n".join(lines) + "\n"


def pick_human_check(
    rows: list[dict[str, Any]], n: int, seed: int
) -> list[dict[str, Any]]:
    """n rows chosen at random (fixed seed) from both modes, in a stable order."""
    pool = sorted(rows, key=lambda r: (r["id"], r["mode"]))
    return random.Random(seed).sample(pool, min(n, len(pool)))


def human_check_markdown(items: list[dict[str, Any]]) -> str:
    """Blind review sheet: question, reference, answer, empty grade box."""
    lines = [
        "# Human check",
        "",
        "Grade each answer against the reference: correct / partial / wrong. The mode",
        "(agent or RAG-only) and the LLM grade are hidden; see human_check_key.json",
        "after grading.",
    ]
    for i, r in enumerate(items, start=1):
        lines += [
            "",
            f"## {i}. {r['id']}: {r['question']}",
            "",
            f"**Reference:** {r['reference']}",
            "",
            "**Answer:**",
            "",
            *[f"> {line}" if line else ">" for line in r["text"].splitlines()],
            "",
            "**Your grade:** [ ] correct  [ ] partial  [ ] wrong",
            "",
            "**Note:**",
        ]
    return "\n".join(lines) + "\n"


def result_row(q: dict[str, str], mode: str, res: Any, grade: Any) -> dict[str, Any]:
    """One jsonl row from a question, an AgentResult and a Grade."""
    p = res.period
    return {
        "id": q["id"], "mode": mode, "question": q["question"],
        "expected": expected_route(q["expected_tool"]), "route": res.route,
        "period": f"{p.start}..{p.end}" if p and p.start else None,
        "rag_query": res.rag_query, "notes": res.notes,
        "sql_status": res.sql.status if res.sql else None,
        "sql": res.sql.sql if res.sql else None,
        "chunks": [c.chunk_id for c in res.chunks], "sources": res.sources,
        "status": res.status, "error": res.error, "text": res.text,
        "reference": q["notes"], "verdict": grade.verdict,
        "reason": grade.reason, "grade_error": grade.error,
        "grade_cost_usd": grade.cost_usd, "request_id": res.request_id,
        "latency_ms": res.latency_ms, "cost_usd": res.cost_usd,
    }  # fmt: skip


# ---------- I/O ----------


def main(argv: list[str] | None = None) -> None:
    """Run both modes on every question, grade, write results and the review sheet."""
    import argparse

    from vnmacro.agent.agent import build_agent
    from vnmacro.eval.grade import build_grader

    parser = argparse.ArgumentParser(description="Official test-set run.")
    parser.add_argument("--questions", type=Path, default=config.TEST_QUESTIONS_FILE)
    parser.add_argument("--out", type=Path, default=config.EVAL_RESULTS_DIR)
    parser.add_argument("--prefix", default="test")
    parser.add_argument("--force", action="store_true", help="overwrite results")
    args = parser.parse_args(argv)

    results_path = args.out / f"{args.prefix}_results.jsonl"
    if results_path.exists() and not args.force:
        raise SystemExit(f"{results_path} exists: the test set is run only once.")
    with open(args.questions, encoding="utf-8", newline="") as f:
        questions = list(csv.DictReader(f))

    agent, grader = build_agent(), build_grader()
    rows: list[dict[str, Any]] = []
    for q in questions:
        for mode in MODES:
            ask = agent.ask if mode == "agent" else agent.ask_rag_only
            res = ask(q["question"])
            g = grader.grade(q["question"], q["expected_tool"], q["notes"], res.text)
            rows.append(result_row(q, mode, res, g))
            print(f"{q['id']} {mode}: route={res.route} -> {g.verdict}")

    args.out.mkdir(parents=True, exist_ok=True)
    with open(results_path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")
    summary = summarize(rows)
    meta = {
        "date": time.strftime("%Y-%m-%d %H:%M"),
        "questions": str(args.questions),
        "model": grader.model,
        "router prompt": agent.router.prompt_version,
        "answer prompt": agent.answerer.prompt_version,
    }
    (args.out / f"{args.prefix}_summary.json").write_text(
        json.dumps({"meta": meta, **summary}, indent=2, default=str), encoding="utf-8"
    )
    md = summary_markdown(summary, meta)
    (args.out / f"{args.prefix}_summary.md").write_text(md, encoding="utf-8")
    picked = pick_human_check(rows, config.HUMAN_CHECK_N, config.HUMAN_CHECK_SEED)
    (args.out / "human_check.md").write_text(
        human_check_markdown(picked), encoding="utf-8"
    )
    key = [
        {"item": i, "id": r["id"], "mode": r["mode"]} for i, r in enumerate(picked, 1)
    ]
    (args.out / "human_check_key.json").write_text(
        json.dumps(key, indent=2), encoding="utf-8"
    )
    print("\n" + md)
    print(f"Saved in {args.out}")


if __name__ == "__main__":
    main()
