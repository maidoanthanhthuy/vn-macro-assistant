"""LLM calls through the OpenAI SDK (Chat Completions, structured JSON output).

Chat Completions is used, not the Responses API: it is the interface that other
OpenAI-compatible providers and local servers implement, so switching provider only
needs OPENAI_BASE_URL, OPENAI_API_KEY and OPENAI_MODEL in .env.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from vnmacro import config


@dataclass(frozen=True)
class LLMResponse:
    """Text of one completion plus its token usage."""

    content: str
    input_tokens: int
    cached_input_tokens: int
    output_tokens: int
    refusal: str | None = None


def usage_tokens(usage: Any) -> tuple[int, int, int]:
    """(input, cached input, output) tokens from a usage object; missing parts = 0."""
    if usage is None:
        return 0, 0, 0
    details = getattr(usage, "prompt_tokens_details", None)
    cached = getattr(details, "cached_tokens", None) or 0
    return (
        getattr(usage, "prompt_tokens", None) or 0,
        cached,
        getattr(usage, "completion_tokens", None) or 0,
    )


def cost_usd(
    model: str,
    input_tokens: int,
    cached_input_tokens: int,
    output_tokens: int,
    prices: dict[str, dict[str, float]] = config.LLM_PRICES_USD_PER_MTOK,
) -> float | None:
    """USD cost from token counts (cached tokens count in input); None if unpriced."""
    price = prices.get(model)
    if price is None:
        return None
    uncached = max(input_tokens - cached_input_tokens, 0)
    total = (
        uncached * price["input"]
        + cached_input_tokens * price["cached_input"]
        + output_tokens * price["output"]
    )
    return total / 1_000_000


def json_schema_format(name: str, schema: dict[str, Any]) -> dict[str, Any]:
    """response_format value for strict structured output."""
    return {
        "type": "json_schema",
        "json_schema": {"name": name, "strict": True, "schema": schema},
    }


# ---------- I/O ----------


def make_client(
    timeout: float = config.LLM_TIMEOUT_SECONDS,
    max_retries: int = config.LLM_MAX_RETRIES,
) -> Any:
    """OpenAI client from .env (OPENAI_API_KEY, optional OPENAI_BASE_URL)."""
    from dotenv import load_dotenv
    from openai import OpenAI

    load_dotenv()
    return OpenAI(
        api_key=os.environ.get("OPENAI_API_KEY") or None,
        base_url=os.environ.get("OPENAI_BASE_URL") or None,
        timeout=timeout,
        max_retries=max_retries,
    )


def model_from_env() -> str:
    """Model id from OPENAI_MODEL in .env."""
    from dotenv import load_dotenv

    load_dotenv()
    model = os.environ.get("OPENAI_MODEL")
    if not model:
        raise SystemExit("OPENAI_MODEL is not set in .env")
    return model


def chat_json(
    client: Any,
    model: str,
    messages: list[dict[str, str]],
    schema_name: str,
    schema: dict[str, Any],
) -> LLMResponse:
    """One Chat Completions call with strict JSON output; returns text and usage."""
    resp = client.chat.completions.create(
        model=model,
        messages=messages,
        response_format=json_schema_format(schema_name, schema),
    )
    message = resp.choices[0].message
    tokens = usage_tokens(resp.usage)
    return LLMResponse(
        message.content or "", *tokens, refusal=getattr(message, "refusal", None)
    )
