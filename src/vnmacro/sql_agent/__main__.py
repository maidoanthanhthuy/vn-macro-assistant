"""Try the Text-to-SQL pipeline on one question.

PYTHONPATH=src python -m vnmacro.sql_agent "Giá đóng cửa gần nhất của FPT?"
"""

from __future__ import annotations

import argparse

from vnmacro.sql_agent.context import format_rows
from vnmacro.sql_agent.pipeline import SQLResult, build_pipeline

PREVIEW_MAX_CHARS = 60  # cut long cell values in the printed table


def format_result(res: SQLResult, max_chars: int = PREVIEW_MAX_CHARS) -> str:
    """Human-readable report of one pipeline run."""
    lines = [f"status: {res.status}   run_id: {res.run_id}"]
    if res.sql:
        lines += ["", "SQL:", res.sql]
    if res.status == "ok":
        lines += ["", f"Result ({len(res.rows)} rows):"]
        lines.append(format_rows(res.columns, res.rows, max_chars))
    if res.notes:
        lines += ["", f"notes: {res.notes}"]
    if res.reason:
        lines.append(f"reason: {res.reason}")
    if res.error:
        lines.append(f"error: {res.error}")
    if len(res.sql_attempts) > 1 or res.status in ("blocked", "error"):
        lines += ["", "attempts:"]
        lines += [
            f"  {a['attempt']}. {a.get('stage')}: {a.get('error') or 'ok'}"
            for a in res.sql_attempts
        ]
    cost = "n/a" if res.cost_usd is None else f"${res.cost_usd:.6f}"
    lines += [
        "",
        f"LLM calls: {res.attempts}   tokens: input {res.input_tokens} "
        f"(cached {res.cached_input_tokens}), output {res.output_tokens}",
        f"cost: {cost}   time: {res.latency_ms} ms",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(description="Ask one question with Text-to-SQL.")
    parser.add_argument("question")
    args = parser.parse_args(argv)
    print(format_result(build_pipeline().answer(args.question)))


if __name__ == "__main__":
    main()
