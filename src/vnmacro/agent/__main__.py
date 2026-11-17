"""Ask the agent one question.

PYTHONPATH=src python -m vnmacro.agent "Lạm phát tháng gần nhất là bao nhiêu?"
"""

from __future__ import annotations

import argparse

from vnmacro.agent.agent import AgentResult, build_agent


def format_result(res: AgentResult) -> str:
    """Answer text plus a short trace of the steps."""
    period = res.period
    span = f"{period.start}..{period.end}" if period and period.start else "-"
    sql = res.sql.status if res.sql else "-"
    lines = [
        res.text,
        "",
        "---",
        f"route: {res.route}   time_ref: {res.time_ref}   period: {span}",
        f"rag_query: {res.rag_query}   chunks: {len(res.chunks)}   sql: {sql}",
    ]
    if res.notes:
        lines.append(f"notes: {' | '.join(res.notes)}")
    if res.error:
        lines.append(f"error: {res.error}")
    lines.append(
        f"request_id: {res.request_id}   cost: ${res.cost_usd:.6f}   "
        f"time: {res.latency_ms} ms"
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(description="Ask the agent one question.")
    parser.add_argument("question")
    args = parser.parse_args(argv)
    print(format_result(build_agent().ask(args.question)))


if __name__ == "__main__":
    main()
