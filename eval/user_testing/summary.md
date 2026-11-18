# User test: findings and changes

## Setup

- Deployed app (Streamlit Cloud) on Neon Postgres with the OpenAI embedding backend.
- **8 people** took part. Baseline: 2026-11-17 08:23:24 UTC (15:23 Asia/Ho_Chi_Minh);
  every `app.query_log` / `app.feedback` row after it comes from the test. Snapshot:
  2026-11-18 13:45 (all times below are Asia/Ho_Chi_Minh).
- **Sessions are not people.** A session id is a random uuid4 made each time the app
  opens, so one person who reloads the page gets a new session, and the first 23
  questions were asked before session ids existed. Round 2 has 9 sessions from 8 or
  fewer people; 4 of them have only 1-3 questions (suggested questions or a quick
  try), so 5 sessions plus the round-1 block hold almost all real use.
- Rows removed before counting: 10 questions identical to the official test set
  (9 deleted on 2026-11-17 19:55, 1 on 2026-11-18), with their log and feedback rows.
  Two feedback rows still point to deleted questions; they are left out of the counts
  but their comments are used below.
- Numbers come from read-only queries on Neon (owner role). Every question, with its
  route, status, answer (when logged) and feedback, is in
  [questions.csv](questions.csv) (no session ids). Rows in its `review` column mention
  the user's own situation and should be checked before the file is shared.

## Timeline of changes during the test

"Live" is the first logged question that used the new code; the app redeploys on
every push to `main`.

| Pushed | Live | Commit | Change |
|---|---|---|---|
| 11-17 15:03 | 15:23 (baseline) | bd57dd1 | App with feedback, connection pool, step status |
| 11-17 18:07 | 19:05 | 94d974c | Anonymous `session_id`; request ids made thread-local (fixes shared ids under concurrent use) |
| 11-17 18:58 | 19:05 (router prompt 7eacfe7053d4) | 3481693 | Route `explain`; data scope on refusals; ticker match on `symbols.symbol`; "current price" = latest close |
| 11-17 20:27 | 20:31 (router prompt 82a1bf5dace7) | fe642b6 | `answer_text` logged; follow-up questions (last 2 turns, `standalone_question`); why a stock moved -> `sql` |
| not yet | not yet | (11-18, not pushed) | Market overview, suggestion picked by code, knowledge why-questions -> `explain`, at most 3 explained terms; partly answerable questions get SQL; questions run in worker threads (feedback no longer stops them) |

No questions were asked between 17:41 and 19:05, so both 18:07 and 18:58 pushes went
live before round 2 started.

## Two rounds

Round 1 is before route `explain` existed; round 2 is after (both 3481693 and, from
20:31, fe642b6).

| | Round 1 (11-17 17:04-17:41) | Round 2 (11-17 19:05 - 11-18 11:33) |
|---|---|---|
| Questions | 23 | 43 (17 before 20:31, 26 after) |
| Sessions | no ids | 9 |
| Route `sql` | 11 (48%) | 22 (51%) |
| Route `out_of_scope` | 12 (52%) | 10 (23%) |
| Route `rag` | 0 | 6 (14%) |
| Route `explain` | (did not exist) | 3 (7%) |
| Route `both` | 0 | 2 (5%) |
| Step errors (`status = 'error'`) | 0 | 0 |
| Text-to-SQL `cannot_answer` | 1 | 5 |
| No answer (run interrupted) | 0 | 1 |
| Declined or data missing | 13 (57%): 12 out of scope + 1 cannot_answer | 20 (47%): 19 with `declined = true` + 1 no answer |
| ... of which the agent missed data or a better route | 2 | 10 (+1 interrupted) |
| Feedback | 18: 14 up, 4 down (78% up) | 18: 13 up, 5 down (72% up) |

Round 1 has no `declined` flag (added in 3481693); its count is out_of_scope plus
cannot_answer.

What changed between the rounds: users in round 2 asked more about the economy
(inflation, GDP, FDI, wages, firms) and asked many follow-ups, so `rag` and `both`
appear and the out-of-scope share halved. The thumbs-up share stayed about the same;
most thumbs-down in both rounds are on refusals.

## Declined or missing-data questions

### Round 1 (13)

| Kind | Questions | Verdict |
|---|---|---|
| Unrelated topic | Python "hello world", Python code for stock data, an English jailbreak prompt, "spacex", "vinaphone" | Correct refusal |
| Data the app never holds | Real estate prices (2), Nvidia, VNG (not one of the 15 stocks) | Correct |
| Personal advice | "vàng đang xuống có nên mua", "có ít tiền nên học đầu tư vào đâu" | Correct |
| Beginner concept | "mua cổ phiếu ở đâu có bị mất tiền", "đầu cơ là gì" | **Missed**: no `explain` route yet. Fixed in 3481693 |

### Round 2 (20)

