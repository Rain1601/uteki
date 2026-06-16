# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Common commands

Day-to-day from repo root:

```bash
make setup        # install all deps (pnpm + uv)
make dev          # run web (3000) + api (8000) in parallel — calls scripts/dev.sh
make web          # web only
make api          # api only (cd services/api && uvicorn …)
make types        # regenerate apps/web shared types from the live API's OpenAPI
make lint         # ruff (api) + next lint (web)
```

Backend tests (the load-bearing chain — start here when changing anything in `services/api/`):

```bash
./scripts/e2e.sh                              # 20 hermetic E2E chains, ~8s, mock LLM
./scripts/e2e.sh -k auth                      # filter by chain
./scripts/e2e.sh -k pipeline -x               # stop on first fail (tight iteration loop)
set -a; source services/api/.env; set +a; \
  UTEKI_USE_MOCK_LLM=false ./scripts/e2e.sh -k real_llm    # real-LLM smoke (opt-in, ~2min, ~$0.25)
```

Single test:

```bash
cd services/api
uv run pytest tests/e2e/test_04_pipeline_chain.py::test_pipeline_artifact_chain -s -v
```

`-s` is important — the per-chain Reporter trace (▶ section / · event / ✓✗ check / kv pairs) prints to stdout and pytest hides it without `-s`. The trace is the diagnostic; don't try to debug an E2E failure without it.

Frontend typecheck:

```bash
cd apps/web && pnpm typecheck
```

The `pnpm lint` script is currently broken under Next 16 (next lint mis-parses the `lint` arg); use ruff + typecheck for now.

## Architecture — the load-bearing abstractions

### The harness contract: intent vs execution separation

This is the single most important pattern in the codebase. Adapted from Anthropic's harness-design guidance.

- **Skills** (subclasses of `BaseAgent` in `services/api/src/uteki_api/agents/base.py`) are pure async generators that `yield AgentEvent`. They never call tools directly, never write files directly, never touch a store.
- **The harness** (`agents/harness.py`) executes the side effects: it intercepts `tool_call` events and dispatches them via `ToolRegistry`, persists every event to `RunStore` + `Memory`, enforces six hard limits (steps / tool_calls / wall_time / input_tokens / output_tokens / cost_usd), and emits the final `done` event.

Concretely: a skill that wants to call a tool yields `AgentEvent(type="tool_call", data={"name": "market_quote", "args": {...}})`. The harness sees it, runs the tool, emits a `tool_result` event back into the stream. Two skills that already executed a tool inside an LLM tool-use loop set `data["_already_executed"] = True` so the harness skips re-dispatch.

**When changing a skill, never add a direct tool/store/file call — always yield the appropriate event.** The exception is `self.artifacts.write(...)` which the harness has explicitly injected (see "Artifact IPC" below).

### Artifact IPC — sub-agents communicate through files

When a pipeline skill (`ResearchPipeline` in `skills/pipelines/research_pipeline.py`) delegates to sub-skills, it shares the same `RunArtifacts` facade with them (`pipelines/research_pipeline.py:_delegate`). Planner writes `sprint-contract.json` → Research reads it → Evaluator reads both and writes `eval-report.json`. This is the M5/M6 invariant.

File layout (user-partitioned, M4):

```
data/runs/users/<user_id>/runs/<sha2>/<run_id>/
  ├── artifacts/<name>
  └── manifest.json
```

Cross-user reads of an artifact return `FileNotFoundError` at the store layer → the API maps to 404. Same 404 shape as "doesn't exist" — deliberately avoids leaking existence.

### Prompt composition + auto-versioning

Every skill's system prompt is composed at import time by `skills/loader.py`:

```
_shared/guardrails.md  +  <skill>/SKILL.md  +  <skill>/references/*.md  +  _shared/addendum_zh.md
```

The result is hashed and exposed via `BaseAgent.current_signature()`. The `EvolutionStore` (seeded in lifespan) auto-bumps the version when the hash changes. **Editing a SKILL.md does not require Python changes** — restart the API and the new version is recorded automatically. `POST /api/admin/reload-skills` hot-reloads without a restart.

### Per-skill `recommended_limits()`

The platform-default `HarnessLimits` (`max_tool_calls=30`, `max_input_tokens=200K`, `max_output_tokens=8192`) is sized for a single-skill run. Pipelines accumulate budgets across N sub-skills under one harness — they overflow the default. The `BaseAgent.recommended_limits()` hook (`agents/base.py`) lets a skill declare what it actually needs; `api/agent.py` reads it and constructs `AgentHarness(limits=...)` accordingly.

**If you add a pipeline-style skill, override `recommended_limits()` or runs will hit `max_X_exceeded` errors mid-iteration.** Real-LLM observed numbers for `ResearchPipeline` are documented in its docstring.

### Multi-tenant invariants (M4)

Every user-scoped store has `user_id` as a partition key:

