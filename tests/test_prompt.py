import json

import pytest

from vnmacro.sql_agent import prompt


def test_fixed_prompt_order_and_question_last():
    fixed = prompt.build_fixed_prompt("ROLE", "SCHEMA", "CONV", "EXAMPLES")
    assert fixed.index("ROLE") < fixed.index("SCHEMA") < fixed.index("CONV")
    assert fixed.index("CONV") < fixed.index("EXAMPLES")
    msgs = prompt.build_messages(fixed, "Câu hỏi?")
    assert msgs[0] == {"role": "system", "content": fixed}
    assert msgs[-1] == {"role": "user", "content": "Câu hỏi?"}


def test_prompt_version_stable_and_sensitive():
    a = prompt.prompt_version("abc", n_chars=12)
    assert a == prompt.prompt_version("abc", n_chars=12) and len(a) == 12
    assert a != prompt.prompt_version("abd", n_chars=12)


def test_retry_messages_keep_conversation():
    msgs = prompt.retry_messages('{"sql": "x"}', "SELECT 1", "Unknown table t.")
    assert msgs[0] == {"role": "assistant", "content": '{"sql": "x"}'}
    assert msgs[1]["role"] == "user"
    assert "SELECT 1" in msgs[1]["content"] and "Unknown table t." in msgs[1]["content"]


def _out(**kw):
    base = {"sql": "SELECT 1", "notes": "", "cannot_answer": False, "reason": None}
    return json.dumps({**base, **kw})


def test_parse_answer():
    ans = prompt.parse_answer(_out())
    assert ans == prompt.LLMAnswer("SELECT 1", "", False, None)
    ans = prompt.parse_answer(_out(sql=None, cannot_answer=True, reason="no gold"))
    assert ans.cannot_answer and ans.sql is None and ans.reason == "no gold"


@pytest.mark.parametrize(
    "content",
    ["not json", "[]", json.dumps({"sql": "x"}), _out(cannot_answer="no"),
     _out(sql=5), _out(extra=1)],
)  # fmt: skip
def test_parse_answer_rejects_bad_output(content):
    with pytest.raises(ValueError):
        prompt.parse_answer(content)


def test_response_schema_is_strict_compatible():
    s = prompt.RESPONSE_SCHEMA
    assert s["additionalProperties"] is False
    assert set(s["required"]) == set(s["properties"])
