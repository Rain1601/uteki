# 008 · Review

## Test Record

- `uv run pytest tests/unit/test_provenance.py` → 6 passed
- `uv run pytest tests/unit` → 17 passed
- `uv run ruff check .` → passed
- `pnpm typecheck` → passed
- `./scripts/e2e.sh -k "research_chain or pipeline_artifact_chain or company_research_pipeline_artifacts"` → 4 passed
- `set -a; source services/api/.env; set +a; UTEKI_USE_MOCK_LLM=false ./scripts/e2e.sh -k real_research_run_emits_tool_calls_and_costs -s` → 1 passed; real run `ef2d6fbd05c3`, 5 low-risk tool calls, status ok

## Design Review

- Risk control is correctly placed at the harness execution boundary.
- Existing research tools remain low-risk by default, preserving current behavior.
- The blocked result gives the LLM and trace a deterministic failure mode instead of silent skipping.

## Residual Risks

- There is not yet an approve/resume API; high-risk tools are safely blocked, not resumable.
