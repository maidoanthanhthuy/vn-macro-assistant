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

`requirements-embed.txt` (CPU-only torch, sentence-transformers) is needed only to
compute embeddings (`python -m vnmacro.rag.embed`). Tests, CI and the data loaders do not
need it. Install it on top of the core requirements; the file points pip to the CPU-only
PyTorch index, so no CUDA packages are downloaded:

```bash
pip install -r requirements.txt -r requirements-embed.txt
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

# 6. RAG documents: fetch, extract text, chunk
PYTHONPATH=src python -m vnmacro.ingest.fetch_documents
PYTHONPATH=src python -m vnmacro.ingest.extract_text
PYTHONPATH=src python -m vnmacro.rag.chunking

# 7. Load chunks into schema rag, embed them and check the vectors
#    (needs requirements-embed.txt; first run downloads the model, ~2.3 GB)
pip install -r requirements-embed.txt
PYTHONPATH=src python -m vnmacro.rag.build
```

`vnmacro.rag.build` is the normal way to (re)build the RAG tables. It runs `load_rag`
(empties and reloads `rag.documents` and `rag.chunks`, which also deletes all rows in
`rag.chunk_embeddings`), then `embed`, then checks that every chunk has exactly one
vector. The two steps can be run alone (`python -m vnmacro.rag.load_rag`,
`python -m vnmacro.rag.embed`), but `embed` must always follow `load_rag`. Vectors are cached in
`data/processed/embeddings/` by model commit and text hash: a rerun only encodes new or
changed chunks (762 chunks take about 16 minutes on CPU the first time, seconds after).

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
