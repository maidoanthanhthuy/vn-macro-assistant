-- Manual checks of the loaded data (Phase 1, step 5).
-- Each query answers one seed question in eval/seed_questions.csv (id in the header).
-- Conventions (docs/SCOPE.md section 4): returns are close-to-close, in percent, using
-- the last trading day of each period. Run with:
--   docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < sql/manual_checks.sql

-- q01: VN-Index close on the last trading day of 2025.
SELECT date, close
FROM daily_prices
WHERE symbol = 'VNINDEX' AND date <= '2025-12-31'
ORDER BY date DESC
LIMIT 1;

-- q02: FPT % change in 2025 (last close of 2024 -> last close of 2025).
WITH start_row AS (
    SELECT date, close FROM daily_prices
    WHERE symbol = 'FPT' AND date <= '2024-12-31' ORDER BY date DESC LIMIT 1
), end_row AS (
    SELECT date, close FROM daily_prices
    WHERE symbol = 'FPT' AND date <= '2025-12-31' ORDER BY date DESC LIMIT 1
)
SELECT s.date AS start_date, s.close AS start_close,
       e.date AS end_date, e.close AS end_close,
       round((e.close / s.close - 1) * 100, 2) AS pct_change
FROM start_row s, end_row e;

-- q04: Vietnam GDP growth in 2023 according to the World Bank.
SELECT m.year, round(m.value, 2) AS gdp_growth_pct, i.source
FROM macro_annual m JOIN indicators i USING (indicator_code)
WHERE m.indicator_code = 'NY.GDP.MKTP.KD.ZG' AND m.year = 2023;

-- q05: average annual inflation 2019-2023 according to the World Bank (arithmetic mean).
SELECT count(*) AS n_years, round(avg(value), 2) AS avg_inflation_pct
FROM macro_annual
WHERE indicator_code = 'FP.CPI.TOTL.ZG' AND year BETWEEN 2019 AND 2023;

-- q06: average daily volume of HPG in Q1 2025.
SELECT count(*) AS trading_days, round(avg(volume)) AS avg_daily_volume
FROM daily_prices
WHERE symbol = 'HPG' AND date BETWEEN '2025-01-01' AND '2025-03-31';

-- q07: month of 2024 with the lowest VN-Index % change
-- (last close of the month vs last close of the previous month).
WITH month_end AS (
    SELECT DISTINCT ON (date_trunc('month', date))
           date_trunc('month', date)::date AS month, date, close
    FROM daily_prices
    WHERE symbol = 'VNINDEX' AND date BETWEEN '2023-12-01' AND '2024-12-31'
    ORDER BY date_trunc('month', date), date DESC
), returns AS (
    SELECT month, close,
           round((close / lag(close) OVER (ORDER BY month) - 1) * 100, 2) AS pct_change
    FROM month_end
)
SELECT month, close, pct_change
FROM returns
WHERE month >= '2024-01-01'
ORDER BY pct_change
LIMIT 3;

-- q21: IMF forecast of Vietnam real GDP growth for 2027 (label as forecast + vintage).
SELECT year, value AS gdp_growth_pct, is_forecast, vintage
FROM macro_annual
WHERE indicator_code = 'NGDP_RPCH' AND year = 2027;

-- Reality check: VCB, FPT, HPG closes on the last trading day of 2025 and on 2026-11-10.
SELECT symbol, date, close
FROM daily_prices
WHERE symbol IN ('VCB', 'FPT', 'HPG')
  AND date IN ((SELECT max(date) FROM daily_prices WHERE date <= '2025-12-31'), '2026-11-10')
ORDER BY symbol, date;

-- Reality check: inflation_yoy for 2026-09.
SELECT month, cpi_index, round(inflation_yoy, 2) AS inflation_yoy_pct
FROM cpi_monthly
WHERE month = '2026-09-01';

-- q23: VHM % change in 2018. First period with data: no close before 2018, so the return
-- starts from the first close in 2018 (2018-05-17) and the period is incomplete.
WITH start_before AS (
    SELECT date, close FROM daily_prices
    WHERE symbol = 'VHM' AND date < '2018-01-01' ORDER BY date DESC LIMIT 1
), start_in AS (
    SELECT date, close FROM daily_prices
    WHERE symbol = 'VHM' AND date BETWEEN '2018-01-01' AND '2018-12-31'
    ORDER BY date LIMIT 1
), end_row AS (
    SELECT date, close FROM daily_prices
    WHERE symbol = 'VHM' AND date BETWEEN '2018-01-01' AND '2018-12-31'
    ORDER BY date DESC LIMIT 1
)
SELECT coalesce(b.date, i.date) AS start_date, coalesce(b.close, i.close) AS start_close,
       e.date AS end_date, e.close AS end_close,
       round((e.close / coalesce(b.close, i.close) - 1) * 100, 2) AS pct_change,
       b.date IS NOT NULL AS full_period
