# 006 · Review

## Test Record

- `uv run ruff check .` → passed
- `uv run pytest tests/unit` → 16 passed
- `./scripts/e2e.sh -k company_research_pipeline_artifacts` → 1 passed
- Real LLM validation: direct harness run with `.env` real mode produced run `cc4a069f8b4f`, terminal `done`, 31 events, and artifacts:
  - `gate-01-business_analysis.md`
  - `gate-02-fisher_qa.md`
  - `gate-03-moat_assessment.md`
  - `gate-04-management_assessment.md`
  - `gate-05-reverse_test.md`
  - `gate-06-valuation.md`
  - `final-report.md`
  - `decision.json`
  - `source-catalog.json`

## Design Review

- The migrated unit is the investment framework, not uteki.open's platform service internals.
- Current harness tool execution replaces the old custom ReAct tool executor and automatically registers source metadata.
- Gate artifacts make the company memo auditable without introducing a new company-analysis table.
- The implementation preserves artifact-first run detail by making `final-report.md` the primary artifact.

## Residual Risks

- Gate prompts are intentionally compact compared with uteki.open; prompt quality should be iterated with eval cases.
- Real path currently records provider usage only when future helper code surfaces gate `UsageDelta` events from internal LLM calls.
