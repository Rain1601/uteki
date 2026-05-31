# Repository Guidelines

## Project Structure & Module Organization

Uteki is a pnpm/uv monorepo for an investment research agent. `apps/web/` contains the Next.js 16 + React 19 frontend, with routes in `app/`, UI in `components/`, and helpers in `lib/`. `services/api/` contains the FastAPI backend; source lives in `src/uteki_api/` and tests in `tests/unit/` and `tests/e2e/`. `packages/shared-types/` holds OpenAPI-generated TypeScript types, and `packages/ui/` is for shared React components. Architecture and specs live in `docs/`, `design/`, and `openspec/`.

## Build, Test, and Development Commands

- `make setup`: install Node dependencies with pnpm and Python dependencies with uv.
- `make dev`: run web on port 3000 and API on port 8000.
- `make web` / `make api`: start only one side of the stack.
- `make types`: regenerate shared TS types from the live FastAPI OpenAPI schema.
- `make lint`: run workspace lint hooks; `next lint` is currently unreliable under Next 16.
- `cd apps/web && pnpm typecheck`: preferred frontend validation.
- `./scripts/e2e.sh`: run deterministic backend E2E chains in mock-LLM mode.
- `cd services/api && uv run pytest tests/unit`: run backend unit tests.

## Coding Style & Naming Conventions

Follow `.editorconfig`: UTF-8, LF endings, final newline, spaces, 2-space default indentation, and 4 spaces for Python. Backend code targets Python 3.13 and uses Ruff (`line-length = 100`, imports sorted, `E/F/I/W/UP/B/SIM` rules). Keep FastAPI routes under `uteki_api/api/`, stores under their domain package, and tools in `uteki_api/tools/`. Frontend components use PascalCase files such as `PlanCard.tsx`; helpers use lowercase names such as `api-base.ts`.

## Testing Guidelines

Backend tests use pytest and pytest-asyncio. Name files `test_*.py` and keep E2E chains in `services/api/tests/e2e/`. Mock LLM mode is the default for normal checks. Real provider smoke tests are marked `real_llm` and require `UTEKI_USE_MOCK_LLM=false` plus credentials. For one failing E2E case, use `./scripts/e2e.sh -k pipeline -x` or a specific pytest node with `-s -v`.

## Commit & Pull Request Guidelines

Git history uses conventional-style prefixes with scopes, for example `docs(design): ...`, `fix(skills): ...`, and `fix(mcp): ...`. Keep commits focused and describe behavior, not just touched files. Pull requests should include a short summary, linked issue or openspec proposal when relevant, screenshots for UI changes, and exact checks run (`pnpm typecheck`, `./scripts/e2e.sh`, targeted pytest, etc.).

## Security & Configuration Tips

Use `services/api/.env.example` as the template and do not commit local secrets. Keep `UTEKI_AUTH_REQUIRED=true` outside local development. Generated data, caches, `.venv/`, `.next/`, and `node_modules/` should remain uncommitted.
