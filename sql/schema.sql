-- Schema for the structured data layer (PostgreSQL 16).
-- Design notes: docs/SCHEMA.md. Documents and embeddings (pgvector) are added later.

-- ---------------------------------------------------------------------------
-- symbols
-- ---------------------------------------------------------------------------
CREATE TABLE symbols (
    symbol      TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    full_name   TEXT NOT NULL,
    aliases     TEXT NOT NULL DEFAULT '',
    asset_type  TEXT NOT NULL CHECK (asset_type IN ('stock', 'index')),
    sector      TEXT CHECK (sector IN (
                    'Ngân hàng', 'Bất động sản / Đa ngành', 'Công nghiệp / Vật liệu',
                    'Công nghệ', 'Tiêu dùng / Bán lẻ', 'Năng lượng', 'Chứng khoán')),
    exchange    TEXT NOT NULL CHECK (exchange IN ('HOSE', 'HNX')),
    price_unit  TEXT NOT NULL CHECK (price_unit IN ('VND', 'points')),
    first_date  DATE NOT NULL,
    CHECK ((asset_type = 'stock' AND price_unit = 'VND' AND sector IS NOT NULL)
        OR (asset_type = 'index' AND price_unit = 'points' AND sector IS NULL))
);

COMMENT ON TABLE symbols IS
    'One row per stock or market index that has daily prices. Join to daily_prices on symbol.';
COMMENT ON COLUMN symbols.symbol IS
    'Ticker or index code, upper case, e.g. FPT, VCB, VNINDEX, VN30, HNXINDEX.';
COMMENT ON COLUMN symbols.name IS
    'Short Vietnamese name, e.g. ''Vietcombank'', ''VN-Index''.';
COMMENT ON COLUMN symbols.full_name IS
    'Full Vietnamese company or index name.';
COMMENT ON COLUMN symbols.aliases IS
    'Other names users may type, comma-separated (Vietnamese, no diacritics, abbreviations). Search with ILIKE, e.g. aliases ILIKE ''%vietcombank%'' OR name ILIKE ''%vietcombank%''.';
COMMENT ON COLUMN symbols.asset_type IS
    '''stock'' or ''index''.';
COMMENT ON COLUMN symbols.sector IS
    'Vietnamese sector group from the project scope; NULL for indices.';
COMMENT ON COLUMN symbols.exchange IS
    'Exchange: ''HOSE'' or ''HNX''.';
COMMENT ON COLUMN symbols.price_unit IS
    'Unit of prices in daily_prices: ''VND'' (dong, not thousand dong) for stocks, ''points'' for indices.';
COMMENT ON COLUMN symbols.first_date IS
    'First date with a price in daily_prices for this symbol.';

-- ---------------------------------------------------------------------------
-- daily_prices
-- ---------------------------------------------------------------------------
CREATE TABLE daily_prices (
    date    DATE NOT NULL,
    symbol  TEXT NOT NULL REFERENCES symbols (symbol),
    open    NUMERIC(14, 2) NOT NULL CHECK (open > 0),
    high    NUMERIC(14, 2) NOT NULL CHECK (high > 0),
    low     NUMERIC(14, 2) NOT NULL CHECK (low > 0),
    close   NUMERIC(14, 2) NOT NULL CHECK (close > 0),
    volume  BIGINT CHECK (volume >= 0),
    PRIMARY KEY (symbol, date),
    CHECK (low <= high)
);

CREATE INDEX daily_prices_date_idx ON daily_prices (date);

COMMENT ON TABLE daily_prices IS
    'Daily OHLCV for 15 stocks (from 2017-01-01) and 3 indices (from 2015-01-01); trading days only. Stock prices are adjusted. Source: KBS.';
COMMENT ON COLUMN daily_prices.date IS
    'Trading date (Vietnam time).';
COMMENT ON COLUMN daily_prices.symbol IS
    'Ticker or index code; see symbols.';
COMMENT ON COLUMN daily_prices.open IS
    'Opening price: VND for stocks, points for indices (see symbols.price_unit).';
COMMENT ON COLUMN daily_prices.high IS
    'Highest price of the day: VND for stocks, points for indices.';
COMMENT ON COLUMN daily_prices.low IS
    'Lowest price of the day: VND for stocks, points for indices.';
COMMENT ON COLUMN daily_prices.close IS
    'Closing price: VND for stocks, points for indices. Use for returns (close-to-close).';
COMMENT ON COLUMN daily_prices.volume IS
    'Matched volume in shares (for indices: total shares of the index). NULL when the source value is known to be wrong.';

-- ---------------------------------------------------------------------------
-- indicators
-- ---------------------------------------------------------------------------
CREATE TABLE indicators (
    indicator_code  TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    unit            TEXT NOT NULL,
    source          TEXT NOT NULL CHECK (source IN ('World Bank', 'IMF WEO', 'IMF CPI')),
    frequency       TEXT NOT NULL CHECK (frequency IN ('annual', 'monthly')),
    table_name      TEXT NOT NULL CHECK (table_name IN ('macro_annual', 'cpi_monthly')),
    notes           TEXT
);

COMMENT ON TABLE indicators IS
    'Catalog of macro series: what each indicator_code means, its unit, source and the table that holds it.';
COMMENT ON COLUMN indicators.indicator_code IS
    'Source code of the series, e.g. NY.GDP.MKTP.KD.ZG (World Bank), NGDP_RPCH (IMF WEO).';
COMMENT ON COLUMN indicators.name IS
    'Vietnamese name, e.g. ''Tăng trưởng GDP thực''.';
COMMENT ON COLUMN indicators.unit IS
    'Unit of value, e.g. ''%'', ''% GDP'', ''VND/USD'', ''index (2024 = 100)''.';
COMMENT ON COLUMN indicators.source IS
    '''World Bank'', ''IMF WEO'' or ''IMF CPI''. Always cite it in answers.';
