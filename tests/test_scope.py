import datetime as dt

from vnmacro.agent.scope import (
    answer_prompt,
    build_scope,
    fmt_period,
    format_scope,
    format_scope_brief,
    short_name,
)

D = dt.date
SYMBOLS = [
    ("VNINDEX", "VN-Index", "index", D(2015, 1, 5)),
    ("VHM", "Vinhomes", "stock", D(2018, 5, 17)),
    ("HNXINDEX", "HNX-Index", "index", D(2015, 1, 5)),
    ("FPT", "FPT", "stock", D(2015, 1, 5)),
]
DOCS = [
    ("sbv_directive", "2026", "2026", 1),
    ("nso_monthly_report", "2025-11", "2026-10", 12),
]


def scope(**kw):
    args = dict(
        symbols=SYMBOLS,
        prices=(D(2015, 1, 5), D(2026, 11, 10)),
        indicators=["Tỷ lệ thất nghiệp (% lực lượng lao động)", "Lãi suất cho vay (%)"],
        annual=(2000, 2025, 2031),
        cpi=(D(2001, 12, 1), D(2026, 9, 1)),
        policy=(D(2020, 3, 16), D(2023, 6, 16)),
        documents=DOCS,
    )
    return build_scope(**{**args, **kw})


def test_helpers():
    assert short_name("Lãi suất cho vay (%)") == "Lãi suất cho vay"
    assert fmt_period("2026-10") == "10/2026"
    assert fmt_period("2025-Q4") == "Q4/2025"
    assert fmt_period("2026") == "2026"


def test_build_scope_splits_and_orders_symbols():
    s = scope()
    assert s.stocks == (("FPT", "FPT"), ("VHM", "Vinhomes"))
    assert s.indices == (("VNINDEX", "VN-Index"), ("HNXINDEX", "HNX-Index"))
    assert s.some_listed_later  # VHM starts in 2018
    assert s.annual == ("Tỷ lệ thất nghiệp", "Lãi suất cho vay")
    assert s.documents[0][0] == "nso_monthly_report"


def test_format_scope():
    labels = {"nso_monthly_report": "báo cáo tháng", "sbv_directive": "chỉ thị"}
    text = format_scope(scope(), title="T", doc_labels=labels)
    lines = text.split("\n")
    assert lines[0] == "**T**"
    assert "05/01/2015 đến 10/11/2026; mã niêm yết sau" in lines[1]
    assert lines[1].endswith("FPT (FPT), VHM (Vinhomes).")
    assert lines[2].startswith("- Chỉ số: VN-Index, HNX-Index")
    assert "2000–2025" in lines[3]
    assert "dự báo tăng trưởng GDP của IMF đến 2031" in lines[3]
    assert lines[3].endswith("Tỷ lệ thất nghiệp; Lãi suất cho vay.")
    assert "12/2001 – 09/2026" in lines[4]
    assert "16/03/2020 – 16/06/2023" in lines[5]
    assert lines[6] == "- Tài liệu: báo cáo tháng, 11/2025 – 10/2026 (12 tài liệu)."
    assert lines[7] == "- Tài liệu: chỉ thị, 2026 (1 tài liệu)."


def test_format_scope_without_optional_parts():
    s = scope(
        symbols=SYMBOLS[2:], indicators=[], annual=(None, None, None),
        cpi=(None, None), policy=(None, None), documents=[],
    )  # fmt: skip
    text = format_scope(s)
    assert "mã niêm yết sau" not in text
    assert len(text.split("\n")) == 3  # title, stocks, indices


def test_format_scope_brief():
    lines = format_scope_brief(scope()).split("  \n")
    assert lines[0] == "**Mã:** FPT, VHM · **Chỉ số:** VN-Index, HNX-Index"
    assert "vĩ mô năm (Tỷ lệ thất nghiệp; Lãi suất cho vay)" in lines[1]
    assert lines[2] == (
        "**Dữ liệu đến:** giá 10/11/2026 · CPI 09/2026 · vĩ mô năm 2025 · "
        "báo cáo Cục Thống kê 10/2026"
    )


def test_answer_prompt():
    assert answer_prompt(" RULES \n", "SCOPE") == (
        "RULES\n\n# Data the app can look up\n\nSCOPE\n"
    )
