# Test-set results (2026-11-17 12:45)

- questions: eval/test_questions.csv
- model: gpt-6-luna
- router prompt: 06a978dfa06c
- answer prompt: 5c4f293ef616

## agent

- All 40: correct 30 (75%) / partial 6 (15%) / wrong 4 (10%)
- sql (16): correct 11 (69%) / partial 2 (12%) / wrong 3 (19%)
- rag (16): correct 12 (75%) / partial 4 (25%) / wrong 0 (0%)
- both (4): correct 3 (75%) / partial 0 (0%) / wrong 1 (25%)
- out_of_scope (4): correct 4 (100%) / partial 0 (0%) / wrong 0 (0%)
- Router accuracy: 37/40 (92%)
- Mean time 10350 ms, mean cost $0.000646, total $0.025844, errors 0

## rag_only

- All 40: correct 14 (35%) / partial 7 (18%) / wrong 19 (48%)
- sql (16): correct 2 (12%) / partial 1 (6%) / wrong 13 (81%)
- rag (16): correct 9 (56%) / partial 6 (38%) / wrong 1 (6%)
- both (4): correct 0 (0%) / partial 0 (0%) / wrong 4 (100%)
- out_of_scope (4): correct 3 (75%) / partial 0 (0%) / wrong 1 (25%)
- Mean time 4858 ms, mean cost $0.000504, total $0.020144, errors 0

Grading cost $0.011171 (errors 0).
