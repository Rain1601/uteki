.PHONY: help setup setup-web setup-api dev web api types lint clean

help:
	@echo "uteki — make targets"
	@echo "  setup       Install all deps (node + python)"
	@echo "  dev         Run web (3000) and api (8000) in parallel"
	@echo "  web         Run web only"
	@echo "  api         Run api only"
	@echo "  types       Regenerate shared-types from FastAPI OpenAPI"
	@echo "  lint        Lint all packages"
	@echo "  clean       Remove build artifacts and caches"

setup: setup-web setup-api

setup-web:
	pnpm install

setup-api:
	cd services/api && uv sync

dev:
	bash scripts/dev.sh

web:
	pnpm --filter @uteki/web dev

api:
	cd services/api && uv run uvicorn uteki_api.main:app --reload --port 8000

types:
	bash scripts/gen-types.sh

lint:
	pnpm -r --filter "./apps/**" --filter "./packages/**" lint || true
	cd services/api && uv run ruff check . || true

clean:
	find . -type d -name node_modules -prune -exec rm -rf {} +
	find . -type d -name .next -prune -exec rm -rf {} +
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	find . -type d -name .ruff_cache -prune -exec rm -rf {} +
	find . -type d -name .pytest_cache -prune -exec rm -rf {} +
