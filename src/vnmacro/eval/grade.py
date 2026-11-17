"""LLM grader: one structured call per answer -> correct / partial / wrong + reason.

The grader sees the question, the expected tool, the reference answer (the `notes`
column of the question file) and the answer text (prompts/grade.md).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from vnmacro import config
from vnmacro.llm import LLMResponse, cost_usd
from vnmacro.sql_agent.prompt import build_messages

LLMCall = Callable[[list[dict[str, str]]], LLMResponse]

VERDICTS: tuple[str, ...] = ("correct", "partial", "wrong")
SCHEMA_NAME = "grade"
RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": list(VERDICTS)},
        "reason": {"type": "string"},
    },
    "required": ["verdict", "reason"],
    "additionalProperties": False,
}


@dataclass(frozen=True)
class Grade:
    """One grading result; verdict None when the grader call failed."""

    verdict: str | None
    reason: str
    cost_usd: float | None = None
    error: str | None = None


def grade_message(
    question: str, expected_tool: str, reference: str, answer: str
) -> str:
    """User message for the grader."""
    return (
        f"Question: {question}\n"
        f"Expected tool: {expected_tool}\n\n"
        f"Reference answer and grading notes:\n{reference}\n\n"
        f"Assistant's answer:\n{answer}"
    )


def parse_grade(content: str) -> tuple[str, str]:
    """(verdict, reason) from the JSON output; raise ValueError if it does not fit."""
    try:
        data = json.loads(content)
    except json.JSONDecodeError as e:
        raise ValueError(f"Output is not valid JSON: {e}") from e
    if not isinstance(data, dict) or set(data) != {"verdict", "reason"}:
        raise ValueError("Output does not have exactly the fields of the schema.")
    if data["verdict"] not in VERDICTS or not isinstance(data["reason"], str):
        raise ValueError("Output verdict or reason is invalid.")
    return data["verdict"], data["reason"].strip()


@dataclass
class Grader:
    """Grade answers with one LLM call each (no retry)."""

    fixed_prompt: str
    model: str
    llm: LLMCall
    prices: dict[str, dict[str, float]] = field(
        default_factory=lambda: config.LLM_PRICES_USD_PER_MTOK
    )

    def grade(
        self, question: str, expected_tool: str, reference: str, answer: str
    ) -> Grade:
        """Grade one answer; failures give verdict None with the error."""
        message = grade_message(question, expected_tool, reference, answer)
        reply: LLMResponse | None = None
        try:
            reply = self.llm(build_messages(self.fixed_prompt, message))
            if reply.refusal:
                raise ValueError(f"Model refused: {reply.refusal}")
            verdict, reason = parse_grade(reply.content)
            return Grade(verdict, reason, self._cost(reply))
        except Exception as e:  # LLM/network error or invalid output
            cost = self._cost(reply) if reply else None
            return Grade(None, "", cost, f"{type(e).__name__}: {e}")

    def _cost(self, reply: LLMResponse) -> float | None:
        """USD cost of one reply."""
        return cost_usd(
            self.model,
            reply.input_tokens,
            reply.cached_input_tokens,
            reply.output_tokens,
            self.prices,
        )


def build_grader() -> Grader:
    """Grader from .env (same provider and model as the agent)."""
    from vnmacro import llm

    model = llm.model_from_env()
    client = llm.make_client()
    fixed = config.GRADE_PROMPT_FILE.read_text(encoding="utf-8").strip() + "\n"
    return Grader(
        fixed_prompt=fixed,
        model=model,
        llm=lambda msgs: llm.chat_json(
            client, model, msgs, SCHEMA_NAME, RESPONSE_SCHEMA
        ),
    )
