# 009 · Design

## Key Design

Keep company deep research inside `company_research_pipeline`. The harness already gives us persistence, provenance, limits, and trace events; the v2 work should enrich the skill's domain behavior without adding another orchestration layer.

## Flow

1. Parse target symbol and optional peer symbols from the user message.
2. If peers are absent, choose up to three US-stock peers from a small deterministic map.
3. Collect evidence for target and peers through existing low-risk read tools.
4. Run the existing six gates for the target company.
5. Build deterministic peer comparison and ranking artifacts.
6. Build a capital plan with bounded position sizing and explicit risk triggers.
7. Synthesize the final memo using gate output, ranking, and capital plan.
8. Persist stage-level agent capability review as JSON.

## Agent Capability Review

Each major stage writes a review record with:

- `autonomy`: whether the stage made progress without user intervention.
- `observability`: which events or artifacts expose the stage.
- `traceability`: source ids and persisted artifacts.
- `self_iteration`: how the stage can feed a later correction pass.

The review is persisted after each stage as `agent-capability-review.json`, so interrupted runs still leave partial observability.

## Capital Plan

The capital plan is an investment sizing recommendation only. It never calls order tools. Position size is capped at 10% of portfolio value, with smaller initial sizing and explicit add/trim/sell triggers.

## Compatibility

Existing single-company prompts still work. If the user supplies no peers, the pipeline auto-fills peers and records that choice in artifacts. Existing gate artifacts and `final-report.md` remain unchanged in name.
