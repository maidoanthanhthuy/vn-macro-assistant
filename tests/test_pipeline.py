import json
import uuid

from vnmacro.llm import LLMResponse
from vnmacro.sql_agent.pipeline import TextToSQL, log_row
from vnmacro.sql_agent.runner import QueryError

PRICES = {"m": {"input": 0.10, "cached_input": 0.01, "output": 0.50}}
GOOD_SQL = "SELECT close FROM daily_prices LIMIT 1"


def reply(sql=None, cannot=False, reason=None, notes="n", tokens=(100, 80, 10)):
    content = json.dumps(
        {"sql": sql, "notes": notes, "cannot_answer": cannot, "reason": reason}
    )
    return LLMResponse(content, *tokens)


class FakeLLM:
    def __init__(self, replies):
        self.replies, self.calls = list(replies), []

    def __call__(self, messages):
        self.calls.append([dict(m) for m in messages])
        return self.replies.pop(0)


def make(replies, run_sql=None, write_log=None):
    logs = []
    llm = FakeLLM(replies)
    pipe = TextToSQL(
        fixed_prompt="FIXED",
        prompt_version="v1",
        model="m",
        allowed_tables=("daily_prices",),
        llm=llm,
        run_sql=run_sql or (lambda q: (["close"], [(1,)])),
        write_log=write_log or logs.append,
        prices=PRICES,
    )
    return pipe, llm, logs


def test_ok_first_try():
    pipe, llm, logs = make([reply(GOOD_SQL)])
    res = pipe.answer("q")
    assert res.status == "ok" and res.attempts == 1
    assert res.sql == GOOD_SQL and res.rows == [(1,)] and res.columns == ["close"]
    assert uuid.UUID(res.run_id).version == 4
    assert logs[0]["run_id"] == res.run_id and logs[0]["row_count"] == 1
    assert llm.calls[0][-1] == {"role": "user", "content": "q"}


def test_blocked_then_fixed_uses_same_conversation():
    pipe, llm, logs = make([reply("SELECT * FROM rag.chunks"), reply(GOOD_SQL)])
    res = pipe.answer("q")
    assert res.status == "ok" and res.attempts == 2
    second = llm.calls[1]
    assert second[:2] == llm.calls[0]  # same system + question, then feedback
    assert second[2]["role"] == "assistant" and second[3]["role"] == "user"
    assert "rag" in second[3]["content"]
    stages = [a["stage"] for a in res.sql_attempts]
    assert stages == ["check", "ok"]
    # tokens summed over both calls
    assert (res.input_tokens, res.cached_input_tokens, res.output_tokens) == (
        200, 160, 20)  # fmt: skip


def test_blocked_twice_gives_blocked():
    pipe, llm, logs = make([reply("DELETE FROM daily_prices")] * 2)
    res = pipe.answer("q")
    assert res.status == "blocked" and res.attempts == 2 and res.error
    assert logs[0]["status"] == "blocked" and logs[0]["row_count"] is None


def test_database_error_twice_gives_error():
    def failing(q):
        raise QueryError("UndefinedColumn [42703]: column x does not exist")

    pipe, llm, logs = make([reply(GOOD_SQL)] * 2, run_sql=failing)
    res = pipe.answer("q")
    assert res.status == "error" and res.attempts == 2
    assert "42703" in llm.calls[1][-1]["content"]
    assert [a["stage"] for a in res.sql_attempts] == ["database", "database"]


def test_cannot_answer_is_not_retried():
    pipe, llm, logs = make([reply(None, cannot=True, reason="no gold data")])
    res = pipe.answer("Giá vàng?")
    assert res.status == "cannot_answer" and res.attempts == 1
    assert res.reason == "no gold data" and res.sql is None
    assert len(llm.calls) == 1


def test_limit_note_and_cost():
    pipe, llm, logs = make([reply("SELECT close FROM daily_prices", notes="FPT")])
    res = pipe.answer("q")
    assert res.sql.endswith("LIMIT 200") and "LIMIT was missing" in res.notes
    expected = (20 * 0.10 + 80 * 0.01 + 10 * 0.50) / 1_000_000
    assert abs(res.cost_usd - expected) < 1e-12
    assert logs[0]["cost_usd"] == res.cost_usd


def test_llm_exception_gives_error_and_is_logged():
    def boom(messages):
        raise TimeoutError("timed out")

    pipe, _, logs = make([])
    pipe.llm = boom
    res = pipe.answer("q")
    assert res.status == "error" and "timed out" in res.error
    assert logs[0]["status"] == "error"


def test_invalid_output_retried_then_ok():
    bad = LLMResponse("not json", 10, 0, 1)
    pipe, llm, _ = make([bad, reply(GOOD_SQL)])
    res = pipe.answer("q")
    assert res.status == "ok" and res.attempts == 2


def test_log_row_has_all_columns():
    from vnmacro.sql_agent.runner import LOG_COLUMNS

    pipe, _, logs = make([reply(GOOD_SQL)])
    res = pipe.answer("q")
    row = log_row(res, "q", "m", "v1")
    assert set(row) | {"request_id"} == set(LOG_COLUMNS)  # request_id: agent only