COMMENT ON COLUMN indicators.frequency IS
    '''annual'' or ''monthly''.';
COMMENT ON COLUMN indicators.table_name IS
    'Table that stores the values: ''macro_annual'' or ''cpi_monthly''.';
COMMENT ON COLUMN indicators.notes IS
    'Caveats, e.g. publication lag or overlap with another series.';

-- ---------------------------------------------------------------------------
-- macro_annual
-- ---------------------------------------------------------------------------
CREATE TABLE macro_annual (
    indicator_code  TEXT NOT NULL REFERENCES indicators (indicator_code),
    year            INTEGER NOT NULL CHECK (year BETWEEN 1990 AND 2100),
    value           NUMERIC NOT NULL,
    is_forecast     BOOLEAN NOT NULL DEFAULT FALSE,
    vintage         TEXT,
    PRIMARY KEY (indicator_code, year),
    CHECK (NOT is_forecast OR vintage IS NOT NULL)
);

COMMENT ON TABLE macro_annual IS
    'Annual macro values for Vietnam: World Bank indicators (actuals) and IMF WEO real GDP growth (actuals + forecasts). Join indicators for name, unit and source.';
COMMENT ON COLUMN macro_annual.indicator_code IS
    'Series code; see indicators.';
COMMENT ON COLUMN macro_annual.year IS
    'Calendar year, integer (e.g. 2024).';
COMMENT ON COLUMN macro_annual.value IS
    'Value in the unit given by indicators.unit.';
COMMENT ON COLUMN macro_annual.is_forecast IS
    'TRUE for IMF forecasts (year after the latest actual year of the WEO vintage). Answers must say it is a forecast.';
COMMENT ON COLUMN macro_annual.vintage IS
    'WEO release, e.g. ''WEO October 2026''; NULL for World Bank rows.';

-- ---------------------------------------------------------------------------
-- cpi_monthly
-- ---------------------------------------------------------------------------
CREATE TABLE cpi_monthly (
    month          DATE PRIMARY KEY CHECK (EXTRACT(DAY FROM month) = 1),
    cpi_index      NUMERIC NOT NULL CHECK (cpi_index > 0),
    inflation_yoy  NUMERIC
);

COMMENT ON TABLE cpi_monthly IS
    'Monthly headline CPI for Vietnam from IMF (index 2024 = 100). Default source for monthly inflation.';
COMMENT ON COLUMN cpi_monthly.month IS
    'First day of the month, e.g. 2026-09-01 means September 2026.';
COMMENT ON COLUMN cpi_monthly.cpi_index IS
    'Headline CPI index, 2024 = 100.';
COMMENT ON COLUMN cpi_monthly.inflation_yoy IS
    'Inflation in %: change of cpi_index versus the same month of the previous year. NULL when that month is missing.';

-- ---------------------------------------------------------------------------
-- policy_events
-- ---------------------------------------------------------------------------
CREATE TABLE policy_events (
    announced_date  DATE NOT NULL,
    effective_date  DATE NOT NULL,
    rate_type       TEXT NOT NULL CHECK (rate_type IN ('refinancing', 'rediscount')),
    old_rate        NUMERIC(5, 2) NOT NULL,
    new_rate        NUMERIC(5, 2) NOT NULL,
    direction       TEXT NOT NULL CHECK (direction IN ('cut', 'hike')),
    document_no     TEXT,
    source_url      TEXT,
    notes           TEXT,
    PRIMARY KEY (announced_date, rate_type),
    CHECK (effective_date >= announced_date),
    CHECK ((direction = 'cut' AND new_rate < old_rate)
        OR (direction = 'hike' AND new_rate > old_rate))
);

COMMENT ON TABLE policy_events IS
    'Changes of SBV (State Bank of Vietnam) refinancing and rediscount rates since 2020, hand-checked. One row per rate type per decision; count DISTINCT announced_date for the number of decisions.';
COMMENT ON COLUMN policy_events.announced_date IS
    'Date the SBV decision was signed / announced.';
COMMENT ON COLUMN policy_events.effective_date IS
    'Date the new rate took effect. Use this for market reaction windows.';
COMMENT ON COLUMN policy_events.rate_type IS
    '''refinancing'' (lãi suất tái cấp vốn) or ''rediscount'' (lãi suất tái chiết khấu).';
COMMENT ON COLUMN policy_events.old_rate IS
    'Rate before the change, % per year.';
COMMENT ON COLUMN policy_events.new_rate IS
    'Rate after the change, % per year.';
COMMENT ON COLUMN policy_events.direction IS
    '''cut'' (giảm) or ''hike'' (tăng).';
COMMENT ON COLUMN policy_events.document_no IS
    'SBV decision number, e.g. ''1123/QĐ-NHNN''; NULL if not found.';
COMMENT ON COLUMN policy_events.source_url IS
    'URL of the source used to record the row (sbv.gov.vn when available, else news).';
COMMENT ON COLUMN policy_events.notes IS
    'Source caveats and other rates changed by the same decision (overnight rate, deposit and lending caps).';
