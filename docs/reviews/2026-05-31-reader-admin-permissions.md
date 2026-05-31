# Reader/Admin Permissions Review

Date: 2026-05-31

## Scope

Separate result/process viewing from operational control:

- `reader`: can view run results, run events, artifacts, source catalogs, agent
  catalog, and eval history.
- `admin`: can start agent runs, run compare/eval jobs, reload skills, and
  trigger self-evolution reviews.

## Key Design

- Backend is authoritative. Agent endpoints use `can_run_agent`; admin/eval
  endpoints use `require_admin`. Frontend controls only hide or disable
  affordances.
- User role is stored on `User.role`, defaulting to `reader`.
- Effective request permissions are returned as `user.permissions`, so future
  subscriptions can expand read scope without promoting users to admin.
- `UTEKI_LOCAL_ALL_PERMISSIONS=true` grants local full permissions without
  rewriting the persisted role. When `UTEKI_AUTH_REQUIRED=false`, local full
  permissions are enabled by default unless explicitly disabled.
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
- Local dev can grant full operation permissions through config while keeping
  the user role as `reader`, which keeps subscription/read-scope work separate
  from owner/admin capability.

## Subscription Direction

Subscription should be modeled as entitlement / tier, not as admin:

- Free reader: limited result and trace visibility.
- Subscriber: broader result/history/artifact/source visibility.
- Admin: full operation and platform management.

This keeps monetized read access separate from the ability to run agents,
reload skills, run evals, or trigger self-evolution.
