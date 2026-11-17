"""Run the Text-to-SQL agent on the dev questions and compare with reference answers.

Semi-automatic grading: the key values of each reference answer (config.EVAL_SQL_KEYS)
must all appear in the agent's result (numbers within 0.1% relative or equal after
rounding to the reference's decimals; dates and strings exactly). Otherwise CHECK, for a
human to read. A non-ok agent status is reported as is.

    PYTHONPATH=src python -m vnmacro.eval.run_sql_dev

Router mode routes every dev question, resolves its period and compares the route with
expected_tool (config.EVAL_ROUTE_MAP):

    PYTHONPATH=src python -m vnmacro.eval.run_sql_dev --router

RAG mode routes and resolves each rag / sql+rag question, retrieves the top 5 chunks and
checks at document level that an answer document (config.EVAL_RAG_DOCS) is among them:

    PYTHONPATH=src python -m vnmacro.eval.run_sql_dev --rag

Agent mode asks the full agent every dev question (answers are read by a human; full
texts are also saved as <time>_agent_dev.md):

    PYTHONPATH=src python -m vnmacro.eval.run_sql_dev --agent

Each run is saved to eval/runs/<time>_sql_dev.jsonl or <time>_router_dev.jsonl
(gitignored). The agent logs to app.query_log as usual.
"""

from __future__ import annotations

import csv
import datetime as dt
import json
import re
import time
from dataclasses import asdict, dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from vnmacro import config

_HEADER_RE = re.compile(r"^--\s*(q\d+)\b")


# ---------- pure helpers ----------


