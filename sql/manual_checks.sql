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
