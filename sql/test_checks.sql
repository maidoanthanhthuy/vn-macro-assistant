-- Reference SQL for the test set (eval/test_questions.csv). Phase 5.
-- Run as the owner or vnmacro_reader. One block per question with a SQL part, headed
-- "-- tNN: ...". Conventions: docs/SCOPE.md section 4 (returns close-to-close from the
-- last close before the period; adjusted prices; default sources).
-- The test set is run through the agent only once, for the official score.

-- t01: FPT return in 2023 (close-to-close).
WITH p AS (
    SELECT
        (SELECT close FROM daily_prices WHERE symbol = 'FPT' AND date < DATE '2023-01-01'
         ORDER BY date DESC LIMIT 1) AS start_close,
        (SELECT close FROM daily_prices WHERE symbol = 'FPT' AND date < DATE '2024-01-01'
         ORDER BY date DESC LIMIT 1) AS end_close
)
SELECT start_close, end_close, round((end_close / start_close - 1) * 100, 2) AS pct_change
FROM p;

-- t02: MBB close "yesterday" = latest trading day on or before yesterday. The answer
-- depends on the run date; with the 2026-11-10 snapshot it is the 2026-11-10 close, and
-- the answer must say that day is the latest available.
SELECT date, close
FROM daily_prices
WHERE symbol = 'MBB' AND date <= CURRENT_DATE - 1
ORDER BY date DESC
LIMIT 1;

-- t03: VCB vs TCB return in 2025.
SELECT symbol,
       round((max(close) FILTER (WHERE date = last_2025) /
              max(close) FILTER (WHERE date = last_2024) - 1) * 100, 2) AS pct_change
FROM daily_prices,
     LATERAL (SELECT max(date) AS last_2024 FROM daily_prices d
              WHERE d.symbol = daily_prices.symbol AND d.date < DATE '2025-01-01') a,
     LATERAL (SELECT max(date) AS last_2025 FROM daily_prices d
              WHERE d.symbol = daily_prices.symbol AND d.date < DATE '2026-01-01') b
WHERE symbol IN ('VCB', 'TCB') AND date IN (last_2024, last_2025)
GROUP BY symbol
ORDER BY pct_change DESC;

-- t04: VN30 highest close in 2021 and its date (intraday high shown for reference).
SELECT date, close, high
FROM daily_prices
WHERE symbol = 'VN30' AND date >= DATE '2021-01-01' AND date < DATE '2022-01-01'
ORDER BY close DESC
LIMIT 1;

-- t05: GDP growth 2019, World Bank (default source for past years).
SELECT year, value AS gdp_growth_pct
FROM macro_annual
WHERE indicator_code = 'NY.GDP.MKTP.KD.ZG' AND year = 2019;

-- t06: unemployment, recent years (World Bank, ILO modeled), last 5 years available.
SELECT year, value AS unemployment_pct
FROM macro_annual
WHERE indicator_code = 'SL.UEM.TOTL.ZS'
ORDER BY year DESC
LIMIT 5;

-- t07: IMF WEO forecasts 2026-2031, highest first.
SELECT year, value AS gdp_growth_pct, is_forecast, vintage
FROM macro_annual
WHERE indicator_code = 'NGDP_RPCH' AND year BETWEEN 2026 AND 2031
ORDER BY value DESC, year;

-- t08: inflation March 2026, IMF CPI (y/y).
SELECT month, round(inflation_yoy, 2) AS inflation_pct
FROM cpi_monthly
WHERE month = DATE '2026-03-01';

-- t09: exchange rate 2025 is missing (World Bank ends 2024); latest available year.
SELECT year, value AS vnd_per_usd
FROM macro_annual
WHERE indicator_code = 'PA.NUS.FCRF'
ORDER BY year DESC
LIMIT 2;

-- t10: current refinancing rate = new_rate of the latest refinancing-rate change.
SELECT announced_date, effective_date, new_rate AS refinancing_rate_pct
FROM policy_events
WHERE rate_type = 'refinancing'
ORDER BY announced_date DESC
LIMIT 1;

-- t14: SQL part: IMF inflation Sep 2026 and VN-Index return in Sep 2026.
SELECT
    (SELECT round(inflation_yoy, 2) FROM cpi_monthly WHERE month = DATE '2026-09-01')
        AS imf_inflation_pct,
    round(((SELECT close FROM daily_prices WHERE symbol = 'VNINDEX' AND date < DATE '2026-10-01'
            ORDER BY date DESC LIMIT 1) /
           (SELECT close FROM daily_prices WHERE symbol = 'VNINDEX' AND date < DATE '2026-09-01'
            ORDER BY date DESC LIMIT 1) - 1) * 100, 2) AS vnindex_pct_change;

-- t16: FDI net inflows, % of GDP, 2022 (World Bank).
SELECT year, round(value, 2) AS fdi_pct_gdp
FROM macro_annual
WHERE indicator_code = 'BX.KLT.DINV.WD.GD.ZS' AND year = 2022;

-- t17: average lending rate 2023 (World Bank).
SELECT year, round(value, 2) AS lending_rate_pct
FROM macro_annual
WHERE indicator_code = 'FR.INR.LEND' AND year = 2023;

-- t18: Masan's best year 2018-2025 (yearly close-to-close returns).
WITH year_end AS (
    SELECT DISTINCT ON (extract(year FROM date)) extract(year FROM date)::int AS year, close
    FROM daily_prices
    WHERE symbol = 'MSN' AND date < DATE '2026-01-01'
    ORDER BY extract(year FROM date), date DESC
)
SELECT year, round((close / lag(close) OVER (ORDER BY year) - 1) * 100, 2) AS pct_change
FROM year_end
ORDER BY year;

-- t19: IMF CPI index level (2024 = 100) for December 2025.
SELECT month, round(cpi_index, 2) AS cpi_index
FROM cpi_monthly
WHERE month = DATE '2025-12-01';

-- t20: month of 2023 with the highest y/y inflation (IMF CPI).
SELECT month, round(inflation_yoy, 2) AS inflation_pct
FROM cpi_monthly
WHERE month >= DATE '2023-01-01' AND month < DATE '2024-01-01'
ORDER BY inflation_yoy DESC
LIMIT 1;

-- t21: HPG session with the largest volume in 2024.
SELECT date, volume, close
FROM daily_prices
WHERE symbol = 'HPG' AND date >= DATE '2024-01-01' AND date < DATE '2025-01-01'
ORDER BY volume DESC
LIMIT 1;

-- t35: SQL part: VN-Index return in Q3 2026.
SELECT
    round(((SELECT close FROM daily_prices WHERE symbol = 'VNINDEX' AND date < DATE '2026-10-01'
            ORDER BY date DESC LIMIT 1) /
           (SELECT close FROM daily_prices WHERE symbol = 'VNINDEX' AND date < DATE '2026-07-01'
            ORDER BY date DESC LIMIT 1) - 1) * 100, 2) AS vnindex_pct_change;

-- t36: SQL part: VCB return over the first 9 months of 2026.
SELECT
    round(((SELECT close FROM daily_prices WHERE symbol = 'VCB' AND date < DATE '2026-10-01'
            ORDER BY date DESC LIMIT 1) /
           (SELECT close FROM daily_prices WHERE symbol = 'VCB' AND date < DATE '2026-01-01'
            ORDER BY date DESC LIMIT 1) - 1) * 100, 2) AS vcb_pct_change;

-- t37: SQL part: IMF inflation June 2026 (y/y).
SELECT month, round(inflation_yoy, 2) AS imf_inflation_pct
FROM cpi_monthly
WHERE month = DATE '2026-06-01';
