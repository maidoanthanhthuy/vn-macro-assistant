"""Project settings: tickers, date ranges, data source endpoints and paths."""

from datetime import date
from pathlib import Path

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
KBS_PAUSE_SECONDS = 1.0
KBS_RETRIES = 2
KBS_TIMEOUT_SECONDS = 30.0
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

# Paths (relative to the repository root)
RAW_KBS_DIR = Path("data/raw/kbs")
EXTERNAL_VIETCAP_DIR = Path("data/external/vietcap")
