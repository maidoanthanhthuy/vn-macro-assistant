"""Run the Text-to-SQL agent on the dev questions and compare with reference answers.

Semi-automatic grading: the key values of each reference answer (config.EVAL_SQL_KEYS)
must all appear in the agent's result (numbers within 0.1% relative or equal after
rounding to the reference's decimals; dates and strings exactly). Otherwise CHECK, for a
human to read. A non-ok agent status is reported as is.

    PYTHONPATH=src python -m vnmacro.eval.run_sql_dev

Each run is saved to eval/runs/<time>_sql_dev.jsonl (gitignored). The agent logs to
app.query_log as usual.
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


# ---------- I/O ----------


def main() -> None:
    """Run the agent and the reference SQL for every dev SQL question; save jsonl."""
    import os

    from dotenv import load_dotenv

    from vnmacro.sql_agent import runner
    from vnmacro.sql_agent.pipeline import build_pipeline

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

    config.EVAL_RUNS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    path = Path(config.EVAL_RUNS_DIR) / f"{stamp}_sql_dev.jsonl"
    with open(path, "w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(asdict(r), ensure_ascii=False, default=str) + "\n")

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
