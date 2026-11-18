# SQL examples

Worked examples of questions and the SQL that answers them. They show patterns; the
symbols, periods and indicators are only illustrations.

## Example 1: latest close of a stock named by the user

Question: Giá cổ phiếu Thế Giới Di Động hiện tại là bao nhiêu?

```sql
SELECT p.symbol, s.name, p.date, p.close, s.price_unit
FROM daily_prices p
JOIN symbols s USING (symbol)
WHERE (upper(s.symbol) = upper('thế giới di động')
       OR ', ' || s.aliases || ',' ILIKE '%, thế giới di động,%')
  AND p.date = (SELECT max(date) FROM daily_prices WHERE symbol = p.symbol)
LIMIT 10
```

## Example 2: return of a stock over a quarter

Question: Cổ phiếu msn tăng hay giảm bao nhiêu phần trăm trong quý 2 năm 2024?

```sql
WITH target AS (
    SELECT symbol FROM symbols
    WHERE upper(symbol) = upper('msn') OR ', ' || aliases || ',' ILIKE '%, msn,%'
), period AS (
    SELECT DATE '2024-04-01' AS p_start, DATE '2024-06-30' AS p_end
), start_before AS (
    SELECT p.date, p.close
    FROM daily_prices p, target t, period
    WHERE p.symbol = t.symbol AND p.date < period.p_start
    ORDER BY p.date DESC
    LIMIT 1
), start_in AS (
    SELECT p.date, p.close
    FROM daily_prices p, target t, period
    WHERE p.symbol = t.symbol AND p.date BETWEEN period.p_start AND period.p_end
    ORDER BY p.date
    LIMIT 1
), end_row AS (
    SELECT p.date, p.close
    FROM daily_prices p, target t, period
    WHERE p.symbol = t.symbol AND p.date BETWEEN period.p_start AND period.p_end
    ORDER BY p.date DESC
    LIMIT 1
)
SELECT t.symbol,
       COALESCE(sb.date, si.date) AS start_date,
       COALESCE(sb.close, si.close) AS start_close,
       e.date AS end_date,
       e.close AS end_close,
       (e.close / COALESCE(sb.close, si.close) - 1) * 100 AS pct_change,
       sb.date IS NOT NULL AS full_period
FROM target t
CROSS JOIN end_row e
LEFT JOIN start_before sb ON TRUE
LEFT JOIN start_in si ON TRUE
LIMIT 1
```

## Example 3: annual macro value for a past year (default source: World Bank)

Question: Xuất khẩu chiếm bao nhiêu phần trăm GDP của Việt Nam năm 2021?

```sql
SELECT m.year, i.name, m.value, i.unit, i.source, m.is_forecast, m.vintage
FROM macro_annual m
JOIN indicators i USING (indicator_code)
WHERE m.indicator_code = 'NE.EXP.GNFS.ZS' AND m.year = 2021
LIMIT 1
```

## Example 4: forecast for a future year (default source: IMF WEO)

Question: Kinh tế Việt Nam năm 2030 được dự báo tăng trưởng bao nhiêu?

```sql
SELECT m.year, i.name, m.value, i.unit, i.source, m.is_forecast, m.vintage
FROM macro_annual m
JOIN indicators i USING (indicator_code)
WHERE m.indicator_code = 'NGDP_RPCH' AND m.year = 2030
LIMIT 1
```

## Example 5: latest monthly inflation (default source: IMF CPI)

Question: Lạm phát của Việt Nam hiện nay là bao nhiêu?

```sql
SELECT c.month, c.cpi_index, c.inflation_yoy, i.source
FROM cpi_monthly c
JOIN indicators i ON i.indicator_code = 'CPI'
WHERE c.month = (SELECT max(month) FROM cpi_monthly)
LIMIT 1
```

## Example 6: number of policy rate decisions in a period

Question: Năm 2020 Ngân hàng Nhà nước giảm lãi suất điều hành mấy lần?

```sql
SELECT count(DISTINCT announced_date) AS n_decisions,
       array_agg(DISTINCT announced_date ORDER BY announced_date) AS announced_dates
FROM policy_events
WHERE direction = 'cut'
  AND announced_date BETWEEN DATE '2020-01-01' AND DATE '2020-12-31'
LIMIT 1
```

## Example 7: general state of the market (trend + top moves)

Question: Dạo này chứng khoán Việt Nam thế nào rồi?

```sql
WITH last_day AS (
    SELECT max(date) AS end_date FROM daily_prices WHERE symbol = 'VNINDEX'
), periods AS (
    SELECT '1 week' AS period, end_date - 7 AS ref_date FROM last_day
    UNION ALL
    SELECT '1 month', (end_date - INTERVAL '1 month')::date FROM last_day
    UNION ALL
    SELECT 'year to date', make_date(extract(year FROM end_date)::int - 1, 12, 31)
    FROM last_day
), moves AS (
    SELECT per.period, s.symbol, s.name, s.asset_type,
           st.date AS start_date, st.close AS start_close,
           en.date AS end_date, en.close AS end_close,
           (en.close / st.close - 1) * 100 AS pct_change
    FROM periods per
    CROSS JOIN last_day l
    CROSS JOIN symbols s
    CROSS JOIN LATERAL (
        SELECT date, close FROM daily_prices
        WHERE symbol = s.symbol AND date <= per.ref_date
        ORDER BY date DESC LIMIT 1
    ) st
    CROSS JOIN LATERAL (
        SELECT date, close FROM daily_prices
        WHERE symbol = s.symbol AND date <= l.end_date
        ORDER BY date DESC LIMIT 1
    ) en
    WHERE s.symbol = 'VNINDEX'
       OR (s.asset_type = 'stock' AND per.period = '1 month')
), ranked AS (
    SELECT m.*,
           rank() OVER (PARTITION BY asset_type ORDER BY pct_change DESC) AS rank_up,
           rank() OVER (PARTITION BY asset_type ORDER BY pct_change) AS rank_down
    FROM moves m
)
SELECT CASE WHEN asset_type = 'index' THEN 'index'
            WHEN rank_up <= 3 THEN 'top gainer' ELSE 'top loser' END AS row_type,
       period, symbol, name, start_date, start_close, end_date, end_close, pct_change
FROM ranked
WHERE asset_type = 'index' OR rank_up <= 3 OR rank_down <= 3
ORDER BY row_type, start_date DESC, pct_change DESC
LIMIT 20
```
