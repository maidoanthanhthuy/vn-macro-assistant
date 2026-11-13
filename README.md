# vn-macro-assistant

![CI](https://github.com/maidoanthanhthuy/vn-macro-assistant/actions/workflows/ci.yml/badge.svg)

A Vietnamese-language question-answering assistant for Vietnam's stock market and
macroeconomy. An agent routes each question to Text-to-SQL (prices, macro indicators,
policy events) or RAG (official NSO and SBV documents), or both, and answers with
numbers and citations. See [docs/SCOPE.md](docs/SCOPE.md).

## Project layout

```
docs/                  Scope, schema and design notes
eval/                  Evaluation set (seed_questions.csv)
scripts/smoke_tests/   Checks that each data source downloads for Vietnam
sql/                   Database schemas (schema.sql, rag_schema.sql)
src/vnmacro/
  ingest/              Fetch and load data into PostgreSQL / pgvector
  tools/               Text-to-SQL and RAG tools
  agent/               Router and answer generation
  app/                 Streamlit UI
tests/                 pytest tests
data/                  Local data (only data/manual/ is committed)
```

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env   # then fill in real values
```

## Reproduce the data

Raw data is **not** in the repository (only the scripts that fetch it and the hand-made
tables in `data/manual/`). The KBS price API is unofficial and undocumented, so it may
change or stop working; see [docs/data_sources.md](docs/data_sources.md). Each fetcher
saves a dated snapshot under `data/raw/<source>/<date>/` and never overwrites files.

```bash
# 1. Environment
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env   # then set a strong POSTGRES_PASSWORD

# 2. Database
docker compose up -d

# 3. Fetch raw snapshots (in this order)
PYTHONPATH=src python -m vnmacro.ingest.fetch_kbs
PYTHONPATH=src python -m vnmacro.ingest.fetch_worldbank
PYTHONPATH=src python -m vnmacro.ingest.fetch_imf

# 4. Create the tables (empty database): numeric tables, then the RAG schema
docker compose exec -T db sh -c 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < sql/schema.sql
docker compose exec -T db sh -c 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < sql/rag_schema.sql

# 5. Clean, check and load (uses the latest snapshot of each source)
PYTHONPATH=src python -m vnmacro.ingest.load_db
```

A newer snapshot can give different adjusted prices (new corporate actions) and newer
macro values, so results may differ from the 2026-11-10 snapshot used in this project.

## Database

PostgreSQL 16 + pgvector runs in Docker on `127.0.0.1:5432` (port from `POSTGRES_PORT` in
`.env`). It does not start on boot; start it by hand when needed.

```bash
docker compose up -d      # start (data is kept in the named volume "pgdata")
docker compose ps         # wait until the status shows "healthy"
docker compose stop       # stop, data is kept
```

Create the tables (first run, on an empty database):

```bash
docker compose exec -T db sh -c 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < sql/schema.sql
```

Recreate the tables after changing `sql/schema.sql`:

> **WARNING: this DELETES ALL NUMERIC DATA** (every table in the `public` schema). The `rag`
> schema is not affected.

```bash
docker compose exec -T db sh -c 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"'
docker compose exec -T db sh -c 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < sql/schema.sql
```

Create the RAG schema (schema `rag`: documents, chunks, embeddings; `vector` extension),
first run:

```bash
docker compose exec -T db sh -c 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < sql/rag_schema.sql
```

Recreate it after changing `sql/rag_schema.sql`:

> **WARNING: this DELETES ALL RAG DATA** (documents, chunks and embeddings in schema `rag`).
> The numeric tables in `public` are not affected.

```bash
docker compose exec -T db sh -c 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "DROP SCHEMA rag CASCADE;"'
docker compose exec -T db sh -c 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < sql/rag_schema.sql
```

Clean, check and load all data (latest raw snapshots + `data/manual/`). The load empties
and refills every table in one transaction; if a blocking check fails, nothing changes.
A report is printed and saved to `data/reports/`.

```bash
PYTHONPATH=src python -m vnmacro.ingest.load_db --dry-run   # checks and report only
PYTHONPATH=src python -m vnmacro.ingest.load_db             # load
```

Remove the container and its volume:

> **WARNING: `down -v` DELETES ALL DATA** (the `pgdata` volume is removed for good).

```bash
docker compose down -v
```

## Run tests

```bash
ruff check . && ruff format --check . && pytest
```
