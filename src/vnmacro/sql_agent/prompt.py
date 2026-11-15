"""Prompt assembly for Text-to-SQL: fixed prefix first (cacheable), question last."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from vnmacro import config

SCHEMA_NAME = "sql_answer"
RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "sql": {"type": ["string", "null"]},
        "notes": {"type": "string"},
        "cannot_answer": {"type": "boolean"},
        "reason": {"type": ["string", "null"]},
    },
    "required": ["sql", "notes", "cannot_answer", "reason"],
    "additionalProperties": False,
}


@dataclass(frozen=True)
class LLMAnswer:
    """Parsed structured output of the LLM."""

    sql: str | None
    notes: str
    cannot_answer: bool
    reason: str | None


def build_fixed_prompt(
    role: str, schema_context: str, conventions: str, examples: str
) -> str:
    """Fixed system prompt: role, database description, conventions, examples."""
    parts = [role, schema_context, conventions, examples]
    return "\n\n".join(p.strip() for p in parts) + "\n"


def prompt_version(
    fixed_prompt: str, n_chars: int = config.PROMPT_VERSION_CHARS
) -> str:
    """Short SHA-256 hash of the fixed prompt (same text = same version)."""
    return hashlib.sha256(fixed_prompt.encode("utf-8")).hexdigest()[:n_chars]


def build_messages(fixed_prompt: str, question: str) -> list[dict[str, str]]:
    """Chat messages: fixed system prompt first, the user question last."""
    return [
        {"role": "system", "content": fixed_prompt},
        {"role": "user", "content": question},
    ]


def retry_messages(previous_output: str, sql: str | None, error: str) -> list[dict]:
    """Messages to append for the retry: the model's last output, then the error."""
    shown = sql if sql else "(no SQL)"
    feedback = (
        "The previous query was rejected or failed.\n"
        f"Query:\n{shown}\n"
        f"Error: {error}\n"
        "Return a corrected query in the same JSON format, or cannot_answer = true if "
        "the database cannot answer the question."
    )
    return [
        {"role": "assistant", "content": previous_output},
        {"role": "user", "content": feedback},
    ]


def parse_answer(content: str) -> LLMAnswer:
    """Parse and validate the JSON output; raise ValueError if it does not fit."""
    try:
        data = json.loads(content)
    except json.JSONDecodeError as e:
        raise ValueError(f"Output is not valid JSON: {e}") from e
    if not isinstance(data, dict) or set(data) != set(RESPONSE_SCHEMA["required"]):
        raise ValueError("Output does not have exactly the fields of the schema.")
    sql, notes = data["sql"], data["notes"]
    cannot, reason = data["cannot_answer"], data["reason"]
    if not isinstance(cannot, bool) or not isinstance(notes, str):
        raise ValueError("Output fields have the wrong types.")
    if sql is not None and not isinstance(sql, str):
        raise ValueError("Output field sql must be a string or null.")
    if reason is not None and not isinstance(reason, str):
        raise ValueError("Output field reason must be a string or null.")
    return LLMAnswer(sql or None, notes, cannot, reason)