| Kind | Questions | Verdict |
|---|---|---|
| Personal advice | "bây giờ nên bắt đầu đầu tư chứng khoán không", "cổ phiếu fd ... nên vào mã nào" | Correct (both offer past data instead) |
| Unrelated topic or career | "có thông tin về AI không" (ambiguous: "AI" or "ai" = who), courses/books to become an investment banker | Correct |
| Data really missing | Registered FDI capital 2018 (World Bank holds net inflows only; NSO documents start 11/2025), VNG, an inflation forecast (only GDP growth is forecast), world inflation, GDP per capita / "is Vietnam rich" | Correct; the answers say what is missing and give what exists |
| Knowledge question routed `out_of_scope` | "tiền tệ nào có giá trị nhất thế giới", "tại sao vàng thế giới với Việt Nam chênh nhau", "vốn nhỏ tham gia hàng hoá phái sinh thế nào, làm IB có phải cách tốt" | **Missed**: should be `explain` (the last one partly advice). Fixed on 11-18, not deployed |
| Why a stock moved / follow-up | "tại sao vingroup tăng nhanh", "diễn biến như nào", "sau đó tăng 736,5% năm 2025 ... vingroup sao cao" | **Missed** (19:15-19:18, before fe642b6). Fixed in fe642b6 |
| Data exists but not found | "dự báo GDP 2031 có tin được không" (cannot_answer, though the IMF 2031 forecast is in the table; the next turn "số liệu không có à" got 5,7%); "lương trung bình" and the wage part of "GDP tăng nhanh ... lương không tăng" (quarterly average income is in the quarter-end NSO reports, but retrieval used the October report only); "giá cổ phiếu ngân hàng nào ổn nhất" (prices exist; could compare volatility, though close to advice) | **Missed**. The GDP 2031 case is fixed on 11-18 (fix 12); the other two are known limitations |
| Run interrupted | "vậy tổng số vốn FDI đăng ký 2018" | **Bug**: a thumbs click at the same second re-ran the Streamlit script and stopped the request; the user retyped it. Fixed on 11-18 (fix 13) |

## Follow-up questions

| Time | Question | Previous turn | Rewritten / result | Context understood? |
|---|---|---|---|---|
| 11-17 19:08 | vậy giá cổ phiếu ngân hàng nào ổn nhất | strongest currency | (no context support yet) cannot_answer | Stands alone; "vậy" adds nothing |
| 11-17 19:15 | diễn biến như nào | why Vingroup rose | out_of_scope, thumbs down, comment "mới hỏi ở trên mà" | **No** (before fe642b6); user retyped "diễn biến cổ phiếu vingroup" |
| 11-17 19:17 | diễn biến vingroup vài năm gần đây nữa | Vingroup move | sql, ok, thumbs up | Yes (names the stock) |
| 11-17 19:18 | sau đó tăng 736,5% năm 2025 nói cụ thể vingroup sao cao quá vậy | Vingroup move | out_of_scope, thumbs down, "phạm vi gì hẹp vậy" | **No** (why-question; fixed in fe642b6) |
| 11-17 19:22 | vậy tổng số vốn FDI đăng ký 2018 | FDI 2018 | interrupted (see above) | - |
| 11-17 20:32 | năm đó biến động nào lớn nhất | CPI and VN-Index 10/2023 | "Trong năm 2023, CPI hay VN-Index biến động lớn hơn?"; answered, thumbs up | Yes |
| 11-17 20:35 | lương trung bình | firms opened/closed 10/2026 | "Lương trung bình trong tháng 10/2026 là bao nhiêu?"; "not in the report", thumbs down | Partly: carrying the month over made retrieval miss the quarterly figure |
| 11-17 20:38 | dự báo tương lai có gì | deflation in Vietnam | "Dự báo lạm phát hoặc giảm phát ở Việt Nam ...?"; says no inflation forecast | Yes |
| 11-17 20:40 | số liệu không có à | GDP 2031 forecast | rewritten with GDP 2031 + "rich"; answered 5,7% (IMF) | Yes; it corrected the previous miss |
| 11-17 20:42 | xếp hạng đi nhé | most traded stock this year | "Xếp hạng các cổ phiếu theo khối lượng giao dịch trong năm nay"; full ranking, thumbs up | Yes; comment: tickers alone are hard to recognise |
| 11-18 09:00 | Dow giảm ... còn cái này là gì | foreign net selling | kept as is; explain | Yes (pasted news, standalone) |
| 11-18 11:33 | trả lời đầy đủ | market overview (one-day answer) | "Hãy trả lời đầy đủ về tình hình thị trường cổ phiếu tại Việt Nam"; long list of 15 stocks, thumbs down | Context yes; answer shape no (fixed on 11-18: trend answer) |

With fe642b6 live, 7 of 7 follow-ups were resolved to the right topic; the problems
left are in the answers (missing quarterly data, an unhelpful list), not in the
rewrite.

## Findings and fixes

