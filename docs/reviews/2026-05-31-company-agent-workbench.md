# Company Agent Workbench Review

Date: 2026-05-31

## Scope

Build a practical company-research agent surface inspired by the prior uteki.open
research desk:

- A dedicated `/company-agent` workbench for company deep-research runs.
- Real invocation of `company_research_pipeline` with `deepseek/deepseek-chat`.
- A company-specific run detail summary for verdict, ranking, capital plan, and
  research artifacts.

## Key Design

- Keep the current Uteki architecture: harness, run, artifact, eval, and tool
  governance remain the agent's internal operating system.
- Use the reference design's useful structure rather than recreating the old app:
  watchlist, active draft, execution log, and investment dossier.
- Prefer artifact-backed display. The run detail reads `decision.json`,
  `ranking.json`, `capital-plan.json`, and `company-profile.json`; the primary
  report is selected from `role=primary`.
- No real order execution. Capital plan remains bounded sizing guidance.

## Validation

- Frontend typecheck: `cd apps/web && pnpm typecheck` passed.
- Diff whitespace check passed for touched frontend files.
- Page HTTP checks passed:
  - `http://localhost:3000/company-agent`
  - `http://localhost:3000/runs/71635ecc1e43`
- Real LLM smoke run completed:
  - run id: `71635ecc1e43`
  - skill: `company_research_pipeline`
  - model: `deepseek/deepseek-chat`
  - status: `ok`
  - artifacts: 17
  - decision: `WATCH`
  - target rank: `3`
  - initial/max position: `1.5% / 5.0%`
  - real order execution: `false`

## Observations

- The agent loop completed autonomously and persisted every major stage.
- Observability is materially better in the UI: the workbench shows run state,
  gates, live trace events, and history; run detail shows verdict and artifact
  structure before the full memo.
- Traceability still has a weak point: the run generated source ids, but the
  final report used mostly `[src:none]`.
- Data quality is the largest current gap. The LLM was real DeepSeek, but
  `market_quote`, `financials`, and `news_search` still returned mock data for
  this run. Production-quality investment decisions require real data adapters.

## Follow-Up Specs

1. Real data adapter: completed in `2026-05-31-real-data-source-traceability.md`
   for US equities via yfinance, optional FMP quote fallback, Google CSE, and
   DDGS.
2. Citation reconciliation: partially completed. Source catalog and artifact
   `source_refs` now persist correctly; stricter handling of remaining
   `[src:none]` claims is still a future eval threshold.
3. Ranking reconciliation: cross-check `final-report.md`, `ranking.json`,
   `decision.json`, and `capital-plan.json` before marking a run final.
4. Browser validation: once the in-app browser is available again, capture
   visual QA for desktop and mobile layouts.
