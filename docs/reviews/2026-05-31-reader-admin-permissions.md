# Reader/Admin Permissions Review

Date: 2026-05-31

## Scope

Separate result/process viewing from operational control:

- `reader`: can view run results, run events, artifacts, source catalogs, agent
  catalog, and eval history.
- `admin`: can start agent runs, run compare/eval jobs, reload skills, and
  trigger self-evolution reviews.

## Key Design

- Backend is authoritative. Operation endpoints use `require_admin`; frontend
  controls only hide or disable affordances.
- User role is stored on `User.role`, defaulting to `reader`.
- Admin assignment is allowlist-based:
  - `UTEKI_ADMIN_EMAILS`
  - `UTEKI_ADMIN_GITHUB_LOGINS`
  - `UTEKI_ADMIN_GITHUB_IDS`
- GitHub OAuth can promote an allowlisted login/id to admin. Password and Google
  identities can promote allowlisted emails.
- Existing SQLite databases are repaired at startup with a small `role` column
  migration until Alembic migrations are introduced.

## Protected Operations

- `POST /api/agent/chat`
- `POST /api/agent/start`
- `POST /api/compare/run`
- `POST /api/eval/run`
- `POST /api/admin/reload-skills`
- `POST /api/admin/review/{run_id}`

## Validation

- `cd services/api && uv run ruff check src/uteki_api/auth src/uteki_api/api src/uteki_api/core/db.py src/uteki_api/users tests/e2e/test_03_research_chain.py tests/e2e/test_09_proposal_store.py tests/e2e/conftest.py`
  passed.
- `cd services/api && uv run pytest tests/e2e/test_01_auth_chain.py tests/e2e/test_03_research_chain.py tests/e2e/test_05_eval_chain.py tests/e2e/test_07_mcp_chain.py tests/e2e/test_09_proposal_store.py -q`
  passed: 19 tests.
- `cd apps/web && pnpm typecheck` passed.

## Review

- Reader can inspect a persisted run and its event trace.
- Reader receives 403 when attempting to start an agent or trigger admin review.
- Admin retains operational flow in existing E2E chains.
- Frontend now marks reader mode and disables/hides operation surfaces.
