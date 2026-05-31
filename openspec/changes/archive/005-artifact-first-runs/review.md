# 005 · Review

## Test Record

- `uv run pytest tests/unit/test_provenance.py` → 5 passed
- `uv run ruff check .` → passed
- `pnpm typecheck` in `apps/web` → passed
- `uv run pytest tests/unit` → 16 passed
- `./scripts/e2e.sh -k "research_chain or pipeline_artifact_chain"` → 3 passed
- `set -a; source services/api/.env; set +a; UTEKI_USE_MOCK_LLM=false ./scripts/e2e.sh -k real_research_run_emits_tool_calls_and_costs -s` → 1 passed; real provider call observed at `https://api.deepseek.com/v1/chat/completions`

## Design Review

- The design keeps old `events` replay intact while making artifacts the primary reading contract.
- `Artifact.role` defaults to `auxiliary`, so existing manifests validate without migration.
- Harness-level `final-report.md` fallback is acceptable because it only fires when the skill has not already written a primary deliverable.
- Run API now returns artifact index and `events_summary`; this reduces frontend dependence on event-stream reconstruction.

## Residual Risks

- Markdown is still rendered as plain preformatted text in the UI.
- List endpoint now reads artifact manifests per run; acceptable for local scale, but pagination/caching may be needed later.