Round 1 (fixed in 94d974c, 3481693):

1. Beginner concept questions were refused (no route for general knowledge) -> route
   `explain` (2-4 sentences, no numbers, no advice, a general-knowledge note and a
   suggested question).
2. Users did not know what data the app holds (real estate, gold, Nvidia, VNG; one
   asked whether the data stops in 2017) -> the data scope (built from the database)
   is appended to every refusal and shown on the main screen.
3. Concurrent questions shared a `request_id` (one cached agent stored the id on
   itself; 2 pairs in round 1) -> thread-local ids. Questions could not be grouped by
   session -> anonymous `session_id`.
4. Lower-case tickers and "giá hiện tại" failed or were refused -> ticker match on
   `symbols.symbol` (12 of 18 symbols do not list their ticker in `aliases`), current
   price = latest close.

Round 2, first part (fixed in fe642b6):

5. Follow-ups ("diễn biến như nào") were read alone and refused -> the router gets the
   last 2 turns and writes a `standalone_question` used by every later step.
6. Why a stock moved was refused -> `sql` gives the move and says the reasons (news,
   reports) are not in the data.
7. Answers were not logged -> `answer_text`.

Round 2, second part (fixed on 11-18 in the code, **not deployed yet**):

8. "Tình hình thị trường" got a one-day VN-Index answer, and "trả lời đầy đủ" a list of
   every stock -> SQL convention and example for a market overview (VN-Index over 1
   week, 1 month, year to date + top 3 / bottom 3 stocks over the month); the answer
   gives the trend in 2-3 sentences.
9. The `explain` suggestion was written by the LLM and could be a question the app
   cannot answer (US indices) -> code picks one of the app's suggested questions by
   keyword topic (inflation, rates/banks, exports/GDP; default VN-Index).
10. Knowledge why/how questions outside the data (gold price gap, currencies) went
    `out_of_scope` -> `explain`; `out_of_scope` is only for advice, data the app never
    holds, or topics outside finance and the economy.
11. "Giải thích thêm" was long (6 terms on one answer, "cổ phiếu", "phiên giao dịch")
    -> at most 3 specialised terms on every route (prompt + code limit).

12. A question with a data part and a judgment part ("dự báo GDP 2031 có tin được
    không, Việt Nam có giàu không") got cannot_answer (3/3 runs locally): the
    Text-to-SQL prompt listed "opinion" as a reason for cannot_answer, so the whole
    question was refused although the model's own reason said the 2031 IMF forecast
    exists. The rule is now general: cannot_answer only when no part can be answered;
    otherwise SQL for the data part and a note on the rest (3/3 runs return the
    forecast). Dev question q40 with a reference SQL.
13. A feedback click while an answer was running stopped it: the agent ran in the
    Streamlit script thread, and a click re-runs the script. Questions now run in a
    worker thread; the job stays in session state, so a rerun only redraws the
    progress and the next run keeps waiting. The question box is disabled while a
    question runs. Checked with Streamlit AppTest (a job started in an earlier run is
    picked up and its answer added to the history), not with a real browser click.

Dev-set check for 8-12 (local database, 40 questions with 5 new ones, q36-q40):
router 40/40 (prompt 737f165de62d); agent 0 errors, $0.0005 and 9.4 s per question;
Text-to-SQL 14/14 PASS on questions with a reference SQL (q40 returns the 5,7% IMF
forecast and the answer says the data cannot judge reliability or wealth). q36 answers
with the 1-week / 1-month / year-to-date trend and the top 3 / bottom 3 stocks, q37-q39
go to `explain` with a suggestion from the app's list. The wage limitation below was
checked: "thu nhập bình quân của người lao động quý 3/2026" is answered (9,2 triệu
đồng/tháng, September report). The official test set was not re-run.

## Known limitations

- **Average wages ("lương trung bình").** Average income of workers is published only
  in the quarter-end NSO reports (March, June, September, December), and the app has
  no wage series in its tables. A question without a period is searched in the latest
  monthly report (October 2026), which has no wage figure, so the answer says the
  number is missing although the September report holds the Q3 figure. Asking for a
  quarter ("thu nhập bình quân quý 3/2026") finds it.
- **Subjective rankings ("cổ phiếu ngân hàng nào ổn nhất").** "Ổn", "tốt", "an toàn"
  have no single measure in the data. The app can give facts such as returns or price
  swings over a period, but it does not pick the "best" or "safest" stock, which would
  be advice. Such questions get cannot_answer or a refusal with the data scope.

## Still open

- Ranking answers show tickers only ("ghi tắt không nhớ của ai"): add company names.
- Policy rate answers should say "%/năm" and give the decision number (comment on a
  deleted test-set question).
- FDI answer wording read backwards in one answer ("2018 đạt 5%; thấp hơn 4,56%").
- Concept suggestions repeat the default VN-Index question for most `explain` answers;
  more topics could be added.
