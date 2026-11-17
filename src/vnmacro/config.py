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
    "doc_id", "source", "doc_type", "title", "context_label",
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
# Quarterly NSO reports end with an untitled closing summary starting with this phrase.
# A level-1 heading (not in the source) is added before it, so its chunks get their own
# label instead of the heading of the report's last section.
NSO_CLOSING_MARKERS: tuple[str, ...] = ("Khái quát lại",)
NSO_CLOSING_HEADING = "Kết luận chung"
# Reports for these months (quarter ends) must contain the closing summary; a warning is
# printed when the marker is missing (the report format may have changed).
NSO_REPORT_TYPE = "nso_monthly_report"
NSO_QUARTER_MONTHS: tuple[str, ...] = ("03", "06", "09", "12")
# Checks after extraction
EXPECTED_DOCUMENTS = 17
MIN_CHARS: dict[str, int] = {"nso_monthly_report": 20000, "default": 2000}
JUNK_PHRASES: tuple[str, ...] = (
    "Tính lãi tiền gửi", "Bình luận", "Tin liên quan", "Đặt mua tạp chí",
)  # fmt: skip
# Chunking (src/vnmacro/rag/chunking.py). One entry per strategy, so later phases can
# add strategies without changing the code.
CHUNKS_DIR = Path("data/processed/chunks")
CHUNKING_STRATEGIES: dict[str, dict] = {
    "heading_v1": {
        "max_chars": 1500,  # longer sections are split at paragraph, then sentence
        "min_chars": 300,  # shorter sections are merged with the next section
        "overlap_chars": 0,  # no overlap between chunks (only 0 is supported)
        "context_sep": " › ",
    },
}
DEFAULT_CHUNKING = "heading_v1"
# Words ending in "." that do not end a sentence (e.g. "TP. Hồ Chí Minh").
SENTENCE_ABBREVIATIONS: tuple[str, ...] = ("TP", "Tp", "TS", "ThS", "PGS", "GS")
# Chunk checks: the chunk holding this answer must carry this context text.
REQUIRED_CONTEXT: dict[str, str] = {"nso_report_2026_06": "tháng 6/2026"}

# Answer to seed question q10 (must survive extraction)
REQUIRED_TEXT: dict[str, str] = {
    "nso_report_2026_06": (
        r"CPI\)? tháng Sáu giảm[^.]*do giá xăng dầu giảm theo giá nhiên liệu thế giới"
    ),
}

