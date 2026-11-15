from types import SimpleNamespace

import pytest

from vnmacro import llm

PRICES = {"m": {"input": 0.10, "cached_input": 0.01, "output": 0.50}}


def test_cost_usd():
    # 1M input of which 400k cached, 100k output
    cost = llm.cost_usd("m", 1_000_000, 400_000, 100_000, PRICES)
    assert cost == pytest.approx(0.6 * 0.10 + 0.4 * 0.01 + 0.1 * 0.50)
    assert llm.cost_usd("m", 0, 0, 0, PRICES) == 0
    assert llm.cost_usd("unknown", 10, 0, 10, PRICES) is None


def test_usage_tokens():
    usage = SimpleNamespace(
        prompt_tokens=5000,
        completion_tokens=120,
        prompt_tokens_details=SimpleNamespace(cached_tokens=4096),
    )
    assert llm.usage_tokens(usage) == (5000, 4096, 120)
    # providers without details or usage
    bare = SimpleNamespace(prompt_tokens=10, completion_tokens=2)
    assert llm.usage_tokens(bare) == (10, 0, 2)
    assert llm.usage_tokens(None) == (0, 0, 0)


def test_json_schema_format_is_strict():
    fmt = llm.json_schema_format("x", {"type": "object"})
    assert fmt["type"] == "json_schema"
    assert fmt["json_schema"]["strict"] is True
    assert fmt["json_schema"]["name"] == "x"


def test_chat_json_with_fake_client():
    message = SimpleNamespace(content='{"a": 1}', refusal=None)
    usage = SimpleNamespace(prompt_tokens=7, completion_tokens=3,
                            prompt_tokens_details=None)  # fmt: skip
    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=usage)

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
        create=create)))  # fmt: skip
    out = llm.chat_json(client, "m", [{"role": "user", "content": "q"}], "s", {})
    assert out == llm.LLMResponse('{"a": 1}', 7, 0, 3, None)
    assert calls[0]["model"] == "m"
    assert calls[0]["response_format"]["json_schema"]["strict"] is True
