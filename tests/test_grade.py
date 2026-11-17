import json

import pytest

from vnmacro.eval.grade import Grader, grade_message, parse_grade
from vnmacro.llm import LLMResponse

PRICES = {"m": {"input": 0.10, "cached_input": 0.01, "output": 0.50}}


def test_grade_message():
    msg = grade_message("Q?", "sql", "Ref 4.65%", "Đáp án 4,65%")
    assert msg.startswith("Question: Q?\nExpected tool: sql\n\n")
    assert "Reference answer and grading notes:\nRef 4.65%" in msg
    assert msg.endswith("Assistant's answer:\nĐáp án 4,65%")


def test_parse_grade():
    assert parse_grade('{"verdict": "partial", "reason": " r "}') == ("partial", "r")


@pytest.mark.parametrize(
    "content",
    ["x", '{"verdict": "ok", "reason": "r"}', '{"verdict": "correct"}',
     '{"verdict": "correct", "reason": 1}'],
)  # fmt: skip
def test_parse_grade_rejects(content):
    with pytest.raises(ValueError):
        parse_grade(content)


def test_grader_ok_and_failures():
    good = LLMResponse(json.dumps({"verdict": "correct", "reason": "r"}), 100, 0, 10)
    g = Grader("FIXED", "m", lambda msgs: good, prices=PRICES).grade(
        "Q", "sql", "R", "A"
    )
    assert (g.verdict, g.reason, g.error) == ("correct", "r", None)
    assert g.cost_usd == pytest.approx((100 * 0.10 + 10 * 0.50) / 1e6)

    bad = Grader("F", "m", lambda msgs: LLMResponse("{}", 5, 0, 1), prices=PRICES)
    g = bad.grade("Q", "sql", "R", "A")
    assert g.verdict is None and "ValueError" in g.error and g.cost_usd is not None

    def boom(msgs):
        raise RuntimeError("down")

    g = Grader("F", "m", boom, prices=PRICES).grade("Q", "sql", "R", "A")
    assert g.verdict is None and "RuntimeError" in g.error and g.cost_usd is None
