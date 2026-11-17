import numpy as np

from vnmacro.rag import embed as em


def test_model_id_and_text_hash():
    assert em.model_id("org/m", "abc") == "org/m@abc"
    assert em.text_hash("a") == em.text_hash("a")
    assert em.text_hash("a") != em.text_hash("a ")
    assert len(em.text_hash("tiếng Việt")) == 64


def test_missing_keys_dedupes_and_skips_cached():
    cache = {"b": np.zeros(2)}
    assert em.missing_keys(["a", "b", "a", "c"], cache) == ["a", "c"]


def test_check_vectors():
    good = np.eye(3, dtype=np.float32)
    assert em.check_vectors(good, 3, 1e-3) == []
    assert "shape" in em.check_vectors(good, 4, 1e-3)[0]
    bad = good.copy()
    bad[0, 0] = np.nan
    bad[1] *= 2
    problems = em.check_vectors(bad, 3, 1e-3)
    assert len(problems) == 2
    assert problems[0].startswith("1 vectors with NaN")
    assert problems[1].startswith("1 vectors with norm")


def test_vector_literal():
    assert em.vector_literal(np.array([0.5, -1.0], dtype=np.float32)) == "[0.5,-1.0]"


def test_answer_chunks():
    chunks = [
        {"chunk_id": "a1", "doc_id": "a", "text": "CPI giảm do xăng"},
        {"chunk_id": "a2", "doc_id": "a", "text": "khác"},
        {"chunk_id": "b1", "doc_id": "b", "text": "CPI giảm do xăng"},
    ]
    assert em.answer_chunks(chunks, "a", r"CPI giảm") == {"a1"}


def test_normalize_rows_and_cost():
    import numpy as np

    from vnmacro.rag.embed import embedding_cost_usd, normalize_rows

    v = normalize_rows(np.array([[3.0, 4.0], [0.0, 0.0]]))
    assert v.dtype == np.float32
    assert np.allclose(v, [[0.6, 0.8], [0.0, 0.0]])
    assert embedding_cost_usd("m", 2_000_000, {"m": 0.13}) == 0.26
    assert embedding_cost_usd("other", 10, {"m": 0.13}) is None


def test_backend_settings():
    import pytest

    from vnmacro.rag.embed import backend_settings

    assert backend_settings("openai", {"openai": {"dim": 1024}}) == {"dim": 1024}
    with pytest.raises(SystemExit):
        backend_settings("cloud", {"local": {}})


def test_openai_encode_batches_orders_and_normalizes():
    from types import SimpleNamespace

    import numpy as np

    from vnmacro.rag.embed import openai_encode

    calls = []

    class FakeEmbeddings:
        def create(self, model, input, dimensions):
            calls.append((model, list(input), dimensions))
            data = [
                SimpleNamespace(index=i, embedding=[2.0, 0.0])
                for i in range(len(input))
            ]
            return SimpleNamespace(
                data=data[::-1], usage=SimpleNamespace(total_tokens=5)
            )

    client = SimpleNamespace(embeddings=FakeEmbeddings())
    vecs, tokens = openai_encode(client, "m", 2, ["a", "b", "c"], batch_size=2)
    assert calls == [("m", ["a", "b"], 2), ("m", ["c"], 2)]
    assert tokens == 10 and vecs.shape == (3, 2)
    assert np.allclose(vecs, [[1.0, 0.0]] * 3)
