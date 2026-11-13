import unicodedata

import pytest

from vnmacro.ingest import extract_text as et

RULE = {"sapo": ".sapo", "body": "div#post", "drop": ["figure", ".meta"]}


def test_normalize_text_nfc_spaces_and_blank_lines():
    decomposed = unicodedata.normalize("NFD", "Tín dụng")
    raw = f"‏{decomposed}  tăng\t 3%  \n\n\n\n  Lãi suất ​\n\n"
    out = et.normalize_text(raw)
    assert out == "Tín dụng tăng 3%\n\nLãi suất"
    assert unicodedata.is_normalized("NFC", out)


def test_drop_junk_lines_removes_photo_captions_and_rules():
    lines = ["Ảnh: Thanh Hà", "(Ảnh: TTXVN)", "____", "CPI tăng 0,2%.", "Ảnh hưởng lớn"]
    assert et.drop_junk_lines(lines) == ["CPI tăng 0,2%.", "Ảnh hưởng lớn"]


def test_nso_heading_level():
    assert et.nso_heading_level("I. TĂNG TRƯỞNG KINH TẾ", bold=True) == 1
    assert et.nso_heading_level("5. Chỉ số giá", bold=True) == 2
    assert et.nso_heading_level("a) Chỉ số giá tiêu dùng", bold=True) == 3
    assert et.nso_heading_level("b) Xuất, nhập khẩu hàng hóa", bold=False) == 3
    assert et.nso_heading_level("1. Vốn tăng 5%.", bold=False) is None
    assert et.nso_heading_level("a) lương thực giảm 0,78%;", bold=False) is None
    assert et.nso_heading_level("CPI tháng Sáu giảm 0,39%.", bold=True) is None


def test_nso_blocks_to_markdown_drops_captions_and_keeps_order():
    blocks = [
        ("5. Chỉ số giá", True),
        ("CPI tháng Sáu giảm 0,39%.", False),
        ("Hình 18. Tốc độ tăng, giảm CPI", True),
        ("so với tháng trước (%)", True),
        ("%", True),
        ("Nhóm giao thông giảm 4,85%.", False),
    ]
    assert et.nso_blocks_to_markdown(blocks) == (
        "## 5. Chỉ số giá\n\nCPI tháng Sáu giảm 0,39%.\n\nNhóm giao thông giảm 4,85%."
    )


def test_html_to_markdown_keeps_body_and_drops_junk():
    html = """<html><nav>Tính lãi tiền gửi</nav>
    <p class="sapo">Sáng 2/7, NHNN họp báo.</p>
    <div id="post">
      <p>Tín dụng tăng 7,41%.</p>
      <p><strong>Lãi suất ổn định</strong></p>
      <figure><img/><figcaption>Toàn cảnh họp báo</figcaption></figure>
      <h5>Thanh toán tăng mạnh</h5>
      <p>Ảnh: Thời báo Ngân hàng</p>
      <div class="meta">Theo sbv.gov.vn</div>
    </div><footer>Bình luận</footer></html>"""
    assert et.html_to_markdown(html, RULE) == (
        "Sáng 2/7, NHNN họp báo.\n\nTín dụng tăng 7,41%.\n\n## Lãi suất ổn định"
        "\n\n## Thanh toán tăng mạnh"
    )


def test_check_results_flags_junk_short_and_missing_answer():
    results = {
        "a": {"kind": "html", "doc_type": "press", "chars": 50},
        "b": {"kind": "docx", "doc_type": "nso_monthly_report", "chars": 30000},
    }
    texts = {"a": "Tin liên quan ...", "b": "CPI giảm do giá xăng dầu"}
    problems = et.check_results(
        results, texts, 3, {"b": "giá xăng dầu"}, ["Tin liên quan"],
        {"nso_monthly_report": 20000, "default": 2000},
    )  # fmt: skip
    assert len(problems) == 3
    assert any("expected 3" in p for p in problems)
    assert any("junk" in p for p in problems)
    assert any("only 50 chars" in p for p in problems)


def test_site_rule_matches_host_without_www():
    rules = {"vnba.org.vn": {"body": "div#post_content"}}
    assert (
        et.site_rule("https://www.vnba.org.vn/vi/a-1.htm", rules)
        == rules["vnba.org.vn"]
    )
    assert et.site_rule("https://VNBA.org.vn/x", rules)["body"] == "div#post_content"


def test_site_rule_raises_for_unknown_host():
    with pytest.raises(KeyError, match="example.com"):
        et.site_rule("https://example.com/a", {"vnba.org.vn": {}})


def test_nso_blocks_to_markdown_adds_closing_heading_once():
    blocks = [
        ("8. Bảo vệ môi trường", True),
        ("Vi phạm môi trường giảm.", False),
        ("Khái quát lại, kinh tế ổn định.", False),
        ("Một là, giữ ổn định vĩ mô.", False),
        ("Khái quát lại lần nữa.", False),
    ]
    md = et.nso_blocks_to_markdown(blocks, closing_markers=("Khái quát lại",),
                                   closing_heading="Kết luận chung")  # fmt: skip
    assert md == (
        "## 8. Bảo vệ môi trường\n\nVi phạm môi trường giảm.\n\n# Kết luận chung\n\n"
        "Khái quát lại, kinh tế ổn định.\n\nMột là, giữ ổn định vĩ mô.\n\n"
        "Khái quát lại lần nữa."
    )


def test_nso_blocks_to_markdown_no_marker_no_heading():
    md = et.nso_blocks_to_markdown([("Văn bản.", False)], closing_markers=("X",))
    assert md == "Văn bản."


def test_warn_missing_closing_only_for_quarter_end_reports():
    def doc(doc_id, period, doc_type="nso_monthly_report"):
        return {"doc_id": doc_id, "doc_type": doc_type, "reference_period": period}

    docs = [
        doc("q_ok", "2026-06"),
        doc("q_missing", "2026-09"),
        doc("monthly", "2026-08"),
        doc("press", "2026-Q3", doc_type="sbv_quarterly_press"),
        doc("not_extracted", "2026-12"),
    ]
    texts = {
        "q_ok": "## 8. Môi trường\n\nText.\n\n# Kết luận chung\n\nKhái quát lại, ...",
        "q_missing": "## 8. Môi trường\n\nText. Kết luận chung trong câu.",
        "monthly": "## 8. Môi trường\n\nText.",
        "press": "Text.",
    }
    warnings = et.warn_missing_closing(
        docs, texts, "nso_monthly_report", ("03", "06", "09", "12"), "Kết luận chung"
    )
    assert len(warnings) == 1
    assert warnings[0].startswith("q_missing:")
