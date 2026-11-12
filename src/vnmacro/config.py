"""Project settings: tickers, date ranges, data source endpoints and paths."""

from datetime import date
from pathlib import Path

# HTTP defaults for all raw data fetchers
HTTP_PAUSE_SECONDS = 1.0  # pause after every call
HTTP_RETRIES = 2  # retries after the first attempt
HTTP_TIMEOUT_SECONDS = 30.0

# Scope (docs/SCOPE.md, section 2.1)
STOCK_TICKERS: tuple[str, ...] = (
    "VCB", "BID", "CTG", "TCB", "MBB", "VPB",  # banks
    "VHM", "VIC",  # real estate / conglomerate
    "HPG",  # industrials / materials
    "FPT",  # technology
    "VNM", "MSN", "MWG",  # consumer / retail
    "GAS",  # energy
    "SSI",  # securities
)  # fmt: skip
# KBS index symbols, checked in the vnstock source at commit 71b853f0db (read only).
INDEX_SYMBOLS: tuple[str, ...] = ("VNINDEX", "VN30", "HNXINDEX")
STOCK_START = date(2017, 1, 1)
INDEX_START = date(2015, 1, 1)

# KBS price API (unofficial; see docs/data_sources.md)
KBS_BASE_URL = "https://kbbuddywts.kbsec.com.vn/iis-server/investment"
KBS_HEADERS: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
    ),
    "Accept": "application/json",
}
KBS_ROWS_KEY = "data_day"
# Rows / weekdays below this ratio -> the call may be capped; refetch year by year.
KBS_MIN_ROW_RATIO = 0.9

# Vietcap price API: validation source for indices only, never merged into main data.
VIETCAP_URL = "https://trading.vietcap.com.vn/api/chart/OHLCChart/gap-chart"
VIETCAP_HEADERS: dict[str, str] = {
    **KBS_HEADERS,
    "Referer": "https://trading.vietcap.com.vn/",
    "Origin": "https://trading.vietcap.com.vn/",
}
# Our index symbol -> Vietcap symbol (vnstock source at commit 71b853f0db, read only).
VIETCAP_INDEX_SYMBOLS: dict[str, str] = {
    "VNINDEX": "VNINDEX",
    "VN30": "VN30",
    "HNXINDEX": "HNXIndex",
}
MARKET_TZ = "Asia/Ho_Chi_Minh"

# World Bank API (docs/SCOPE.md, section 2.1)
WB_API = "https://api.worldbank.org/v2"
WB_COUNTRY = "VNM"
WB_START_YEAR = 2000
WB_PER_PAGE = 100
WB_HEADERS: dict[str, str] = {"Accept": "application/json"}
WB_INDICATORS: dict[str, str] = {
    "NY.GDP.MKTP.KD.ZG": "GDP growth (annual %)",
    "FP.CPI.TOTL.ZG": "Inflation, consumer prices (annual %)",
    "FR.INR.LEND": "Lending interest rate (%)",
    "PA.NUS.FCRF": "Official exchange rate (VND per USD, period average)",
    "SL.UEM.TOTL.ZS": "Unemployment (% of labor force)",
    "BX.KLT.DINV.WD.GD.ZS": "FDI, net inflows (% of GDP)",
    "NE.EXP.GNFS.ZS": "Exports of goods and services (% of GDP)",
    "FM.LBL.BMNY.ZG": "Broad money growth (annual %)",
}

# IMF Data Portal, SDMX 3.0 (docs/data_sources.md). CSV with attributes=all, because
# series attributes such as LATEST_ACTUAL_ANNUAL_DATA are only returned in that format.
IMF_API = "https://api.imf.org/external/sdmx/3.0"
IMF_HEADERS: dict[str, str] = {"Accept": "application/vnd.sdmx.data+csv;version=2.0.0"}
IMF_TIMEOUT_SECONDS = 180.0
IMF_PERIOD_COL = "TIME_PERIOD"
IMF_VALUE_COL = "OBS_VALUE"
# name -> flow, series key, and series attributes to record in the manifest
IMF_SERIES: dict[str, dict] = {
    "CPI": {"flow": "IMF.STA/CPI", "key": "VNM.CPI._T.IX.M", "attributes": []},
    # IMF's own y/y inflation; used only to check our inflation_yoy at load time.
    "CPI_YOY": {
        "flow": "IMF.STA/CPI",
        "key": "VNM.CPI._T.YOY_PCH_PA_PT.M",
        "attributes": [],
    },
    "WEO_NGDP_RPCH": {
        "flow": "IMF.RES/WEO",
        "key": "VNM.NGDP_RPCH.A",
        "attributes": ["PUBLICATION_DATE", "LATEST_ACTUAL_ANNUAL_DATA"],
    },
}

