# 006 · Design

## Key Design

The company pipeline is a harness-native skill, not a restored domain service. The old gates become subagent boundaries and artifacts. The run is the source of truth.

## Artifacts

- `company-profile.json`
- `financials.json`
- `news-brief.json`
- `gate-01-business_analysis.md`
- `gate-02-fisher_qa.md`
- `gate-03-moat_assessment.md`
- `gate-04-management_assessment.md`
- `gate-05-reverse_test.md`
- `gate-06-valuation.md`
- `final-report.md`
- `decision.json`
- `source-catalog.json` when tools return sources

## Events

Each gate is framed with `subagent_start` / `subagent_end`. Tool evidence is collected through the harness executor so source ids are registered in the run catalog.

## Migration Notes From uteki.open

The migrated behavior is the 7-gate investment framework and gate naming. The old ReAct XML parser, company SQL repository, and provider adapter layer are intentionally not copied; current `LLMClient` and harness tool execution replace them.

## Key Result

A user can run `agent=company_research_pipeline` and receive an artifact-first company investment memo with gate-level audit artifacts.
