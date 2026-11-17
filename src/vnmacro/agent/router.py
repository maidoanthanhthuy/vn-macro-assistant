"""Router: one LLM call picks the tool(s) and the time reference of a question.

The fixed prompt (prompts/router.md + data coverage read from the database) is built
once in `build_router`; each question only adds a user message (today's date + the
question), so the prefix stays the same and is cached.
Each call writes one app.query_log row (component 'router'); the decision is stored in
sql_attempts.

    PYTHONPATH=src python -m vnmacro.agent.router "Lạm phát tháng gần nhất?"
"""

from __future__ import annotations

import datetime as dt
import json
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from vnmacro import config
from vnmacro.llm import LLMResponse, cost_usd
from vnmacro.sql_agent.prompt import build_messages

LLMCall = Callable[[list[dict[str, str]]], LLMResponse]
WriteLog = Callable[[dict[str, Any]], None]

ROUTES: tuple[str, ...] = ("sql", "rag", "both", "out_of_scope")
TIME_REFS: tuple[str, ...] = ("latest", "specific", "range", "none")
RAG_ROUTES: tuple[str, ...] = ("rag", "both")  # routes that search the documents
SCHEMA_NAME = "route_decision"
RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "route": {"type": "string", "enum": list(ROUTES)},
        "time_ref": {"type": "string", "enum": list(TIME_REFS)},
        "period_start": {"type": ["string", "null"]},
        "period_end": {"type": ["string", "null"]},
        "rag_query": {"type": ["string", "null"]},
        "reason": {"type": "string"},
    },
    "required": [
        "route",
        "time_ref",
        "period_start",
        "period_end",
        "rag_query",
        "reason",
    ],
    "additionalProperties": False,
}


@dataclass(frozen=True)
class RouteDecision:
    """Parsed router output."""

    route: str
    time_ref: str
    period_start: dt.date | None
    period_end: dt.date | None
    reason: str
    rag_query: str | None = None  # document part of the question (rag/both only)


def _date(value: Any, name: str) -> dt.date | None:
    """ISO date string or None; raise ValueError otherwise."""
    if value is None:
        return None
    try:
        return dt.date.fromisoformat(value)
    except (TypeError, ValueError) as e:
        raise ValueError(f"Output field {name} is not an ISO date: {value!r}") from e


def parse_decision(content: str) -> RouteDecision:
    """Parse and validate the JSON output; raise ValueError if it does not fit."""
    try:
        data = json.loads(content)
    except json.JSONDecodeError as e:
        raise ValueError(f"Output is not valid JSON: {e}") from e
    if not isinstance(data, dict) or set(data) != set(RESPONSE_SCHEMA["required"]):
        raise ValueError("Output does not have exactly the fields of the schema.")
    if data["route"] not in ROUTES or data["time_ref"] not in TIME_REFS:
        raise ValueError("Output route or time_ref is not an allowed value.")
    if not isinstance(data["reason"], str):
        raise ValueError("Output field reason must be a string.")
    rag_query = data["rag_query"]
    if rag_query is not None and not isinstance(rag_query, str):
        raise ValueError("Output field rag_query must be a string or null.")
    if data["route"] not in RAG_ROUTES:
        rag_query = None  # only used for document search
    return RouteDecision(
        data["route"],
        data["time_ref"],
        _date(data["period_start"], "period_start"),
        _date(data["period_end"], "period_end"),
        data["reason"],
        (rag_query or "").strip() or None,
    )


def search_query(decision: RouteDecision, question: str) -> str:
    """Text for document search: the router's rag_query, else the whole question."""
    return decision.rag_query or question


def format_documents(rows: list[tuple[str, str, dt.date, dt.date]]) -> str:
    """Markdown list of documents per type: count and first .. last reference period."""
    by_type: dict[str, list[str]] = {}
    for doc_type, period, _, _ in rows:
        by_type.setdefault(doc_type, []).append(period)
    lines = ["## Documents (rag): reference periods (first .. last)"]
    for doc_type in sorted(by_type):
        periods = sorted(by_type[doc_type])
        lines.append(
            f"- {doc_type}: {periods[0]} .. {periods[-1]} ({len(periods)} documents)"
        )
    return "\n".join(lines)


def user_message(question: str, today: dt.date) -> str:
    """User message: today's date (for relative periods), then the question."""
    return f"Today: {today.isoformat()}\nQuestion: {question}"


def format_indicators(rows: list[tuple[str, str]]) -> str:
    """Markdown list of the annual and monthly indicators in the numeric tables."""
    lines = ["## Indicators in the sql tables (code: name)"]
    lines += [f"- {code}: {name}" for code, name in sorted(rows)]
    return "\n".join(lines)


def build_fixed_prompt(instructions: str, coverage_text: str, docs_text: str) -> str:
    """Fixed system prompt: instructions and examples, then the data coverage."""
    data = "# Data available\n\n" + coverage_text.strip() + "\n\n" + docs_text.strip()
    return instructions.strip() + "\n\n" + data + "\n"


@dataclass
class RouterResult:
    """Outcome of one routing call (also the content of its app.query_log row)."""

    run_id: str
    status: str  # 'ok' or 'error'
    decision: RouteDecision | None = None
    error: str | None = None
    latency_ms: int = 0
    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float | None = None