def select_questions(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    """Seed questions whose expected tool includes SQL (sql, sql+rag), in file order."""
    return [r for r in rows if "sql" in r.get("expected_tool", "").split("+")]


def parse_reference_sql(text: str) -> dict[str, str]:
    """Map question id -> reference SQL from a file of '-- qNN: ...' headed blocks."""
    out: dict[str, str] = {}
    current: str | None = None
    lines: list[str] = []
    for line in text.splitlines():
        header = _HEADER_RE.match(line)
        if header:
            current, lines = header.group(1), []
            continue
        if line.lstrip().startswith("--") or (not lines and not line.strip()):
            continue
        if current is None:
            continue
        lines.append(line)
        if line.rstrip().endswith(";"):
            out[current] = "\n".join(lines).strip()
            current, lines = None, []
    return out


def key_values(
    columns: list[str], rows: list[tuple[Any, ...]], spec: tuple[tuple[str, ...], str]
) -> list[tuple[str, Any]]:
    """(column, value) pairs to look for, from the first or all reference rows."""
    names, which = spec
    picked = rows[:1] if which == "first" else rows
    idx = [columns.index(n) for n in names]
    return [(columns[i], row[i]) for row in picked for i in idx]


def _decimal(value: Any) -> Decimal | None:
    """Number as Decimal (bools and non-numbers -> None)."""
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


def values_match(ref: Any, got: Any, rel_tol: float = config.EVAL_REL_TOL) -> bool:
    """True if an agent cell equals a reference value (tolerant for numbers)."""
    ref_num, got_num = _decimal(ref), _decimal(got)
    if ref_num is not None:
        if got_num is None:
            return False
        if ref_num == got_num:
            return True
        if ref_num != 0 and abs(got_num - ref_num) / abs(ref_num) <= Decimal(
            str(rel_tol)
        ):
            return True
        exponent = ref_num.as_tuple().exponent
        if isinstance(exponent, int) and exponent < 0:  # reference was rounded
            return got_num.quantize(Decimal(1).scaleb(exponent)) == ref_num
        return False
    if isinstance(ref, dt.date):
        if isinstance(got, dt.datetime):
            got = got.date()
        if isinstance(got, dt.date):
            return got == ref
        return isinstance(got, str) and got.strip()[:10] == ref.isoformat()
    if isinstance(ref, str):
        return isinstance(got, str) and got.strip().lower() == ref.strip().lower()
    return got == ref


def find_value(ref: Any, rows: list[tuple[Any, ...]], rel_tol: float) -> Any:
    """First agent cell (also inside arrays) that matches ref, or None."""
    for row in rows:
        for cell in row:
            cells = cell if isinstance(cell, (list, tuple)) else [cell]
            for c in cells:
                if values_match(ref, c, rel_tol):
                    return c
    return None


def grade(
    status: str,
    keys: list[tuple[str, Any]],
    agent_rows: list[tuple[Any, ...]],
    has_reference: bool,
    rel_tol: float = config.EVAL_REL_TOL,
) -> tuple[str, list[Any]]:
    """Verdict (PASS, CHECK or the agent status) and the agent values found per key."""
    if status != "ok":
        return status, []
    if not has_reference:
        return "CHECK", []
    found = [find_value(v, agent_rows, rel_tol) for _, v in keys]
    ok = all(f is not None for f in found)
    return ("PASS" if ok else "CHECK"), found


def final_verdict(
    qid: str, verdict: str, phase4_ids: tuple[str, ...] = config.EVAL_PHASE4_IDS
) -> str:
    """Label hybrid questions graded in Phase 4 as 'phase 4' (non-ok status kept)."""
    if qid in phase4_ids and verdict in ("PASS", "CHECK"):
        return "phase 4"
    return verdict


def shorten(text: str, n: int) -> str:
    """Cut text to n characters with an ellipsis."""
    return text if len(text) <= n else text[: n - 1] + "…"


@dataclass
class EvalRow:
    """One question's outcome (one line of the jsonl file)."""

    id: str
    question: str
    status: str
    verdict: str
    keys: list[tuple[str, Any]] = field(default_factory=list)
    found: list[Any] = field(default_factory=list)
    seed_notes: str = ""
    agent_sql: str | None = None
    agent_columns: list[str] = field(default_factory=list)
    agent_rows: list[tuple[Any, ...]] = field(default_factory=list)
    agent_notes: str = ""
    agent_reason: str | None = None
    agent_error: str | None = None
    ref_sql: str | None = None
    ref_columns: list[str] = field(default_factory=list)
    ref_rows: list[tuple[Any, ...]] = field(default_factory=list)
    run_id: str = ""
    attempts: int = 0
    latency_ms: int = 0
    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float | None = None


def summary_table(rows: list[EvalRow], q_chars: int = 48) -> str:
    """Plain-text summary: id, question, status, verdict, agent and reference values."""
    lines = ["id | question | status | verdict | agent | reference"]
    for r in rows:
        ref = ", ".join(f"{c}={_show(v)}" for c, v in r.keys) or "-"
        got = ", ".join(_show(v) for v in r.found) if r.found else "-"
        lines.append(
            f"{r.id} | {shorten(r.question, q_chars)} | {r.status} | {r.verdict} | "
            f"{got} | {ref}"
        )
    return "\n".join(lines)


def _show(value: Any) -> str:
    """Compact text for a value in the summary."""
    if value is None:
        return "not found"
    if isinstance(value, dt.date):
        return value.isoformat()
    if isinstance(value, (float, Decimal)) and not isinstance(value, bool):
        return f"{Decimal(str(value)):.4f}".rstrip("0").rstrip(".")
    return str(value)


def expected_route(
    expected_tool: str, route_map: dict[str, str] = config.EVAL_ROUTE_MAP
) -> str | None:
    """Router route expected for a seed question's expected_tool (None if unknown)."""
    return route_map.get(expected_tool.strip())


def router_table(rows: list[dict[str, Any]], q_chars: int = 48) -> str:
    """Plain-text table: id, question, expected, route, resolved period, correct."""
    lines = ["id | question | expected | route | period | ok"]
    for r in rows:
        period = f"{r['start']}..{r['end']}" if r["start"] else "-"
        notes = f" ({'; '.join(r['notes'])})" if r["notes"] else ""
        lines.append(
            f"{r['id']} | {shorten(r['question'], q_chars)} | {r['expected']} | "
            f"{r['route'] or r['status']} | {period}{notes} | "
            f"{'yes' if r['correct'] else 'NO'}"
        )
    return "\n".join(lines)


def rag_table(rows: list[dict[str, Any]], q_chars: int = 48) -> str:
    """Plain-text table: id, question, filtered period, in top k, rank of answer doc."""
    lines = [
        "id | question | rag_query | period filter | in top 5 | doc rank | chunk rank"
    ]
    for r in rows:
        period = f"{r['start']}..{r['end']}" if r["filtered"] else "none"
        if r["notes"]:
            period += f" ({'; '.join(r['notes'])})"
        if not r["gold"]:
            hit = "n/a (no answer doc)"
        else:
            hit = "yes" if r["rank"] else "NO"
        lines.append(
            f"{r['id']} | {shorten(r['question'], q_chars)} | "
            f"{r['rag_query'] or '-'} | {period} | {hit} | "
            f"{r['rank'] or '-'} | {r['chunk_rank'] or '-'}"
        )
    return "\n".join(lines)


# ---------- I/O ----------


def _save(rows: list[dict[str, Any]], suffix: str) -> Path:
    """Write rows as jsonl to eval/runs/<time>_<suffix>.jsonl."""
    config.EVAL_RUNS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    path = Path(config.EVAL_RUNS_DIR) / f"{stamp}_{suffix}.jsonl"
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")
    return path


def main_router() -> None:
    """Route every dev question, resolve its period, compare with expected_tool."""
    from vnmacro.agent.resolver import resolve_period
    from vnmacro.agent.router import build_router

    with open(config.SEED_QUESTIONS_FILE, encoding="utf-8", newline="") as f:
        questions = list(csv.DictReader(f))
    router, cov = build_router()
    print(f"Router prompt version {router.prompt_version}, {len(questions)} questions")
    rows: list[dict[str, Any]] = []
    for q in questions:
        res = router.route(q["question"])
        d = res.decision
        period = resolve_period(d, cov) if d else None
        expected = expected_route(q["expected_tool"])
        rows.append({
            "id": q["id"], "question": q["question"], "expected": expected,
            "status": res.status, "route": d.route if d else None,
            "time_ref": d.time_ref if d else None,
            "llm_start": d.period_start if d else None,
            "llm_end": d.period_end if d else None,
            "reason": d.reason if d else None, "error": res.error,
            "start": period.start if period else None,
            "end": period.end if period else None,
            "notes": list(period.notes) if period else [],
            "correct": d is not None and d.route == expected,
            "run_id": res.run_id, "latency_ms": res.latency_ms,
            "input_tokens": res.input_tokens,
            "cached_input_tokens": res.cached_input_tokens,
            "output_tokens": res.output_tokens, "cost_usd": res.cost_usd,
        })  # fmt: skip
    path = _save(rows, "router_dev")
    costs = [r["cost_usd"] for r in rows if r["cost_usd"] is not None]
    print("\n" + router_table(rows))
    n_ok = sum(r["correct"] for r in rows)
    print(
        f"\nCorrect {n_ok}/{len(rows)} ({n_ok / len(rows):.0%})   "
        f"total cost ${sum(costs):.6f}   "
        f"mean time {sum(r['latency_ms'] for r in rows) / len(rows):.0f} ms"
    )
    print(f"Saved: {path}")


def main_rag() -> None:
    """Router -> resolver -> retrieve for every rag / sql+rag dev question."""
    from vnmacro.agent.resolver import resolve_period
    from vnmacro.agent.retrieve import first_rank, get_retriever
    from vnmacro.agent.router import build_router, search_query

    with open(config.SEED_QUESTIONS_FILE, encoding="utf-8", newline="") as f:
        questions = [
            r for r in csv.DictReader(f) if r["expected_tool"] in ("rag", "sql+rag")
        ]
    router, cov = build_router()
    t0 = time.perf_counter()
    retriever = get_retriever()
    load_s = time.perf_counter() - t0
    rows: list[dict[str, Any]] = []
    for q in questions:
        res = router.route(q["question"])
        period = resolve_period(res.decision, cov) if res.decision else None
        start = period.start if period else None
        end = period.end if period else None
        t1 = time.perf_counter()
        query = (
            search_query(res.decision, q["question"]) if res.decision else q["question"]
        )
        hits = retriever.retrieve(query, start, end)
        ms = round((time.perf_counter() - t1) * 1000)
        gold = config.EVAL_RAG_DOCS.get(q["id"], ())
        rows.append({
            "id": q["id"], "question": q["question"],
            "route": res.decision.route if res.decision else None,
            "start": start, "end": end, "filtered": hits.filtered,
            "notes": [*(period.notes if period else ()), *hits.notes],
            "rag_query": res.decision.rag_query if res.decision else None,
            "gold": list(gold), "rank": first_rank(hits.chunks, gold),
            "chunk_rank": first_rank(
                hits.chunks, config.EVAL_RAG_CHUNKS.get(q["id"], ()), "chunk_id"
            ),
            "top": [(c.chunk_id, round(c.score, 4)) for c in hits.chunks],
            "retrieve_ms": ms, "router_cost_usd": res.cost_usd,
        })  # fmt: skip
    path = _save(rows, "rag_dev")
    print("\n" + rag_table(rows))
    graded = [r for r in rows if r["gold"]]
    n_hit = sum(r["rank"] is not None for r in graded)
    mean_ms = sum(r["retrieve_ms"] for r in rows) / len(rows)
    print(
        f"\nAnswer doc in top 5: {n_hit}/{len(graded)}   model load {load_s:.1f} s   "
        f"mean retrieve time {mean_ms:.0f} ms (embed + search)"
    )
    print(f"Saved: {path}")


def answers_markdown(rows: list[dict[str, Any]]) -> str:
    """All agent answers as one Markdown document, one section per question."""
    parts = ["# Agent answers on the dev set"]
    for r in rows:
        parts.append(
            f"## {r['id']}: {r['question']}\n\n"
            f"route `{r['route']}` (expected `{r['expected']}`), period "
            f"{r['period'] or '-'}, sql `{r['sql_status'] or '-'}`, "
            f"cost ${r['cost_usd']:.6f}, {r['latency_ms']} ms\n\n{r['text']}"
        )
    return "\n\n".join(parts) + "\n"


def main_agent() -> None:
    """Ask the agent every dev question; save jsonl and a Markdown file of answers."""
    from vnmacro.agent.agent import build_agent

    with open(config.SEED_QUESTIONS_FILE, encoding="utf-8", newline="") as f:
        questions = list(csv.DictReader(f))
    agent = build_agent()
    rows: list[dict[str, Any]] = []
    for q in questions:
        res = agent.ask(q["question"])
        p = res.period
        rows.append({
            "id": q["id"], "question": q["question"],
            "expected": expected_route(q["expected_tool"]), "route": res.route,
            "period": f"{p.start}..{p.end}" if p and p.start else None,
            "rag_query": res.rag_query, "notes": res.notes,
            "sql_status": res.sql.status if res.sql else None,
            "sql": res.sql.sql if res.sql else None,
            "chunks": [c.chunk_id for c in res.chunks], "sources": res.sources,
            "status": res.status, "error": res.error, "text": res.text,
            "request_id": res.request_id, "latency_ms": res.latency_ms,
            "cost_usd": res.cost_usd,
        })  # fmt: skip
        print(f"{q['id']}: {res.status} route={res.route} {res.latency_ms} ms")
    path = _save(rows, "agent_dev")
    md = path.with_suffix(".md")
    md.write_text(answers_markdown(rows), encoding="utf-8")
    total = sum(r["cost_usd"] for r in rows)
    print(
        f"\n{len(rows)} questions   errors {sum(r['status'] != 'ok' for r in rows)}   "
        f"total cost ${total:.6f}   mean ${total / len(rows):.6f} per question   "
        f"mean time {sum(r['latency_ms'] for r in rows) / len(rows):.0f} ms"
    )
    print(f"Saved: {path}\n       {md}")


def main(argv: list[str] | None = None) -> None:
    """Run the agent and the reference SQL for every dev SQL question; save jsonl."""
    import argparse
    import os

    from dotenv import load_dotenv

    from vnmacro.sql_agent import runner
    from vnmacro.sql_agent.pipeline import build_pipeline

    parser = argparse.ArgumentParser(description="Run the dev set.")
    parser.add_argument("--router", action="store_true", help="evaluate the router")
    parser.add_argument("--rag", action="store_true", help="evaluate retrieval")
    parser.add_argument("--agent", action="store_true", help="run the full agent")
    args = parser.parse_args(argv)
    if args.agent:
        main_agent()
        return
    if args.router:
        main_router()
        return
    if args.rag:
        main_rag()
        return
    load_dotenv()
    with open(config.SEED_QUESTIONS_FILE, encoding="utf-8", newline="") as f:
        questions = select_questions(list(csv.DictReader(f)))
    refs = parse_reference_sql(config.MANUAL_CHECKS_SQL.read_text(encoding="utf-8"))
    reader_url = os.environ["DATABASE_URL_READER"]
    print(f"Questions ({len(questions)}): {', '.join(q['id'] for q in questions)}")
    missing = [q["id"] for q in questions if q["id"] not in refs]
    print(f"No reference SQL (always CHECK): {', '.join(missing) or 'none'}\n")

    agent = build_pipeline()
    results: list[EvalRow] = []
    for q in questions:
        res = agent.answer(q["question"])
        ref_sql = refs.get(q["id"])
        ref_cols: list[str] = []
        ref_rows: list[tuple[Any, ...]] = []
        keys: list[tuple[str, Any]] = []
        if ref_sql:
            ref_cols, ref_rows = runner.run_select(reader_url, ref_sql)
            spec = config.EVAL_SQL_KEYS.get(q["id"])
            keys = key_values(ref_cols, ref_rows, spec) if spec else []
        verdict, found = grade(res.status, keys, res.rows, bool(keys))
        verdict = final_verdict(q["id"], verdict)
        row = EvalRow(
            id=q["id"], question=q["question"], status=res.status, verdict=verdict,
            keys=keys, found=found, seed_notes=q.get("notes", ""),
            agent_sql=res.sql, agent_columns=res.columns, agent_rows=res.rows,
            agent_notes=res.notes, agent_reason=res.reason, agent_error=res.error,
            ref_sql=ref_sql, ref_columns=ref_cols, ref_rows=ref_rows,
            run_id=res.run_id, attempts=res.attempts, latency_ms=res.latency_ms,
            input_tokens=res.input_tokens,
            cached_input_tokens=res.cached_input_tokens,
            output_tokens=res.output_tokens, cost_usd=res.cost_usd,
        )  # fmt: skip
        results.append(row)
        note = row.seed_notes
        print(f"{row.id}: {row.status} -> {row.verdict}")
        if len(note) > config.EVAL_NOTE_MIN_CHARS:
            print(f"    note: {note}")

    path = _save([asdict(r) for r in results], "sql_dev")

    costs = [r.cost_usd for r in results if r.cost_usd is not None]
    print("\n" + summary_table(results))
    n_pass = sum(r.verdict == "PASS" for r in results)
    print(
        f"\nPASS {n_pass}/{len(results)}   total cost ${sum(costs):.6f}   "
        f"mean time {sum(r.latency_ms for r in results) / len(results):.0f} ms"
    )
    print(f"Saved: {path}")


if __name__ == "__main__":
    main()
