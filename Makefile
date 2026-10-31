SHELL := /bin/bash
API_DIR := apps/api
WEB_DIR := apps/web
CONTRACTS_DIR := packages/contracts
COMPOSE := docker compose -f infra/docker-compose.yml
API_PORT ?= 8100

.PHONY: setup api-install web-install dev api web up down migrate minio-init init contracts check test llm-smoke parse-script import-stage-probe import-dramabench story-kg-smoke feedback-suggestions calibrate backfill-feedback eval-quick eval-stuck-points eval-threads eval-heldout blind-worksheet score-blind ab-genre-prior build-scene-index rebuild-scene-index build-scene-index-sample replay-check

setup: api-install web-install

api-install:
	cd $(API_DIR) && uv sync --all-groups

web-install:
	pnpm install

dev:
	@echo "Run 'make api' and 'make web' in two terminals."

api:
	cd $(API_DIR) && uv run uvicorn canonguard.main:app --reload --host 127.0.0.1 --port $(API_PORT)

web:
	pnpm --dir $(WEB_DIR) dev

up:
	$(COMPOSE) up -d

down:
	$(COMPOSE) down

migrate:
	cd $(API_DIR) && uv run alembic upgrade head

minio-init:
	cd $(API_DIR) && uv run python scripts/minio_init.py

init: migrate minio-init

contracts:
	cd $(API_DIR) && uv run python scripts/export_openapi.py ../../$(CONTRACTS_DIR)/openapi.json
	pnpm --dir $(CONTRACTS_DIR) generate

check:
	cd $(API_DIR) && uv run ruff check . && uv run ruff format --check . && uv run mypy canonguard
	pnpm --dir $(WEB_DIR) typecheck
	pnpm --dir $(WEB_DIR) lint
	pnpm --dir $(CONTRACTS_DIR) typecheck

test:
	cd $(API_DIR) && uv run pytest

llm-smoke:
	cd $(API_DIR) && uv run python scripts/llm_smoke.py

parse-script:
	cd $(API_DIR) && uv run python scripts/parse_script.py --file tests/fixtures/sample_screenplay.txt

import-stage-probe:
	cd $(API_DIR) && uv run python scripts/import_stage.py --probe --limit 1

import-dramabench:
	cd $(API_DIR) && uv run python scripts/import_dramabench.py --limit 3

story-kg-smoke:
	cd $(API_DIR) && uv run python scripts/story_kg_smoke.py --limit 10

feedback-suggestions:
	cd $(API_DIR) && uv run python scripts/feedback_suggestions.py --report

calibrate:
	cd $(API_DIR) && uv run python scripts/calibrate_feedback.py

backfill-feedback:
	cd $(API_DIR) && uv run python scripts/backfill_feedback.py

eval-quick:
	cd $(API_DIR) && uv run python scripts/eval_stuck_points.py --limit 3 --gate

eval-stuck-points:
	cd $(API_DIR) && uv run python scripts/eval_stuck_points.py --gate

eval-threads:
	cd $(API_DIR) && uv run python scripts/eval_threads.py --limit 3 --gate

eval-heldout:
	cd $(API_DIR) && uv run python scripts/eval_stuck_points.py --input ../../data/evaluations/heldout_stuck_points_report.json --output ../../data/evaluations/eval_heldout.json --gate

blind-worksheet:
	cd $(API_DIR) && uv run python scripts/make_blind_worksheet.py --input ../../data/evaluations/eval_heldout.json --output ../../data/evaluations/blind_worksheet_heldout.csv

score-blind:
	cd $(API_DIR) && uv run python scripts/score_blind.py --input ../../data/evaluations/blind_worksheet_heldout.csv --output ../../data/evaluations/blind_scores_heldout.json

ab-genre-prior:
	cd $(API_DIR) && uv run python scripts/ab_genre_prior.py

build-scene-index:
	cd $(API_DIR) && uv run python scripts/build_scene_index.py

rebuild-scene-index:
	cd $(API_DIR) && uv run python scripts/build_scene_index.py --force

build-scene-index-sample:
	cd $(API_DIR) && uv run python scripts/build_scene_index.py --per-language 6 --output ../../data/indexes/scenes/index.sample.json

replay-check:
	cd $(API_DIR) && uv run python scripts/replay_check.py --limit 3