# Paths (relative to the repository root)
RAW_KBS_DIR = Path("data/raw/kbs")
RAW_WB_DIR = Path("data/raw/worldbank")
RAW_IMF_DIR = Path("data/raw/imf")
EXTERNAL_VIETCAP_DIR = Path("data/external/vietcap")
MANUAL_DIR = Path("data/manual")
REPORTS_DIR = Path("data/reports")
RAW_DOCUMENTS_DIR = Path("data/raw/documents")

# RAG source documents (src/vnmacro/ingest/fetch_documents.py, docs/SCOPE.md 2.2)
DOCUMENTS_FILE = MANUAL_DIR / "documents.csv"
DOC_PAUSE_SECONDS = 1.5  # pause after every call (1-2 s)
# Generic client name: no personal or project details.
DOC_HEADERS: dict[str, str] = {
    "User-Agent": "Mozilla/5.0 (compatible; document-snapshot/0.1)",
    "Accept": "*/*",
}
# Sources whose full text is a .docx attachment linked in the `notes` column.
DOCX_SOURCES: tuple[str, ...] = ("NSO",)
# HTTP codes and page text that mean the site refuses automated access.
BLOCK_HTTP_CODES: tuple[int, ...] = (401, 403, 429)
BLOCK_MARKERS: tuple[str, ...] = ("Request Rejected", "Access Denied", "captcha")

# Text extraction (src/vnmacro/ingest/extract_text.py)
PROCESSED_DOCUMENTS_DIR = Path("data/processed/documents")
FRONT_MATTER_FIELDS: tuple[str, ...] = (
    "doc_id", "source", "doc_type", "title",
    "reference_period", "published_date", "url",
)  # fmt: skip
# Article body per website: CSS selectors for the lead paragraph (sapo), the body, and
# the parts of the body to drop (images, captions, source line, share buttons).
SITE_RULES: dict[str, dict] = {
    "vnba.org.vn": {
        "sapo": ".sapo",
        "body": "div#post_content",
        "drop": ["figure", "h6", ".meta-info", ".social-actions", "script", "style"],
    },
    "thitruongtaichinhtiente.vn": {
        "sapo": ".sc-longform-header-sapo",
        "body": "div.entry",
        "drop": [".sc-longform-header", ".sc-empty-layer", "figure", "script", "style"],
    },
}
NSO_MAX_HEADING_CHARS = 150  # longer paragraphs are never headings
# Checks after extraction
EXPECTED_DOCUMENTS = 17
MIN_CHARS: dict[str, int] = {"nso_monthly_report": 20000, "default": 2000}
JUNK_PHRASES: tuple[str, ...] = (
    "Tính lãi tiền gửi", "Bình luận", "Tin liên quan", "Đặt mua tạp chí",
)  # fmt: skip
# Answer to seed question q10 (must survive extraction)
REQUIRED_TEXT: dict[str, str] = {
    "nso_report_2026_06": (
        r"CPI\)? tháng Sáu giảm[^.]*do giá xăng dầu giảm theo giá nhiên liệu thế giới"
    ),
}

# Database load (src/vnmacro/ingest/load_db.py)
MACRO_START_YEAR = 2000  # World Bank and WEO rows from this year
PRICE_FIXES_FILE = MANUAL_DIR / "price_fixes.csv"
EXPECTED_SYMBOLS = 18
# Daily price band per exchange (%): a normal session cannot move beyond it. Moves
# larger than band + tolerance (rounding of adjusted prices) are reported as warnings.
PRICE_BAND_PCT: dict[str, float] = {"HOSE": 7.0, "HNX": 10.0}
BAND_TOLERANCE_PP = 0.1
YOY_TOLERANCE_PP = 0.01  # max gap between our inflation_yoy and IMF's y/y series
MIN_STOCK_PRICE_VND = 1000.0  # lower stock prices suggest thousand-VND units
