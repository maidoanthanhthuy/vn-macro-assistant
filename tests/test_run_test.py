from vnmacro.eval import run_test as rt


def row(id_, mode, expected, verdict, route=None, cost=0.001, ms=1000):
    return {
        "id": id_, "mode": mode, "expected": expected, "route": route,
        "verdict": verdict, "latency_ms": ms, "cost_usd": cost, "status": "ok",
        "grade_cost_usd": 0.0001, "question": f"Q {id_}", "reference": "R",
        "text": "Line 1\n\nLine 2",
    }  # fmt: skip


ROWS = [
    row("t1", "agent", "sql", "correct", "sql"),
    row("t2", "agent", "rag", "partial", "sql", ms=3000),
    row("t1", "rag_only", "sql", "wrong", "rag_only"),
    row("t2", "rag_only", "rag", None, "rag_only"),
]


def test_summarize():
    s = rt.summarize(ROWS)
    a, r = s["modes"]["agent"], s["modes"]["rag_only"]
    assert a["verdicts"] == {"correct": 1, "partial": 1}
    assert a["by_route"] == {"sql": {"correct": 1}, "rag": {"partial": 1}}
    assert a["router_correct"] == 1 and a["mean_latency_ms"] == 2000
    assert abs(a["total_cost_usd"] - 0.002) < 1e-12
    assert "router_correct" not in r and r["verdicts"] == {"wrong": 1, None: 1}
    assert s["grading_errors"] == 1 and abs(s["grading_cost_usd"] - 0.0004) < 1e-12


def test_summary_markdown():
    md = rt.summary_markdown(rt.summarize(ROWS), {"date": "d", "model": "m"})
    assert "## agent" in md and "- model: m" in md
    assert "- All 2: correct 1 (50%) / partial 1 (50%) / wrong 0 (0%)" in md
    assert "- Router accuracy: 1/2 (50%)" in md
    assert "not graded 1" in md


def test_pick_human_check_is_reproducible_and_mixed():
    rows = [row(f"t{i:02d}", m, "sql", "correct") for i in range(40) for m in rt.MODES]
    a = rt.pick_human_check(rows, 10, 7)
    b = rt.pick_human_check(list(reversed(rows)), 10, 7)
    assert [(r["id"], r["mode"]) for r in a] == [(r["id"], r["mode"]) for r in b]
    assert len(a) == 10 and {r["mode"] for r in a} == set(rt.MODES)


def test_human_check_markdown_hides_grade_and_mode():
    md = rt.human_check_markdown([row("t1", "agent", "sql", "correct")])
    assert "## 1. t1: Q t1" in md and "**Reference:** R" in md
    assert "> Line 1\n>\n> Line 2" in md
    assert "[ ] correct  [ ] partial  [ ] wrong" in md
    assert "agent" not in md.split("human_check_key.json")[1]
    assert "correct" not in md.replace("[ ] correct", "").replace("correct /", "")
