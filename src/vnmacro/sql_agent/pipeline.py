"""Text-to-SQL pipeline: question -> LLM -> safety check -> read-only query -> log.

The fixed prompt (role, schema context, conventions, examples) is built once in
`build_pipeline`; each question only adds a user message. The LLM, database and log
writer are passed in as functions, so the flow is tested without network or database.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from vnmacro import config
from vnmacro.llm import LLMResponse, cost_usd
from vnmacro.sql_agent.guard import check_sql
from vnmacro.sql_agent.prompt import (
    build_messages,
    parse_answer,
    retry_messages,
)
from vnmacro.sql_agent.runner import QueryError

LLMCall = Callable[[list[dict[str, str]]], LLMResponse]
RunSQL = Callable[[str], tuple[list[str], list[tuple[Any, ...]]]]
WriteLog = Callable[[dict[str, Any]], None]


@dataclass
class SQLResult:
    """Outcome of one question (also the content of its app.query_log row)."""

    run_id: str
    status: str  # 'ok', 'cannot_answer', 'blocked', 'error'
    sql: str | None = None
    columns: list[str] = field(default_factory=list)
    rows: list[tuple[Any, ...]] = field(default_factory=list)
    notes: str = ""
    reason: str | None = None
    error: str | None = None
    attempts: int = 0
    latency_ms: int = 0
    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float | None = None
    sql_attempts: list[dict[str, Any]] = field(default_factory=list)


def log_row(
    result: SQLResult,
    question: str,
    model: str,
    prompt_version: str,
    component: str = config.LOG_COMPONENT_TEXT_TO_SQL,
) -> dict[str, Any]:
    """Map a result to the columns of app.query_log."""
    return {
        "run_id": result.run_id,
        "component": component,
        "question": question,
        "model": model,
        "prompt_version": prompt_version,
        "status": result.status,
        "final_sql": result.sql,
        "attempts": result.attempts,
        "sql_attempts": result.sql_attempts,
        "error": result.error,
        "row_count": len(result.rows) if result.status == "ok" else None,
        "latency_ms": result.latency_ms,
        "input_tokens": result.input_tokens,
        "cached_input_tokens": result.cached_input_tokens,
        "output_tokens": result.output_tokens,
        "cost_usd": result.cost_usd,
    }


@dataclass
class TextToSQL:
    """Answer questions with SQL; one LLM retry when the SQL is blocked or fails."""

    fixed_prompt: str
    prompt_version: str
    model: str
    allowed_tables: tuple[str, ...]
    llm: LLMCall
    run_sql: RunSQL
    write_log: WriteLog
    max_calls: int = config.SQL_MAX_LLM_CALLS
    max_rows: int = config.SQL_MAX_ROWS
    prices: dict[str, dict[str, float]] = field(
        default_factory=lambda: config.LLM_PRICES_USD_PER_MTOK
    )

    def answer(self, question: str) -> SQLResult:
        """Run the whole pipeline for one question and log it."""
        start = time.perf_counter()
        res = SQLResult(run_id=str(uuid.uuid4()), status="error")
        try:
            self._run(question, res)
        except Exception as e:  # LLM/network or unexpected failure
            res.status, res.error = "error", f"{type(e).__name__}: {e}"
        res.latency_ms = round((time.perf_counter() - start) * 1000)
        res.cost_usd = cost_usd(
            self.model,
            res.input_tokens,
            res.cached_input_tokens,
            res.output_tokens,
            self.prices,
        )
        self.write_log(log_row(res, question, self.model, self.prompt_version))
        return res

    def _run(self, question: str, res: SQLResult) -> None:
        """Call the LLM, check and run its SQL; retry once with the error."""
        messages = build_messages(self.fixed_prompt, question)
        for _ in range(self.max_calls):
            reply = self.llm(messages)
            res.attempts += 1
            res.input_tokens += reply.input_tokens
            res.cached_input_tokens += reply.cached_input_tokens
            res.output_tokens += reply.output_tokens
            step: dict[str, Any] = {"attempt": res.attempts, "sql": None}
            res.sql_attempts.append(step)

            if reply.refusal:
                step.update(stage="output", error=f"Model refused: {reply.refusal}")
                res.status, res.error = "error", step["error"]
                return  # a refusal is not fixed by a retry
            try:
                ans = parse_answer(reply.content)
            except ValueError as e:
                step.update(stage="output", error=str(e))
                res.status, res.error = "error", str(e)
                messages += retry_messages(reply.content, None, str(e))
                continue
            res.notes, res.reason, step["sql"] = ans.notes, ans.reason, ans.sql
            if ans.cannot_answer:
                step.update(stage="cannot_answer", error=None)
                res.status, res.sql, res.error = "cannot_answer", None, None
                return
            if not ans.sql:
                err = "cannot_answer is false but sql is null."
                step.update(stage="output", error=err)
                res.status, res.error = "error", err
                messages += retry_messages(reply.content, None, err)
                continue

            check = check_sql(ans.sql, self.allowed_tables, self.max_rows)
            if not check.ok:
                step.update(stage="check", error=check.error)
                res.status, res.error = "blocked", check.error
                messages += retry_messages(reply.content, ans.sql, check.error or "")
                continue
            step["sql"] = check.sql
            try:
                columns, rows = self.run_sql(check.sql or "")
            except QueryError as e:
                step.update(stage="database", error=str(e))
                res.status, res.error = "error", str(e)
                messages += retry_messages(reply.content, check.sql, str(e))
                continue
            step.update(stage="ok", error=None, notes=list(check.notes))
            res.status, res.error, res.sql = "ok", None, check.sql
            res.columns, res.rows = columns, rows
            res.notes = " ".join([ans.notes, *check.notes]).strip()
            return


def build_pipeline() -> TextToSQL:
    """Build the pipeline from .env and the database (fixed prompt made once here)."""
    import os

    from dotenv import load_dotenv

    from vnmacro import llm
    from vnmacro.sql_agent import runner
    from vnmacro.sql_agent.context import build_schema_context, fetch_schema
    from vnmacro.sql_agent.conventions import load_sql_conventions
    from vnmacro.sql_agent.examples import load_sql_examples
    from vnmacro.sql_agent.prompt import (
        RESPONSE_SCHEMA,
        SCHEMA_NAME,
        build_fixed_prompt,
        prompt_version,
    )

    load_dotenv()
    reader_url = os.environ.get("DATABASE_URL_READER")
    logger_url = os.environ.get("DATABASE_URL_LOGGER")
    if not reader_url or not logger_url:
        raise SystemExit("DATABASE_URL_READER and DATABASE_URL_LOGGER must be set")
    tables, coverage = fetch_schema(reader_url)
    fixed = build_fixed_prompt(
        config.SQL_ROLE_FILE.read_text(encoding="utf-8"),
        build_schema_context(config.SQL_CONTEXT_SCHEMA, tables, coverage),
        load_sql_conventions(),
        load_sql_examples(),
    )
    model = llm.model_from_env()
    client = llm.make_client()
    return TextToSQL(
        fixed_prompt=fixed,
        prompt_version=prompt_version(fixed),
        model=model,
        allowed_tables=tuple(t.name for t in tables),
        llm=lambda msgs: llm.chat_json(
            client, model, msgs, SCHEMA_NAME, RESPONSE_SCHEMA
        ),
        run_sql=lambda q: runner.run_select(reader_url, q),
        write_log=lambda row: runner.write_log(logger_url, row),
    )
