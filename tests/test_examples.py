import re
from pathlib import Path

from vnmacro import config
from vnmacro.sql_agent import examples

MAX_LIMIT = 200
FAKE = """# SQL examples

## Example 1: a

Question: Câu một?

```sql
SELECT 1
LIMIT 1
```

## Example 2: b

Question: Câu hai?

```sql
WITH x AS (SELECT 2 AS v)
SELECT v FROM x
LIMIT 5
```
"""


def test_parse_examples():
    pairs = examples.parse_examples(FAKE)
    assert pairs == [
        ("Câu một?", "SELECT 1\nLIMIT 1"),
        ("Câu hai?", "WITH x AS (SELECT 2 AS v)\nSELECT v FROM x\nLIMIT 5"),
    ]


def test_examples_file_follows_output_rules():
    # The prompt file ships with the repo (not data); check its SQL shape.
    pairs = examples.parse_examples(
        Path(config.SQL_EXAMPLES_FILE).read_text(encoding="utf-8")
    )
    assert len(pairs) == 6
    for question, sql in pairs:
        assert question
        assert re.match(r"(SELECT|WITH)\b", sql, re.I), question
        assert ";" not in sql, question  # one statement, no trailing semicolon
        last = re.search(r"\bLIMIT\s+(\d+)\s*$", sql, re.I)
        assert last and int(last.group(1)) <= MAX_LIMIT, question
