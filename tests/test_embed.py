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
