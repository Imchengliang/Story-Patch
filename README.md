# Story-Patch (CanonGuard)

CanonGuard is a narrative-consistency research prototype. It decomposes scripts and novels into
PlotUnits and scene-level facts, audits setting contradictions over a temporal knowledge graph, and
offers replayable continuation suggestions for the points where an author gets stuck.

This repository contains core code only. Design notes, experiment logs and third-party corpora stay
out of it.

## Layout

```
apps/api          FastAPI backend (Python 3.12, uv)
  canonguard/     core / corpus / plot / harness / runs / api / eval / llm / db
  alembic/        database migrations
  tests/          pytest suite and synthetic fixtures
apps/web          Next.js frontend (pnpm workspace)
packages/contracts OpenAPI contract and the types generated from openapi.json
infra/            docker-compose (Postgres / Neo4j / MinIO / Valkey) + Neo4j constraints
docs/             method alignment notes
```

## Setup

```bash
cp .env.example .env      # fill in LLM provider model names and API keys
make setup                # uv sync + pnpm install
make up                   # start infra (host ports 5433/7688 avoid local instances)
make init                 # alembic upgrade head + MinIO bucket bootstrap
```

## Run

```bash
make api                  # 127.0.0.1:8100
make web                  # localhost:3000
```

## Verify

```bash
make test                 # pytest
make check                # ruff / mypy / typecheck / lint
make contracts            # re-export openapi.json and regenerate frontend types
```

CI (`.github/workflows/ci.yml`) runs the same checks and fails if `openapi.json` or the generated
types drift from the committed versions.

## Data and licensing

- `data/` only tracks directory placeholders (`.gitkeep`), the entity alias table
  `data/plot/aliases.yaml`, and the synthetic example inputs `data/eval/*.example.jsonl` and
  `data/eval/sample_gaps.jsonl`. Source texts, extractions, indexes and run artifacts are excluded
  via `.gitignore`.
- `apps/api/tests/fixtures/` holds hand-written samples that mirror the data formats; they contain
  no third-party corpus text.
- The corpora used in the study are not redistributed here. STAGE ships no license (research use
  only) and DramaBench is MIT; fetch each under its own terms.

## License

Research prototype, no open-source license attached. No usage rights are granted unless explicitly
authorized.
