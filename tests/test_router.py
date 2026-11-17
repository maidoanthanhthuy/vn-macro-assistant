import datetime as dt
import json
import uuid

import pytest

from vnmacro.agent.router import (
    Router,
    build_fixed_prompt,
    format_documents,
    parse_decision,
    router_log_row,
    user_message,
)
from vnmacro.llm import LLMResponse
from vnmacro.sql_agent.runner import LOG_COLUMNS

PRICES = {"m": {"input": 0.10, "cached_input": 0.01, "output": 0.50}}


def output(**kw):
    data = {
        "route": "rag",
        "time_ref": "specific",
        "period_start": "2026-06-01",
        "period_end": "2026-06-30",
        "reason": "r",
    }
    return json.dumps({**data, **kw})


def make(replies):
    logs, calls = [], []

    def llm(messages):
        calls.append(messages)
        reply = replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    router = Router("FIXED", "v1", "m", llm, logs.append, prices=PRICES)
    return router, calls, logs


def test_parse_decision_ok():
    d = parse_decision(output())
    assert (d.route, d.time_ref) == ("rag", "specific")
    assert d.period_start == dt.date(2026, 6, 1)
    assert d.period_end == dt.date(2026, 6, 30)
    d = parse_decision(output(time_ref="latest", period_start=None, period_end=None))
    assert d.period_start is None and d.period_end is None


@pytest.mark.parametrize(
    "content",
    [
        "not json",
        output(route="web"),
        output(time_ref="soon"),
        output(period_start="06/2026"),
        json.dumps({"route": "rag"}),
        output(extra=1),
        output(reason=None),
    ],
)
def test_parse_decision_rejects(content):
    with pytest.raises(ValueError):
        parse_decision(content)


def test_format_documents_and_prompt():
    rows = [
        ("nso_monthly_report", "2026-09", None, None),
        ("nso_monthly_report", "2026-10", None, None),
        ("sbv_directive", "2026", None, None),
    ]
    text = format_documents(rows)
    assert "- nso_monthly_report: 2026-09 .. 2026-10 (2 documents)" in text
    assert "- sbv_directive: 2026 .. 2026 (1 documents)" in text
    prompt = build_fixed_prompt("INSTR\n", "COV", text)
    assert prompt.startswith("INSTR\n\n# Data available")
    assert prompt.index("COV") < prompt.index("sbv_directive")


def test_route_ok_logs_decision():
    router, calls, logs = make([LLMResponse(output(), 100, 80, 10)])
    res = router.route("q", today=dt.date(2026, 11, 17))
    assert res.status == "ok" and res.decision.route == "rag"
    assert uuid.UUID(res.run_id).version == 4
    assert calls[0][0] == {"role": "system", "content": "FIXED"}  # date not in prefix
    assert calls[0][-1] == {"role": "user", "content": "Today: 2026-11-17\nQuestion: q"}
    assert res.cost_usd == pytest.approx((20 * 0.10 + 80 * 0.01 + 10 * 0.50) / 1e6)
    row = logs[0]
    assert set(row) == set(LOG_COLUMNS) and row["question"] == "q"
    assert row["component"] == "router" and row["final_sql"] is None
    step = row["sql_attempts"][0]
    assert step["route"] == "rag" and step["period_start"] == "2026-06-01"
    json.dumps(row["sql_attempts"])  # must be JSON-serialisable


def test_route_invalid_output_or_exception_is_error_and_logged():
    router, calls, logs = make([LLMResponse("{}", 5, 0, 1), RuntimeError("down")])
    bad = router.route("q1")
    assert bad.status == "error" and "ValueError" in bad.error
    assert bad.decision is None and bad.input_tokens == 5
    down = router.route("q2")
    assert down.status == "error" and "RuntimeError" in down.error
    assert len(calls) == 2  # no retry
    assert [r["status"] for r in logs] == ["error", "error"]
    assert all(r["error"] for r in logs)


def test_route_refusal_is_error():
    router, _, _ = make([LLMResponse("", 5, 0, 1, refusal="no")])
    assert router.route("q").status == "error"


def test_log_row_without_decision():
    from vnmacro.agent.router import RouterResult

    row = router_log_row(RouterResult("id", "error", error="e"), "q", "m", "v")
    assert row["sql_attempts"] == [{"attempt": 1, "stage": "error", "error": "e"}]


def test_user_message():
    msg = user_message("Năm ngoái?", dt.date(2026, 1, 5))
    assert msg == "Today: 2026-01-05\nQuestion: Năm ngoái?"