# RAG load and embeddings (src/vnmacro/rag/load_rag.py, src/vnmacro/rag/embed.py)
RAG_SCHEMA = "rag"  # vector type and operators live here (sql/rag_schema.sql)
EMBEDDINGS_DIR = Path("data/processed/embeddings")  # local vector cache
EMBEDDING_MODEL: dict = {
    "repo": "AITeamVN/Vietnamese_Embedding_v2",
    "revision": "18b44161e041bf1d3a333ab5144b5b7b93f914d2",  # Hugging Face commit
    "dim": 1024,
    "max_seq_length": 2048,  # passage length the model was trained with
    "batch_size": 4,  # small batches keep RAM low on CPU
    "num_threads": 8,  # torch CPU threads (leave cores free)
}
NORM_TOLERANCE = 1e-3  # normalized vectors: | ||v|| - 1 | must stay below this
# Retrieval check: the q10 answer chunk (matched by REQUIRED_TEXT) must be in the top k.
RETRIEVAL_CHECK: dict = {
    "query": "Vì sao chỉ số giá tiêu dùng tháng 6/2026 giảm so với tháng trước?",
    "doc_id": "nso_report_2026_06",
    "top_k": 5,
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

# Read-only role for Text-to-SQL (src/vnmacro/roles.py)
ROLES_SQL = Path("sql/roles.sql")
READER_ROLE = "vnmacro_reader"  # must match the role name in sql/roles.sql
LOGGER_ROLE = "vnmacro_logger"  # must match the role name in sql/roles.sql
# role -> (.env variable with its password, .env variable with its connection URL)
DB_ROLE_ENV: dict[str, tuple[str, str]] = {
    READER_ROLE: ("DB_READER_PASSWORD", "DATABASE_URL_READER"),
    LOGGER_ROLE: ("DB_LOGGER_PASSWORD", "DATABASE_URL_LOGGER"),
}
# Databases the roles are applied to: the owner's connection (.env URL variable; None =
# POSTGRES_* of the local Docker database) and each role's (password, URL) variables.
DB_TARGETS: dict[str, dict] = {
    "local": {"owner_url_env": None, "roles": DB_ROLE_ENV, "hash_passwords": True},
    "neon": {
        "owner_url_env": "NEON_DATABASE_URL",
        "hash_passwords": False,  # Neon rejects pre-hashed passwords
        "roles": {
            READER_ROLE: ("NEON_DB_READER_PASSWORD", "NEON_DATABASE_URL_READER"),
            LOGGER_ROLE: ("NEON_DB_LOGGER_PASSWORD", "NEON_DATABASE_URL_LOGGER"),
        },
    },
}
APP_SCHEMA_SQL = Path("sql/app_schema.sql")  # schema app: query log

# Schema context for Text-to-SQL (vnmacro.sql_agent.context)
SQL_CONTEXT_SCHEMA = "public"
# Tables listed in full instead of sample rows.
SQL_CONTEXT_FULL_TABLES: tuple[str, ...] = ("symbols", "indicators")
# table -> (period column, optional group column, list only groups whose last period
# differs from the table's last period). Without the flag every group is listed.
SQL_CONTEXT_COVERAGE: dict[str, tuple[str, str | None, bool]] = {
    "daily_prices": ("date", "symbol", True),
    "macro_annual": ("year", "indicator_code", False),
    "cpi_monthly": ("month", None, False),
    "policy_events": ("announced_date", None, False),
}
SQL_CONTEXT_SAMPLE_ROWS = 3
# table -> (key column, key values): samples are these keys on the latest period
# (two stocks and one index, so both VND and points appear).
SQL_CONTEXT_SAMPLE_KEYS: dict[str, tuple[str, tuple[str, ...]]] = {
    "daily_prices": ("symbol", ("FPT", "VCB", "VNINDEX")),
}
# Columns left out of sample rows (still described under Columns).
SQL_CONTEXT_SAMPLE_EXCLUDE: dict[str, tuple[str, ...]] = {
    "policy_events": ("source_url", "notes"),
}
SQL_CONTEXT_SAMPLE_DECIMALS = 2  # sample numbers are shown with at most this many
SQL_CONTEXT_MAX_VALUE_CHARS = 80  # longer sample values are cut with "..."
SQL_CONTEXT_CHARS_PER_TOKEN = 4  # rough token estimate for the preview
SQL_CONVENTIONS_FILE = Path("prompts/sql_conventions.md")  # SQL rules for the LLM
SQL_EXAMPLES_FILE = Path("prompts/sql_examples.md")  # few-shot SQL examples
SQL_ROLE_FILE = Path("prompts/sql_role.md")  # short role instructions for the LLM

# Text-to-SQL pipeline (src/vnmacro/sql_agent/pipeline.py)
SQL_MAX_ROWS = 200  # LIMIT is set or lowered to this; at most this many rows fetched
SQL_STATEMENT_TIMEOUT = "5s"  # SET LOCAL before every generated query
SQL_MAX_LLM_CALLS = 2  # first try + one retry with the check or database error
SQL_ALLOWED_SCHEMAS: tuple[str, ...] = ("public",)
PROMPT_VERSION_CHARS = 12  # length of the prompt hash stored in app.query_log
LOG_COMPONENT_TEXT_TO_SQL = "text_to_sql"
# Functions a generated query may never call (lower case). Exact names, then prefixes.
# The *_to_xml functions and dblink run SQL given as a string, which the parser cannot
# inspect; the others read files, sleep, signal backends, change settings or sequences.
SQL_BLOCKED_FUNCTIONS: tuple[str, ...] = (
    "set_config", "current_setting", "pg_sleep", "pg_sleep_for", "pg_sleep_until",
    "pg_read_file", "pg_read_binary_file", "pg_ls_dir", "pg_stat_file",
    "pg_terminate_backend", "pg_cancel_backend", "pg_reload_conf", "pg_rotate_logfile",
    "lo_import", "lo_export", "dblink", "dblink_exec", "dblink_connect",
    "query_to_xml", "query_to_xml_and_xmlschema", "query_to_xmlschema",
    "cursor_to_xml", "table_to_xml", "schema_to_xml", "database_to_xml",
    "nextval", "setval", "currval", "lastval", "txid_current", "pg_notify",
    "pg_switch_wal", "pg_promote", "pg_export_snapshot",
)  # fmt: skip
SQL_BLOCKED_FUNCTION_PREFIXES: tuple[str, ...] = (
    "pg_read_", "pg_ls_", "pg_file_", "lo_", "dblink", "pg_advisory",
    "pg_try_advisory", "pg_logical_", "pg_replication_", "pg_create_", "pg_drop_",
    "pg_backup_", "pg_terminate_", "pg_cancel_", "pg_sleep",
)  # fmt: skip

# LLM calls (src/vnmacro/llm.py). Model, key and optional base URL come from .env.
LLM_TIMEOUT_SECONDS = 30.0  # per API call
LLM_MAX_RETRIES = 2  # SDK retries on connection errors, timeouts, 429 and 5xx
# USD per 1 million tokens, per model (OpenAI Standard tier, checked 2026-11-15).
LLM_PRICES_USD_PER_MTOK: dict[str, dict[str, float]] = {
    "gpt-6-luna": {"input": 0.10, "cached_input": 0.01, "output": 0.50},
}

# Dev-set evaluation of Text-to-SQL (src/vnmacro/eval/run_sql_dev.py)
SEED_QUESTIONS_FILE = Path("eval/seed_questions.csv")
MANUAL_CHECKS_SQL = Path("sql/manual_checks.sql")
EVAL_RUNS_DIR = Path("eval/runs")  # gitignored: dev results stay local
EVAL_REL_TOL = 0.001  # 0.1% relative tolerance for numeric key values
# Hybrid questions whose SQL part depends on RAG (e.g. the month): shown as "phase 4".
EVAL_PHASE4_IDS: tuple[str, ...] = ("q16",)
EVAL_NOTE_MIN_CHARS = 60  # seed notes longer than this are printed with the result
# Key values of each reference answer: (columns, "first" row or "all" rows). A question
# passes if every key value appears somewhere in the agent's result.
EVAL_SQL_KEYS: dict[str, tuple[tuple[str, ...], str]] = {
    "q01": (("date", "close"), "first"),
    "q02": (("pct_change",), "first"),
    "q03": (("symbol", "pct_change"), "first"),
    "q04": (("gdp_growth_pct",), "first"),
    "q05": (("avg_inflation_pct",), "first"),
    "q06": (("avg_daily_volume",), "first"),
    "q07": (("pct_change",), "first"),
    "q08": (("gdp_growth_pct", "inflation_pct"), "all"),
    "q15": (("pct_change",), "first"),
    "q16": (("symbol", "pct_change"), "all"),
    "q17": (("n_hike_decisions", "pct_change"), "first"),
    "q21": (("gdp_growth_pct", "vintage"), "first"),
    "q22": (("gdp_growth_pct", "vintage"), "first"),
    "q23": (("start_date", "pct_change"), "first"),
}

# Router and period resolver (src/vnmacro/agent/router.py, resolver.py)
ROUTER_PROMPT_FILE = Path("prompts/router.md")  # role, tools, time rules, examples
LOG_COMPONENT_ROUTER = "router"
# Period column of each public table shown to the router as data coverage (min .. max).
ROUTER_COVERAGE: dict[str, tuple[str, str | None, bool]] = {
    table: (column, None, False)
    for table, (column, _, _) in SQL_CONTEXT_COVERAGE.items()
}
# "latest" for rag/both = period of the newest document of this type.
LATEST_REPORT_TYPE = NSO_REPORT_TYPE
# Dev-set expected_tool -> router route.
EVAL_ROUTE_MAP: dict[str, str] = {
    "sql": "sql",
    "rag": "rag",
    "sql+rag": "both",
    "none": "out_of_scope",
    "explain": "explain",
}

# Retrieval for the agent (src/vnmacro/agent/retrieve.py)
RETRIEVE_TOP_K = 5
# Dev-set retrieval check: documents that hold the answer (from answer_source and the
# question's period). q11 has none: its 2023 SBV documents are not loaded.
EVAL_RAG_DOCS: dict[str, tuple[str, ...]] = {
    "q09": ("nso_report_2026_10",),
    "q10": ("nso_report_2026_06",),
    "q11": (),
    "q12": ("nso_report_2026_06",),
    "q13": ("nso_report_2026_08",),
    "q14": ("sbv_directive_2026_01", "sbv_press_2025_q4"),
    "q16": ("nso_report_2026_10",),
}
# Chunks that hold the answer (docs/rag_notes.md, smoke test 1): chunk-level rank.
EVAL_RAG_CHUNKS: dict[str, tuple[str, ...]] = {
    "q09": ("nso_report_2026_10_029",),
    "q10": ("nso_report_2026_06_052",),
    "q12": ("nso_report_2026_06_003",),
    "q13": ("nso_report_2026_08_026",),
    "q14": ("sbv_directive_2026_01_002",),
    "q16": ("nso_report_2026_10_029",),
}

# Answer step and agent (src/vnmacro/agent/answer.py, agent.py)
ANSWER_PROMPT_FILE = Path("prompts/answer.md")
LOG_COMPONENT_ANSWER = "answer"
LOG_COMPONENT_RETRIEVE = "retrieve"
ANSWER_MAX_CELL_CHARS = 200  # longer SQL cell values are cut in the answer input
# Shown when a step fails (user-facing, Vietnamese).
ANSWER_ERROR_TEXT = (
    "Xin lỗi, hệ thống đang gặp lỗi và chưa trả lời được. Bạn thử lại sau nhé."
)
# Source line per data table read by the final SQL (user-facing, Vietnamese). Tables not
# listed (lookup tables symbols, indicators) are not shown as sources.
SOURCE_TABLE_LABELS: dict[str, str] = {
    "daily_prices": "giá đóng cửa và khối lượng hằng ngày (giá điều chỉnh), nguồn KBS",
    "macro_annual": (
        "chỉ tiêu vĩ mô hằng năm: World Bank (số thực tế) và IMF WEO (tăng trưởng GDP, "
        "gồm dự báo)"
    ),
    "cpi_monthly": "chỉ số giá tiêu dùng (CPI) hằng tháng, nguồn IMF",
    "policy_events": "các lần NHNN đổi lãi suất điều hành (theo thông cáo của NHNN)",
}

# Route `explain` (general knowledge): note added by code after the explanation, and the
# lead-in of the suggested lookup question (user-facing, Vietnamese).
EXPLAIN_NOTE = "_Đây là giải thích chung, không lấy từ dữ liệu của app._"
EXPLAIN_SUGGESTION_LEAD = "Câu hỏi gợi ý"
ANSWER_TITLES: dict[str, str] = {"explain": "Giải thích", "default": "Trả lời ngắn"}

# Data scope (src/vnmacro/agent/scope.py): shown on the main screen and appended to
# refusals. Labels are user-facing (Vietnamese).
SCOPE_DOC_TYPE_LABELS: dict[str, str] = {
    "nso_monthly_report": "báo cáo kinh tế - xã hội hằng tháng của Cục Thống kê",
    "sbv_quarterly_press": "họp báo quý của Ngân hàng Nhà nước",
    "sbv_directive": "chỉ thị điều hành năm của Ngân hàng Nhà nước",
}
SCOPE_TITLE = "Dữ liệu mình tra cứu được"
APP_DISCLAIMER = "Thông tin chỉ để tham khảo, không phải lời khuyên đầu tư."

# Official test-set run (src/vnmacro/eval/run_test.py, grade.py)
TEST_QUESTIONS_FILE = Path("eval/test_questions.csv")
EVAL_RESULTS_DIR = Path("eval/results")  # committed: official results
GRADE_PROMPT_FILE = Path("prompts/grade.md")
HUMAN_CHECK_N = 10  # answers sampled for the human check
HUMAN_CHECK_SEED = 20261117

# Embedding backends (vnmacro.rag.embed, vnmacro.agent.retrieve). EMBEDDING_BACKEND in
# .env picks the one used to embed questions at runtime; with "openai" the app needs no
# torch. Each backend stores its vectors under its own model_name (repo@revision).
EMBEDDING_BACKENDS: dict[str, dict] = {
    "local": EMBEDDING_MODEL,
    "openai": {
        "repo": "openai/text-embedding-3-large",
        "revision": "dim1024",  # no commit for an API model: the output size instead
        "api_model": "text-embedding-3-large",
        "dim": 1024,  # API `dimensions` parameter (same vector(1024) column as local)
        "batch_size": 64,  # texts per API call
    },
}
DEFAULT_EMBEDDING_BACKEND = "local"
# USD per 1 million input tokens (OpenAI model page, checked 2026-11-17).
EMBEDDING_PRICES_USD_PER_MTOK: dict[str, float] = {"text-embedding-3-large": 0.13}
EVAL_COMPARE_TOP_K = 20  # embedding comparison: ranks shown up to this depth

# Streamlit app (app.py, src/vnmacro/app/). Settings come from environment variables
# (.env locally, root-level secrets on Streamlit Cloud): APP_PASSWORD, OPENAI_*,
# DATABASE_URL_READER, DATABASE_URL_LOGGER, EMBEDDING_BACKEND.
APP_TITLE = "Trợ lý số liệu thị trường & kinh tế Việt Nam"
APP_SUGGESTED_QUESTIONS: tuple[str, ...] = (
    "VN-Index năm 2025 tăng hay giảm bao nhiêu phần trăm?",
    "Lạm phát tháng gần nhất là bao nhiêu?",
    "Báo cáo tháng 10/2026 nói gì về xuất khẩu?",
    "Lãi suất tái cấp vốn của Ngân hàng Nhà nước hiện nay là bao nhiêu?",
)
FEEDBACK_RATINGS: tuple[str, ...] = ("up", "down")
FEEDBACK_MAX_CHARS = 1000  # same limit as the CHECK on app.feedback.comment
