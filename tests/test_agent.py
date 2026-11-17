import datetime as dt
from types import SimpleNamespace

from vnmacro import config
from vnmacro.agent.agent import (
    Agent,
    RequestLog,
    period_notes,
    retrieval_log_row,
    sql_question,
)
from vnmacro.agent.resolver import DataCoverage, ResolvedPeriod
from vnmacro.agent.retrieve import RetrievalResult, RetrievedChunk
from vnmacro.agent.router import RouteDecision

D = dt.date
COV = DataCoverage(
    (D(2015, 1, 1), D(2026, 11, 10)),
    (D(2025, 10, 1), D(2026, 12, 31)),
    (D(2026, 10, 1), D(2026, 10, 31)),
)
CHUNK = RetrievedChunk("t", "l", "T", "2026-10", "u", 0.5, "d", "d_001")


class FakeRouter:
    def __init__(self, decision, log):
        self.decision, self.log = decision, log

    def route(self, question):
        self.log({"component": "router"})
        return SimpleNamespace(decision=self.decision, cost_usd=0.001, error="boom")


class FakeAnswerer:
    def __init__(self, log):
        self.calls, self.log = [], log

    def answer(self, question, route, notes, sql, chunks):
        self.calls.append((question, route, notes, sql, chunks))
        self.log({"component": "answer"})
        return SimpleNamespace(
            text="ANSWER", sources=["s"], error=None, status="ok", cost_usd=0.002
        )


def make(route, time_ref="latest", rag_query=None):
    rows = []
    log = RequestLog(sink=rows.append)
    decision = None
    if route:
        decision = RouteDecision(route, time_ref, None, None, "r", rag_query)
    calls = {"retrieve": [], "sql": []}

    def retrieve(q, s, e):
        calls["retrieve"].append((q, s, e))
        return RetrievalResult([CHUNK], True, ("rnote",))

    def text_to_sql(q):
        calls["sql"].append(q)
        return SimpleNamespace(
            status="ok", sql="SELECT 1", columns=["x"], rows=[(1,)], notes="n",
            reason=None, cost_usd=0.003,
        )  # fmt: skip

    answerer = FakeAnswerer(log)
    agent = Agent(FakeRouter(decision, log), COV, retrieve, text_to_sql, answerer, log)
    return agent, rows, calls, answerer


def test_sql_question_adds_period_and_scope_for_both_only():
    p = ResolvedPeriod(D(2026, 10, 1), D(2026, 10, 31))
    assert sql_question("Q", "sql", p) == "Q"
    text = sql_question("Q", "both", p)
    assert text.startswith("Q\n\n") and "2026-10-01 to 2026-10-31" in text
    assert "cannot_answer only if no part" in text
    assert "period" not in sql_question("Q", "both", ResolvedPeriod(None, None))


def test_period_notes():
    p = ResolvedPeriod(D(2023, 1, 1), D(2023, 12, 31), ("outside",))
    assert period_notes(p) == ["Period used: 2023-01-01 to 2023-12-31.", "outside"]
    assert period_notes(ResolvedPeriod(None, None)) == []


def test_request_log_adds_request_id():
    rows = []
    log = RequestLog(rows.append, "rid")
    log({"a": 1})
    assert rows == [{"a": 1, "request_id": "rid"}]


def test_retrieval_log_row():
    row = retrieval_log_row("Q", "rq", RetrievalResult([CHUNK], True), 12)
    assert row["component"] == config.LOG_COMPONENT_RETRIEVE
    assert row["status"] == "ok" and row["row_count"] == 1 and row["final_sql"] is None
    assert row["sql_attempts"][0]["chunks"] == [["d_001", 0.5]]


def test_both_searches_documents_first_and_passes_period_to_sql():
    agent, rows, calls, answerer = make("both", rag_query="CPI?")
    res = agent.ask("Q")
    assert calls["retrieve"] == [("CPI?", D(2026, 10, 1), D(2026, 10, 31))]
    assert "2026-10-01 to 2026-10-31" in calls["sql"][0]
    assert [r["component"] for r in rows] == ["router", "retrieve", "answer"]
    assert {r["request_id"] for r in rows} == {res.request_id}
    _, route, notes, sql, chunks = answerer.calls[0]
    assert route == "both" and chunks == [CHUNK] and sql.rows == [(1,)]
    assert notes == ["Period used: 2026-10-01 to 2026-10-31.", "rnote"]
    assert res.status == "ok" and res.text == "ANSWER"
    assert abs(res.cost_usd - 0.006) < 1e-12


def test_sql_route_skips_retrieval():
    agent, _, calls, answerer = make("sql")
    res = agent.ask("Q")
    assert calls["retrieve"] == [] and calls["sql"] == ["Q"]
    assert res.chunks == [] and answerer.calls[0][4] == []


def test_out_of_scope_goes_straight_to_answer():
    agent, _, calls, answerer = make("out_of_scope", "none")
    res = agent.ask("Q")
    assert calls == {"retrieve": [], "sql": []}
    assert answerer.calls[0][1] == "out_of_scope" and answerer.calls[0][3] is None
    assert res.status == "ok"


def test_router_failure_gives_error_text():
    agent, _, calls, answerer = make(None)
    res = agent.ask("Q")
    assert res.status == "error" and res.text == config.ANSWER_ERROR_TEXT
    assert answerer.calls == [] and res.error == "boom"


def test_each_question_gets_a_new_request_id():
    agent, rows, _, _ = make("sql")
    first, second = agent.ask("Q1"), agent.ask("Q2")
    assert first.request_id != second.request_id
