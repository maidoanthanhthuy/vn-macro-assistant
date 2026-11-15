# SQL conventions

Rules for writing PostgreSQL queries against the database described above.

## Output
- Return exactly one SELECT statement (a WITH ... SELECT is allowed). No other statements.
- No trailing semicolon.
- Always end with LIMIT, at most 200 rows.
- Do not round in SQL; return full precision. Rounding is done when the answer is written.
- Every percentage column in the result is in percent units, like
  cpi_monthly.inflation_yoy: 5.08 means 5.08%, and a 15% rise is 15, not 0.15.

## Transparency
- Return the inputs of every calculation, not only the final number. Example for a
  return: start_date, start_close, end_date, end_close, pct_change.
- Return the dates actually used, so the answer can state the date range.
- For macro values, also return indicators.source, and is_forecast and vintage from
  macro_annual, so the answer can name the source and flag forecasts.

## Relative time
- "Latest", "current", "today", "this year" ("gần nhất", "hiện tại", "hôm nay",
  "năm nay") refer to the data, never to CURRENT_DATE or now().
- Example: "today's price" of a symbol = the row with the largest date in daily_prices
  for that symbol. "Latest month" of CPI = MAX(month) in cpi_monthly.
- Always return the actual date used.

## Prices and returns
- Stock prices are adjusted for dividends and bonus shares; use them for all percentage
  changes. Volume is the real traded volume (not adjusted).
- Returns are close-to-close, in percent.
- Period return (year, quarter, month):
  pct_change = (end_close / start_close - 1) * 100, where:
  - end = last trading day in the period: MAX(date) <= last calendar day of the period.
  - start = last trading day before the period: MAX(date) < first calendar day of the
    period.
  - Never hard-code trading dates such as 31 December; find them with MAX(date).
- If there is no close before the period (first period with data), start from the
  first close in the period (MIN(date) in the period) and return that date, so the
  answer can say the period is incomplete.
- "N months after event X" starts from the first trading day on or after the event date.

## Symbols
- Find a symbol by name with a whole-name match on symbols.aliases, as described in the
  column comment: ', ' || aliases || ',' ILIKE '%, <name>,%'. Never a plain substring
  match.

## Macro data and sources
- Default source when the user does not name one:
  - Past years (annual macro): World Bank.
  - Future years: IMF WEO (rows with is_forecast = true).
  - Monthly inflation: IMF CPI (cpi_monthly).
- If the user names a source, use exactly that source.
- Forecast values are rows with is_forecast = true; always return is_forecast and
  vintage with them. Never compute a forecast in SQL.
- Inflation = year-over-year % change of the CPI index versus the same month of the
  previous year (cpi_monthly.inflation_yoy).
- If the asked month is not in cpi_monthly yet, the answer will come from the NSO monthly
  report (documents); the query returns the latest available month instead of guessing.

## Missing data
- If the data cannot answer the question (period outside the data range, indicator not
  in the database), do not guess or estimate. Either return a query that shows the
  available range (e.g. MIN/MAX of the period column), or report that the question
  cannot be answered with SQL.