FROM end_row e CROSS JOIN start_in i LEFT JOIN start_before b ON TRUE;

-- q03: bank with the largest % change in 2024 (last close of 2023 -> last close of 2024).
WITH banks AS (
    SELECT b.symbol,
           (SELECT close FROM daily_prices p WHERE p.symbol = b.symbol
              AND p.date <= '2023-12-31' ORDER BY p.date DESC LIMIT 1) AS start_close,
           (SELECT close FROM daily_prices p WHERE p.symbol = b.symbol
              AND p.date <= '2024-12-31' ORDER BY p.date DESC LIMIT 1) AS end_close
    FROM (VALUES ('VCB'), ('BID'), ('CTG'), ('TCB'), ('MBB'), ('VPB')) AS b (symbol)
)
SELECT symbol, start_close, end_close,
       round((end_close / start_close - 1) * 100, 2) AS pct_change
FROM banks
ORDER BY pct_change DESC
LIMIT 3;

-- q08: World Bank GDP growth and inflation 2020-2024, side by side.
SELECT year,
       round(max(value) FILTER (WHERE indicator_code = 'NY.GDP.MKTP.KD.ZG'), 2) AS gdp_growth_pct,
       round(max(value) FILTER (WHERE indicator_code = 'FP.CPI.TOTL.ZG'), 2) AS inflation_pct
FROM macro_annual
WHERE indicator_code IN ('NY.GDP.MKTP.KD.ZG', 'FP.CPI.TOTL.ZG') AND year BETWEEN 2020 AND 2024
GROUP BY year
ORDER BY year;

-- q15 (SQL part): VN-Index % change in the 3 months after the first 2023 cut. Start = first
-- trading day on or after the effective date 2023-03-15; end = last trading day on or
-- before 2023-03-15 + 3 months = 2023-06-15 (docs/SCOPE.md section 4).
WITH start_row AS (
    SELECT date, close FROM daily_prices
    WHERE symbol = 'VNINDEX' AND date >= '2023-03-15' ORDER BY date LIMIT 1
), end_row AS (
    SELECT date, close FROM daily_prices
    WHERE symbol = 'VNINDEX' AND date <= '2023-06-15' ORDER BY date DESC LIMIT 1
)
SELECT s.date AS start_date, s.close AS start_close, e.date AS end_date, e.close AS end_close,
       round((e.close / s.close - 1) * 100, 2) AS pct_change
FROM start_row s, end_row e;

-- q17 (SQL part): number of SBV rate hike decisions in 2022 and VN-Index % change in 2022.
WITH hikes AS (
    SELECT count(DISTINCT announced_date) AS n_hike_decisions FROM policy_events
    WHERE direction = 'hike' AND announced_date BETWEEN '2022-01-01' AND '2022-12-31'
), start_row AS (
    SELECT date, close FROM daily_prices
    WHERE symbol = 'VNINDEX' AND date <= '2021-12-31' ORDER BY date DESC LIMIT 1
), end_row AS (
    SELECT date, close FROM daily_prices
    WHERE symbol = 'VNINDEX' AND date <= '2022-12-31' ORDER BY date DESC LIMIT 1
)
SELECT h.n_hike_decisions, s.date AS start_date, s.close AS start_close,
       e.date AS end_date, e.close AS end_close,
       round((e.close / s.close - 1) * 100, 2) AS pct_change
FROM hikes h, start_row s, end_row e;

-- q22: GDP growth in 2028, no source named -> IMF WEO forecast (label as forecast + vintage).
SELECT year, value AS gdp_growth_pct, is_forecast, vintage
FROM macro_annual
WHERE indicator_code = 'NGDP_RPCH' AND year = 2028;

-- q16 (SQL part): % change of each of the 6 bank stocks in the latest month. Latest month =
-- newest month in any source: 2026-10 (NSO report; IMF CPI ends 2026-09). Hybrid: in Phase 4
-- the month comes from RAG. Last close before the month -> last close in the month.
SELECT b.symbol, s.date AS start_date, s.close AS start_close,
       e.date AS end_date, e.close AS end_close,
       round((e.close / s.close - 1) * 100, 2) AS pct_change
FROM (VALUES ('VCB'), ('BID'), ('CTG'), ('TCB'), ('MBB'), ('VPB')) AS b (symbol)
CROSS JOIN LATERAL (
    SELECT date, close FROM daily_prices p
    WHERE p.symbol = b.symbol AND p.date < '2026-10-01' ORDER BY p.date DESC LIMIT 1
) s
CROSS JOIN LATERAL (
    SELECT date, close FROM daily_prices p
    WHERE p.symbol = b.symbol AND p.date <= '2026-10-31' ORDER BY p.date DESC LIMIT 1
) e
ORDER BY b.symbol;