def router_log_row(
    res: RouterResult,
    question: str,
    model: str,
    prompt_version: str,
    component: str = config.LOG_COMPONENT_ROUTER,
) -> dict[str, Any]:
    """Map a router result to the columns of app.query_log."""
    step: dict[str, Any] = {"attempt": 1, "stage": res.status, "error": res.error}
    if res.decision:
        d = res.decision
        step.update(
            route=d.route,
            time_ref=d.time_ref,
            period_start=d.period_start.isoformat() if d.period_start else None,
            period_end=d.period_end.isoformat() if d.period_end else None,
            rag_query=d.rag_query,
            reason=d.reason,
        )
    return {
        "run_id": res.run_id,
        "component": component,
        "question": question,
        "model": model,
        "prompt_version": prompt_version,
        "status": res.status,
        "final_sql": None,
        "attempts": 1,
        "sql_attempts": [step],
        "error": res.error,
        "row_count": None,
        "latency_ms": res.latency_ms,
        "input_tokens": res.input_tokens,
        "cached_input_tokens": res.cached_input_tokens,
        "output_tokens": res.output_tokens,
        "cost_usd": res.cost_usd,
    }


@dataclass
class Router:
    """Route questions with one LLM call each (no retry) and log every call."""

    fixed_prompt: str
    prompt_version: str
    model: str
    llm: LLMCall
    write_log: WriteLog
    prices: dict[str, dict[str, float]] = field(
        default_factory=lambda: config.LLM_PRICES_USD_PER_MTOK
    )

    def route(self, question: str, today: dt.date | None = None) -> RouterResult:
        """Route one question (today defaults to the current date) and log it."""
        start = time.perf_counter()
        res = RouterResult(run_id=str(uuid.uuid4()), status="error")
        message = user_message(question, today or dt.date.today())
        try:
            reply = self.llm(build_messages(self.fixed_prompt, message))
            res.input_tokens = reply.input_tokens
            res.cached_input_tokens = reply.cached_input_tokens
            res.output_tokens = reply.output_tokens
            if reply.refusal:
                raise ValueError(f"Model refused: {reply.refusal}")
            res.decision, res.status = parse_decision(reply.content), "ok"
        except Exception as e:  # LLM/network error or invalid output
            res.status, res.error = "error", f"{type(e).__name__}: {e}"
        res.latency_ms = round((time.perf_counter() - start) * 1000)
        res.cost_usd = cost_usd(
            self.model,
            res.input_tokens,
            res.cached_input_tokens,
            res.output_tokens,
            self.prices,
        )
        self.write_log(router_log_row(res, question, self.model, self.prompt_version))
        return res


# ---------- I/O ----------

_INDICATORS_SQL = "SELECT indicator_code, name FROM indicators ORDER BY 1"
_DOCUMENTS_SQL = (
    "SELECT doc_type, reference_period, period_start, period_end "
    "FROM rag.documents ORDER BY doc_type, period_start"
)


def fetch_data_info(
    url: str,
) -> tuple[list[Any], list[tuple[str, str, Any, Any]], list[tuple[str, str]]]:
    """Read table coverage, rag.documents periods and indicators as the reader."""
    import psycopg

    from vnmacro.sql_agent.context import fetch_coverage

    with psycopg.connect(url) as conn:
        conn.read_only = True
        coverage = fetch_coverage(
            conn, config.SQL_CONTEXT_SCHEMA, config.ROUTER_COVERAGE
        )
        documents = [tuple(r) for r in conn.execute(_DOCUMENTS_SQL).fetchall()]
        indicators = [tuple(r) for r in conn.execute(_INDICATORS_SQL).fetchall()]
    return coverage, documents, indicators


def build_router() -> tuple[Router, Any]:
    """Build the router and the data coverage (for the resolver) from .env + DB."""
    import os

    from dotenv import load_dotenv

    from vnmacro import llm
    from vnmacro.agent.resolver import data_coverage
    from vnmacro.sql_agent import runner
    from vnmacro.sql_agent.context import format_coverage
    from vnmacro.sql_agent.prompt import prompt_version

    load_dotenv()
    reader_url = os.environ.get("DATABASE_URL_READER")
    logger_url = os.environ.get("DATABASE_URL_LOGGER")
    if not reader_url or not logger_url:
        raise SystemExit("DATABASE_URL_READER and DATABASE_URL_LOGGER must be set")
    coverage, documents, indicators = fetch_data_info(reader_url)
    fixed = build_fixed_prompt(
        config.ROUTER_PROMPT_FILE.read_text(encoding="utf-8"),
        format_coverage(sorted(coverage, key=lambda c: c.table))
        + "\n\n"
        + format_indicators(indicators),
        format_documents(documents),
    )
    model = llm.model_from_env()
    client = llm.make_client()
    router = Router(
        fixed_prompt=fixed,
        prompt_version=prompt_version(fixed),
        model=model,
        llm=lambda msgs: llm.chat_json(
            client, model, msgs, SCHEMA_NAME, RESPONSE_SCHEMA
        ),
        write_log=lambda row: runner.write_log(logger_url, row),
    )
    return router, data_coverage(coverage, documents)


def main(argv: list[str] | None = None) -> None:
    """Route one question and print the decision and the resolved period."""
    import argparse

    from vnmacro.agent.resolver import resolve_period

    parser = argparse.ArgumentParser(description="Route one question.")
    parser.add_argument("question")
    parser.add_argument("--show-prompt", action="store_true")
    args = parser.parse_args(argv)
    router, cov = build_router()
    if args.show_prompt:
        print(router.fixed_prompt + "\n---")
    res = router.route(args.question)
    print(f"status: {res.status}   run_id: {res.run_id}   cost: {res.cost_usd}")
    if res.decision:
        print(res.decision)
        print(resolve_period(res.decision, cov))
    if res.error:
        print(f"error: {res.error}")


if __name__ == "__main__":
    main()
