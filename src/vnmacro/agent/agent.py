"""The agent: router -> period resolver -> RAG and/or Text-to-SQL -> answer.

For `both`, documents are searched first and the resolved period (e.g. the newest NSO
report's month) is passed to Text-to-SQL with the question. Every step writes one
app.query_log row; all rows of one question share its request_id (and the app's
anonymous session_id, if given).

    PYTHONPATH=src python -m vnmacro.agent "Lạm phát tháng gần nhất là bao nhiêu?"
"""

from __future__ import annotations

import datetime as dt
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from vnmacro import config
from vnmacro.agent.answer import Answerer, SQLData
from vnmacro.agent.resolver import DataCoverage, ResolvedPeriod, resolve_period
from vnmacro.agent.retrieve import RetrievalResult, RetrievedChunk
from vnmacro.agent.router import RAG_ROUTES, Router, search_query

RetrieveFn = Callable[[str, dt.date | None, dt.date | None], RetrievalResult]
TextToSQLFn = Callable[[str], Any]  # returns a sql_agent.pipeline.SQLResult
WriteLog = Callable[[dict[str, Any]], None]
OnStep = Callable[[str], None]  # called with "route", "retrieve", "sql", "answer"
STEPS: tuple[str, ...] = ("route", "retrieve", "sql", "answer")
SQL_ROUTES: tuple[str, ...] = ("sql", "both")


class RequestLog:
    """Log writer shared by all steps: adds the request and session ids to every row.

    The ids are thread-local: one cached agent serves every Streamlit session, each in
    its own thread, so concurrent questions must not see each other's ids.
    """

    def __init__(
        self,
        sink: WriteLog,
        request_id: str | None = None,
        session_id: str | None = None,
    ) -> None:
        self.sink = sink
        self._ids = threading.local()
        self.request_id, self.session_id = request_id, session_id

    @property
    def request_id(self) -> str | None:
        """Id of the question being answered in this thread."""
        return getattr(self._ids, "request_id", None)

    @request_id.setter
    def request_id(self, value: str | None) -> None:
        self._ids.request_id = value

    @property
    def session_id(self) -> str | None:
        """Anonymous app session id (random uuid) of this thread's question."""
        return getattr(self._ids, "session_id", None)

    @session_id.setter
    def session_id(self, value: str | None) -> None:
        self._ids.session_id = value

    def __call__(self, row: dict[str, Any]) -> None:
        """Forward one row with the request and session ids."""
        self.sink({**row, "request_id": self.request_id, "session_id": self.session_id})


@dataclass
class AgentResult:
    """Everything about one question: the answer text and what produced it."""

    request_id: str
    question: str
    text: str
    status: str  # 'ok' or 'error'
    route: str | None = None
    time_ref: str | None = None
    rag_query: str | None = None
    period: ResolvedPeriod | None = None
    notes: list[str] = field(default_factory=list)
    sql: SQLData | None = None
    chunks: list[RetrievedChunk] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    latency_ms: int = 0
    cost_usd: float = 0.0
    error: str | None = None


def sql_question(
    question: str, route: str, period: ResolvedPeriod, today: dt.date
) -> str:
    """Question for Text-to-SQL with today's date; for `both`, the period and a hint."""
    lines = [question, "", f"Today's date: {today.isoformat()}."]
    if route != "both":
        return "\n".join(lines)
    if period.start is not None:
        lines.append(
            f"Use this period (resolved from the latest documents): "
            f"{period.start} to {period.end}."
        )
    lines.append(
        "Documents answer the other parts of this question. Write SQL for the parts "
        "the database can answer; set cannot_answer only if no part can be answered."
    )
    return "\n".join(lines)


def period_notes(period: ResolvedPeriod) -> list[str]:
    """Notes for the answer step: the period used, then the resolver's notes."""
    used = [f"Period used: {period.start} to {period.end}."] if period.start else []
    return used + list(period.notes)


def retrieval_log_row(
    question: str,
    query: str,
    res: RetrievalResult,
    latency_ms: int,
    component: str = config.LOG_COMPONENT_RETRIEVE,
) -> dict[str, Any]:
    """app.query_log row for one document search (API embedding cost, if any)."""
    step = {
        "attempt": 1, "stage": "ok", "error": None, "query": query,
        "filtered": res.filtered, "notes": list(res.notes),
        "chunks": [[c.chunk_id, round(c.score, 4)] for c in res.chunks],
    }  # fmt: skip
    return {
        "run_id": str(uuid.uuid4()), "component": component, "question": question,
        "model": res.model, "prompt_version": None, "status": "ok",
        "final_sql": None, "attempts": 0, "sql_attempts": [step], "error": None,
        "row_count": len(res.chunks), "latency_ms": latency_ms,
        "input_tokens": res.tokens, "cached_input_tokens": 0, "output_tokens": 0,
        "cost_usd": res.cost_usd,
    }  # fmt: skip