- `Run.user_id` is a required field — `InMemoryRunStore.create()` raises if missing.
- `Memory` short-term keys are `(user_id, session_id)` tuples — two users with the same `session_id` cannot collide.
- `ArtifactStore` paths physically partition under `users/<user_id>/`.
- `EvalHistoryStore` partitions ndjson files the same way. Platform-level eval (drift_monitor) uses the reserved `user_id="system"`.
- `EvolutionStore` is **not** partitioned — skill versions are platform-shared.

Every API route uses `Depends(current_user)`. In dev (`UTEKI_AUTH_REQUIRED=false`) missing tokens fall back to a `demo@local` user that's idempotently created on startup. In tests + prod (`UTEKI_AUTH_REQUIRED=true`) missing tokens are 401.

When adding a new route that touches user data, the pattern is `_owner_id(run_id, user)` (see `api/artifacts.py`): resolve ownership via the run record first, then pass the resolved owner to the store call.

### Mock-LLM mode is the test mode

`UTEKI_USE_MOCK_LLM=true` (default) makes every skill use its `_mock_run` branch — deterministic events, no provider key needed. The E2E suite runs entirely in this mode; real-LLM tests are marked `@pytest.mark.real_llm` and skip unless `UTEKI_USE_MOCK_LLM=false` + a provider key is set.

**Mock and real modes emit different event sequences.** Mock has a `plan` event prelude; real goes straight from `step_start` to `delta` streams. Test assertions should target the mode-agnostic contract (`run_start`, `step_start`, `delta`, `done`) and verify usage rollup against `Run.usage_summary`, not against raw event types.

### Singleton-replacement testing pattern

`tests/e2e/conftest.py` resets in-process state per test by:

1. Calling `engine.dispose()` (SQLite holds deleted-file handles in its connection pool — without dispose, the next test sees the previous test's DB through the orphaned inode).
2. Rebinding `default_run_store` and `default_memory` on **every importing module** (`agents/harness.py`, `api/{agent,artifacts,compare,runs}.py`). These imports are by-name bindings, not attribute lookups — replacing one without the others leaves a module writing to a stale store, and ownership checks fail mysteriously downstream.

If you add a new module that imports `default_run_store` or `default_memory`, the conftest fixture must rebind it there too.

### LLM routing + tool spec dual-format

`ModelRouter` (`llm/router.py`) resolves a `<provider>/<model>` id to a client with a uniform async surface (`.stream_chat`, `.stream_chat_with_tools`, `.configured`). Providers: `anthropic` (native, supports prompt cache), `deepseek`, `openrouter`, `aihubmix`. Unknown provider falls back to the legacy `UTEKI_LLM_*` env vars; unconfigured client routes the skill to mock.

Tools expose both `to_openai_spec()` (function wrapper) and `to_anthropic_spec()` (flatter, `input_schema` instead of `parameters`). The LLM clients pick the right one. Adding a new tool means subclassing `Tool` in `tools/`, registering in `tools/__init__.py`, and listing the name in any skill's `DEFAULT_TOOLS` that should see it.

## Things that look like bugs but aren't

- **`status=error` on a run that produced all artifacts**: harness sets `final_status="error"` whenever any `error` event passes through the stream, even if the pipeline caught the inner failure and continued. Real-LLM iteration discovered this — the fix path was widening pipeline limits so error events don't fire, not changing the harness rule.
- **`async generator ignored GeneratorExit` in test logs**: SSE client disconnect propagation through the multi-layer async generator chain (`event_source` → `harness.run` → `pipeline.run` → `sub-skill.run`). Cleaned at the outermost layer but not deeper. Non-functional; only fires on mid-stream client teardown.
- **demo@local can't be registered**: Pydantic's `EmailStr` rejects it before the handler's reserved-email check runs (no TLD). Defense-in-depth; intentional.
- **Duplicate email → 409 not 400**: REST-correct. Auth spec was updated to match.
- **Anonymous mode (`UTEKI_AUTH_REQUIRED=false`) makes `/api/admin/reload-skills` reachable**: by design for dev convenience. Don't deploy with this flag.

## Spec-driven development

`openspec/` is the SSOT for capability contracts. When changing behavior:

1. Look at `openspec/specs/<capability>/spec.md` first — capabilities documented: `auth`, `users`, `storage`, `harness`, `artifacts`, `pipeline`, `evaluation`, `llm-routing`.
2. Significant features incubate as a proposal in `openspec/changes/<NNN>-name/{proposal.md,design.md,tasks.md}`, then archived to `openspec/changes/archive/` when complete.
3. The four archived changes (`001-tenant-and-auth`, `005-artifact-layer`, `006-planner-evaluator-pipeline`, `007-llm-judge-and-prompt-tuning`) are the history of how the platform got here — read them when an architectural decision is unclear.

## Environment

`services/api/.env.example` is the template; `services/api/.env` is gitignored. Key knobs:

- `UTEKI_USE_MOCK_LLM=true` — default in dev, makes every skill deterministic.
- `UTEKI_AUTH_REQUIRED=false` — dev convenience; falls back to demo user. Always `true` in tests + prod.
- `UTEKI_JWT_SECRET` — must be ≥ 32 chars in prod.
- `UTEKI_DEFAULT_MODEL=deepseek/deepseek-chat` — cheapest path for real-LLM dev.
