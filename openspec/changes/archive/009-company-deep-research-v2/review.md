# 009 · Review

## Test Record

- `uv run ruff check .` → passed
- `uv run pytest tests/unit tests/e2e/test_10_company_pipeline.py -q` → 21 passed
- `set -a; source .env; set +a; UTEKI_USE_MOCK_LLM=false uv run pytest tests/e2e/test_10_company_pipeline.py -q -s` → passed; direct DeepSeek run `9be270ddc9c0`
- `./scripts/e2e.sh` → 30 passed, 2 skipped
- `set -a; source .env; set +a; UTEKI_USE_MOCK_LLM=false uv run pytest tests/e2e/test_10_company_pipeline.py -q -s` → passed; direct DeepSeek run `823f2186c96d`

## Real LLM Observation

Direct DeepSeek produced the full v2 artifact set for AAPL vs MSFT/GOOGL/META:

- `ranking.json`: AAPL rank 1, action BUY
- `capital-plan.json`: initial 4%, max 10%, `real_order_execution=false`
- `agent-capability-review.json`: 10 stages persisted
- `final-report.md`: primary memo written; markdown preamble stripped by artifact store

Follow-up direct DeepSeek run `823f2186c96d`:

- `ranking.json`: AAPL rank 1, action BUY; order `AAPL > MSFT > META > GOOGL`
- `capital-plan.json`: initial 4%, max 10%, `real_order_execution=false`
- `decision.json`: BUY, conviction 0.6, max position 10%
- `final-report.md`: valid numeric citations only; no invalid `[src:*]` labels
- Observed issue: `final-report.md` duplicated the `Capital Plan` section and described GOOGL as "ranking incomplete" while `ranking.json` ranked GOOGL #4. This should become a reconciliation/evaluator check in the next iteration.

Two real-model issues drove implementation changes:

1. DeepSeek generated non-catalog citations such as `[src:quote]`; the pipeline now deterministically sanitizes non-numeric source labels to `[src:none]`.
2. One synthesis call exceeded the previous 120s LLM streaming timeout; the timeout is now 300s and synthesis prompt context is narrower.

## Design Review

- The implementation is a harness-native agentic pipeline, not a true multi-skill agent swarm.
- Keeping gates internal is acceptable for v2 because it keeps artifact and evidence flow simple.
- Autonomy is medium: the pipeline can parse peers, auto-fill missing peers, collect evidence, rank, size, and synthesize without user intervention.
- Observability is strong: tool events, gate artifacts, ranking, capital plan, trace diagnosis, and capability review are persisted.
- Traceability is improved but still limited by mock/fixture data quality; citations are now mechanically valid.
- Self-iteration is early: stage artifacts allow later comparison and correction, but no automatic rerun loop exists inside company research yet.
- Codex takeover requirement: validation should include run → observe persisted artifacts → identify drift → record result → iterate. The current repo supports most of this through e2e logs, run artifacts, trace diagnosis, and OpenSpec review records; it still needs automated reconciliation checks before the agent can self-correct output drift.

## Residual Risks

- Peer selection is a deterministic map, not a live sector classifier.
- Ranking is a simple scorecard, not a full valuation model.
- Gates are not reusable skills yet; if cross-pipeline reuse matters, split ranker/capital/risk reviewer first.
- No brokerage integration is present by design.