@dataclass
class Agent:
    """Answer one question end to end."""

    router: Router
    coverage: DataCoverage
    retrieve: RetrieveFn
    text_to_sql: TextToSQLFn
    answerer: Answerer
    log: RequestLog

    def ask(
        self,
        question: str,
        today: dt.date | None = None,
        on_step: OnStep | None = None,
        session_id: str | None = None,
    ) -> AgentResult:
        """Route, resolve the period, gather data, write the answer.

        on_step, if given, is called with each step name (STEPS) before that step runs,
        so a UI can show progress. session_id (anonymous app session) goes to the log.
        """
        start = time.perf_counter()
        self.log.request_id = str(uuid.uuid4())
        self.log.session_id = session_id
        res = AgentResult(self.log.request_id, question, "", "error")
        costs: list[float | None] = []
        try:
            self._run(
                question, res, costs, today or dt.date.today(), on_step or _no_step
            )
        except Exception as e:  # unexpected failure in a step
            res.status, res.error = "error", f"{type(e).__name__}: {e}"
            res.text = config.ANSWER_ERROR_TEXT
        res.cost_usd = sum(c for c in costs if c is not None)
        res.latency_ms = round((time.perf_counter() - start) * 1000)
        return res

    def ask_rag_only(self, question: str) -> AgentResult:
        """Baseline: search all documents (no router, no period filter, no SQL)."""
        start = time.perf_counter()
        self.log.request_id = str(uuid.uuid4())
        self.log.session_id = None
        res = AgentResult(self.log.request_id, question, "", "error", route="rag_only")
        costs: list[float | None] = []
        try:
            t0 = time.perf_counter()
            hits = self.retrieve(question, None, None)
            ms = round((time.perf_counter() - t0) * 1000)
            self.log(retrieval_log_row(question, question, hits, ms))
            costs.append(hits.cost_usd)
            res.chunks, res.notes = hits.chunks, list(hits.notes)
            ans = self.answerer.answer(question, "rag", res.notes, None, res.chunks)
            costs.append(ans.cost_usd)
            res.text, res.sources, res.error = ans.text, ans.sources, ans.error
            res.status = ans.status
        except Exception as e:  # unexpected failure in a step
            res.status, res.error = "error", f"{type(e).__name__}: {e}"
            res.text = config.ANSWER_ERROR_TEXT
        res.cost_usd = sum(c for c in costs if c is not None)
        res.latency_ms = round((time.perf_counter() - start) * 1000)
        return res

    def _run(
        self,
        question: str,
        res: AgentResult,
        costs: list[float | None],
        today: dt.date,
        on_step: OnStep,
    ) -> None:
        """The steps of `ask`, filling res in place."""
        on_step("route")
        routed = self.router.route(question, today)
        costs.append(routed.cost_usd)
        d = routed.decision
        if d is None:
            res.error, res.text = routed.error, config.ANSWER_ERROR_TEXT
            return
        res.route, res.time_ref, res.rag_query = d.route, d.time_ref, d.rag_query
        res.period = resolve_period(d, self.coverage)
        res.notes = period_notes(res.period)

        if d.route in RAG_ROUTES:
            on_step("retrieve")
            query = search_query(d, question)
            t0 = time.perf_counter()
            hits = self.retrieve(query, res.period.start, res.period.end)
            ms = round((time.perf_counter() - t0) * 1000)
            self.log(retrieval_log_row(question, query, hits, ms))
            costs.append(hits.cost_usd)
            res.chunks, res.notes = hits.chunks, res.notes + list(hits.notes)
        if d.route in SQL_ROUTES:
            on_step("sql")
            s = self.text_to_sql(sql_question(question, d.route, res.period, today))
            costs.append(s.cost_usd)
            res.sql = SQLData(s.status, s.sql, s.columns, s.rows, s.notes, s.reason)

        on_step("answer")
        ans = self.answerer.answer(question, d.route, res.notes, res.sql, res.chunks)
        costs.append(ans.cost_usd)
        res.text, res.sources, res.error = ans.text, ans.sources, ans.error
        res.status = ans.status


def _no_step(step: str) -> None:
    """Default on_step: do nothing."""


# ---------- I/O ----------


def build_agent() -> Agent:
    """Build all steps from .env and the database (model and prompts loaded once)."""
    import os

    from dotenv import load_dotenv

    from vnmacro import llm
    from vnmacro.agent.answer import RESPONSE_SCHEMA, SCHEMA_NAME
    from vnmacro.agent.retrieve import get_retriever
    from vnmacro.agent.router import build_router
    from vnmacro.agent.scope import answer_prompt, fetch_scope, format_scope
    from vnmacro.sql_agent import runner
    from vnmacro.sql_agent.pipeline import build_pipeline
    from vnmacro.sql_agent.prompt import prompt_version

    load_dotenv()
    logger_url = os.environ.get("DATABASE_URL_LOGGER")
    reader_url = os.environ.get("DATABASE_URL_READER")
    if not logger_url or not reader_url:
        raise SystemExit("DATABASE_URL_LOGGER and DATABASE_URL_READER must be set")
    log = RequestLog(sink=lambda row: runner.write_log(logger_url, row))
    router, coverage = build_router()
    pipe = build_pipeline()
    router.write_log = pipe.write_log = log
    retriever = get_retriever()
    model = llm.model_from_env()
    client = llm.make_client()
    scope_text = format_scope(fetch_scope(reader_url))
    fixed = answer_prompt(
        config.ANSWER_PROMPT_FILE.read_text(encoding="utf-8"), scope_text
    )
    answerer = Answerer(
        fixed_prompt=fixed,
        prompt_version=prompt_version(fixed),
        model=model,
        llm=lambda msgs: llm.chat_json(
            client, model, msgs, SCHEMA_NAME, RESPONSE_SCHEMA
        ),
        write_log=log,
        scope_text=scope_text,
    )
    return Agent(
        router=router,
        coverage=coverage,
        retrieve=lambda q, s, e: retriever.retrieve(q, s, e),
        text_to_sql=pipe.answer,
        answerer=answerer,
        log=log,
    )
