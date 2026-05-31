# 006 · Company research pipeline

## Why

`uteki.open` has a company analysis system built as a domain service with a 7-gate decision tree. `uteki` should keep the investment logic but move execution into the harness: one run, explicit tool evidence, source catalog, gate artifacts, and a primary investment memo.

## What changes

- Add `company_research_pipeline` as a pipeline skill.
- Migrate the 7-gate structure:
  1. business analysis
  2. Fisher growth QA
  3. moat assessment
  4. management assessment
  5. reverse test
  6. valuation
  7. synthesis / verdict
- Use current tools (`market_quote`, `financials`, `news_search`) to seed evidence and source metadata.
- Persist evidence artifacts, per-gate markdown artifacts, `final-report.md`, and `decision.json`.

## Out of scope

- Persisting old `company_analyses` SQL tables.
- Migrating every uteki.open output schema field.
- Order execution.
