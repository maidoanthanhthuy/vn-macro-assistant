# Test-set evaluation (Phase 5)

Official run on 2026-11-17 over `eval/test_questions.csv` (40 questions written fresh in
Phase 5, never used for tuning). Each question was answered once by each mode and each
answer was graded once by an LLM (`gpt-6-luna`, `prompts/grade.md`, verdict correct /
partial / wrong). The test set was not run again after this.

- **Agent:** router -> period resolver -> RAG (period filter) and/or Text-to-SQL ->
  answer step. Router prompt `06a978dfa06c`, answer prompt `5c4f293ef616`.
- **RAG-only baseline:** every question goes to document search over all documents (no
  router, no period filter, no SQL), then the same answer step.

Raw results: `test_results.jsonl` (80 rows), `test_summary.md` / `.json` (original
grades), `test_regrade.jsonl` (two corrected references), `human_check.md`.

## Scores

Counts are correct / partial / wrong.

| Expected route (n) | Agent, original | Agent, corrected refs | RAG-only |
|---|---|---|---|
| **All (40)** | **30 / 6 / 4** (75% / 15% / 10%) | **32 / 6 / 2** (80% / 15% / 5%) | **14 / 7 / 19** (35% / 18% / 48%) |
| sql (16) | 11 / 2 / 3 | 12 / 2 / 2 | 2 / 1 / 13 |
| rag (16) | 12 / 4 / 0 | 12 / 4 / 0 | 9 / 6 / 1 |
| both (4) | 3 / 0 / 1 | 4 / 0 / 0 | 0 / 0 / 4 |
| out_of_scope (4) | 4 / 0 / 0 | 4 / 0 / 0 | 3 / 0 / 1 |

### Corrected reference answers (after the run, grader only)

Two reference answers were incomplete. They were fixed in `eval/test_questions.csv`
(reason written in the notes) and only these answers were graded again; the agent was not
run again. Both RAG-only answers to these questions stay wrong (they say data is missing).

- **t04** (VN30 highest in 2021): the reference listed the highest close (1,572.46 on
  2021-11-25) with that day's intraday high (1,579.56), missing the year's highest
  intraday high (1,587.00 on 2021-11-26). The agent answered 1,587 on 2021-11-26:
  wrong -> correct.
- **t36** (credit growth in the first 9 months of 2026): the reference had only the SBV
  figure (11.59% by 30/9/2026). The agent gave the NSO figure (10.89% by 28/9/2026,
  `nso_report_2026_09_040`) with its date: wrong -> correct.

## Router

37 / 40 correct (92%). Misses: t09 (2025 exchange rate, intentionally missing) and t17
(2023 lending rate, in the data) were sent to `out_of_scope`; t14 (September 2026
inflation and VN-Index) was sent to `sql` instead of `both` but answered correctly (IMF
has September).

## Human check

10 answers drawn at random (seed 20261117) from both modes (3 agent, 7 RAG-only), graded
blind by the project owner. Agreement with the LLM grade: **8 / 10**.

| Item | Question | Mode | Human | LLM |
|---|---|---|---|---|
| 1 | t10 refinancing rate now | agent | partial | partial |
| 2 | t02 MB Bank yesterday | rag_only | partial | partial |
| 3 | t15 Thủ Đức rents | rag_only | **correct** | **wrong** |
| 4 | t13 Directive 01 credit | rag_only | correct | correct |
| 5 | t14 inflation + VN-Index Sep | rag_only | wrong | wrong |
| 6 | t22 FDI 7 months | rag_only | correct | correct |
| 7 | t20 highest inflation 2023 | agent | correct | correct |
| 8 | t38 Vingroup news | rag_only | correct | correct |
| 9 | t23 passenger transport | agent | **correct** | **partial** |
| 10 | t30 banks cutting deposit rates | rag_only | correct | correct |

Both disagreements are stricter LLM grades: t15 (the answer said plainly there is no data
but did not phrase it as a refusal) and t23 (missing four-month figures that the question
did not ask for, but that the reference listed). With the two reference errors above, the
LLM grades lean strict, so the scores are, if anything, slightly low.

## Cost and time

| | Mean time / question | Mean cost / question | Total |
|---|---|---|---|
| Agent | 10.4 s | $0.00065 | $0.0258 |
| RAG-only | 4.9 s | $0.00050 | $0.0201 |
| LLM grading (80 + 4 calls) | - | $0.00014 | $0.0117 |
| **Whole run** | | | **$0.058** |

## Known issues fixed after the test run

Fixed for the deployed version and checked on the dev set only (`eval/seed_questions.csv`,
four questions q26-q29 added for these checks). The test scores above are from before
these fixes.

1. **"Hôm qua" / "hôm nay" (t02).** Text-to-SQL took "yesterday" as the second-latest row
   (`OFFSET 1`) and returned 2026-11-09. Now the agent passes today's date to Text-to-SQL,
   the SQL conventions define these as calendar days (latest trading day on or before
   that day), and the answer says when the asked day has no data and gives the latest
   date. The router also treats a daily close for a named day as `sql`, not as a
   real-time price. Dev q26 ("Hôm nay VN-Index đóng cửa bao nhiêu điểm?"): "17/11/2026
   chưa có dữ liệu; mức gần nhất 1.743,07 điểm ngày 10/11/2026".
2. **Missing data vs out of scope (t09, t17).** The router prompt now lists every
   indicator in the numeric tables (read from the `indicators` table) and says that a
   listed indicator is in scope for any year, even one not in the data yet. Dev router
   29 / 29 in two runs, including q27 (M2 2024, missing -> `sql`, "data only to 2022") and
   q28 (2023 exchange rate -> `sql`, 23.787,32 đồng/USD).
3. **Hedging on supported data (t10).** The answer prompt forbids doubts such as "chưa
   xác minh" when the data answers the question, and the SQL conventions say the current
   policy rate is the new rate of its latest change (policy_events lists every change).
   Dev q29 ("Lãi suất tái chiết khấu hiện nay"): "hiện là 3%, áp dụng từ ngày 19/06/2023".
4. **Percentage points (t31).** A change between two percentages is written as "điểm phần
   trăm", even when the source writes "%". Checked on a made-up excerpt ("tăng 0,40%" ->
   "tăng 0,40 điểm phần trăm").

Regression checks on the dev set after the fixes: Text-to-SQL dev runner 13 / 13 PASS on
the questions with reference SQL (q16 graded in Phase 4, unchanged); full agent 29 / 29
answered without errors.
