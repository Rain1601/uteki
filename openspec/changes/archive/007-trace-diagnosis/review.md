# 007 · Review

## Test Record

- `uv run pytest tests/unit/test_provenance.py` → 5 passed
- `uv run ruff check .` → passed
- `./scripts/e2e.sh -k "research_chain or pipeline_artifact_chain or company_research_pipeline_artifacts"` → 4 passed
- `set -a; source services/api/.env; set +a; UTEKI_USE_MOCK_LLM=false ./scripts/e2e.sh -k real_research_run_emits_tool_calls_and_costs -s` → 1 passed; real run `85dc4872fe87` produced `final-report.md`, `final-research.md`, `source-catalog.json`, and `trace-diagnosis.json`

## Design Review

- Diagnosis is deterministic and cheap; it does not add another evaluator loop.
- The artifact is written before `done`, so run readers can treat it like every other artifact.
- The design summarizes failure/tool/citation signals without replacing raw event replay.

## Residual Risks

- Internal LLM calls inside custom pipeline skills need explicit `usage` emission if we want full usage diagnosis for every subcall.
