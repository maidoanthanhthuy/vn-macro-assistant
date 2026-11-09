"""Smoke test for document sources: one NSO monthly report and one SBV press release.

For each: content type (HTML/PDF/other), attachments, and how much clean text a
plain stdlib extraction gets. Nothing is saved or loaded into a database.
"""

from __future__ import annotations

import html
import io
import re
import zipfile
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit
from xml.etree import ElementTree

import requests

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
    )
}
NSO_URL = (
    "https://www.nso.gov.vn/bai-top/2026/11/"
    "bao-cao-tinh-hinh-kinh-te-xa-hoi-thang-muoi-va-10-thang-nam-2026/"
)
SBV_URL = (
    "https://sbv.gov.vn/vi/w/di%E1%BB%85n-bi%E1%BA%BFn-l%C3%A3i-su%E1%BA%A5t-c%E1%BB%A7a-"
    "t%E1%BB%95-ch%E1%BB%A9c-t%C3%ADn-d%E1%BB%A5ng-%C4%91%E1%BB%91i-v%E1%BB%9Bi-"
    "kh%C3%A1ch-h%C3%A0ng-th%C3%A1ng-9/2026"
)
# Plain links (NSO, WordPress) and Liferay links with a "/<uuid>?t=..." suffix (SBV).
ATTACHMENT_RE = re.compile(r'href="([^"]+\.(?:pdf|docx?|xlsx?)(?:/[^"]*)?)"', re.I)
W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


class TextExtractor(HTMLParser):
    """Collect visible text from <p>, headings, list items and table cells."""

    BLOCKS = {"p", "h1", "h2", "h3", "h4", "li", "td", "th"}
    SKIP = {"script", "style", "nav", "header", "footer"}

    def __init__(self) -> None:
        super().__init__()
        self.blocks: list[str] = []
        self._buf: list[str] = []
        self._depth_skip = 0
        self._in_block = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._depth_skip += 1
        elif tag in self.BLOCKS:
            self._in_block += 1

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._depth_skip:
            self._depth_skip -= 1
        elif tag in self.BLOCKS and self._in_block:
            self._in_block -= 1
            text = " ".join("".join(self._buf).split())
            if text:
                self.blocks.append(text)
            self._buf = []

    def handle_data(self, data):
        if self._in_block and not self._depth_skip:
            self._buf.append(data)


def html_blocks(html: str) -> list[str]:
    """Return text blocks from an HTML page."""
    parser = TextExtractor()
    parser.feed(html)
    return parser.blocks


def docx_paragraphs(data: bytes) -> list[str]:
    """Return non-empty paragraphs from a .docx file (stdlib only)."""
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        root = ElementTree.fromstring(z.read("word/document.xml"))
    paras = []
    for p in root.iter(f"{W_NS}p"):
        text = "".join(t.text or "" for t in p.iter(f"{W_NS}t")).strip()
        if text:
            paras.append(text)
    return paras


def pdf_pages(data: bytes) -> list[str]:
    """Return the text of each PDF page (requires pypdf)."""
    from pypdf import PdfReader

    return [page.extract_text() or "" for page in PdfReader(io.BytesIO(data)).pages]


def get(url: str) -> requests.Response:
    resp = requests.get(url, headers=HEADERS, timeout=60)
    resp.raise_for_status()
    return resp


def report_page(label: str, url: str, marker: str) -> None:
    """Fetch a page; show its type, attachments and article text near a marker."""
    resp = get(url)
    print(f"== {label} ==")
    print(f"  status={resp.status_code} type={resp.headers.get('content-type')}")
    print(f"  size={len(resp.content)} bytes")
    attachments = sorted(
        {urljoin(url, html.unescape(a)) for a in ATTACHMENT_RE.findall(resp.text)}
    )
    print(f"  attachments: {attachments or 'none'}")
    blocks = html_blocks(resp.text)
    article = [b for b in blocks if len(b) > 80]  # drop menus and short labels
    print(f"  text blocks (>80 chars): {len(article)}, chars={sum(map(len, article))}")
    hits = [b for b in article if marker.lower() in b.lower()]
    print(f"  blocks mentioning '{marker}': {len(hits)}")
    for b in (hits or article)[:2]:
        print(f"    > {b[:300]}")
    for att in attachments:
        path = urlsplit(att).path.lower()
        if path.endswith(".docx"):
            kind, parts = "docx", docx_paragraphs(get(att).content)
        elif ".pdf" in path:
            pages = pdf_pages(get(att).content)
            kind, parts = (
                f"pdf ({len(pages)} pages)",
                [line for page in pages for line in page.splitlines() if line.strip()],
            )
        else:
            continue
        print(f"  {kind}: {len(parts)} lines/paragraphs, {sum(map(len, parts))} chars")
        hits = [p for p in parts if marker.lower() in p.lower()]
        for p in (hits or parts)[:3]:
            print(f"    > {p[:300]}")
    print()


def main() -> None:
    report_page("NSO monthly socio-economic report (Oct 2026)", NSO_URL, "lạm phát")
    report_page("SBV press release (lending rates, Sep 2026)", SBV_URL, "lãi suất")


if __name__ == "__main__":
    main()
