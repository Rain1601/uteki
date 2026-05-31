# Real Data Source Traceability Review

Date: 2026-05-31

## Scope

Replace fixture-only company research evidence with live providers while keeping
the harness-native run/artifact/source model:

- Quotes and K-line data: yfinance, with optional FMP quote fallback.
- Financials: yfinance income statement, cash flow, profile, profitability,
  balance, and growth snapshots.
- News: Google Custom Search when configured, DDGS as no-key fallback.
- Source catalog: normalize provider evidence into domain source types so every
  persisted analysis can be traced from artifact metadata and report citations.

## Key Design

- Provider identity stays in the payload (`source`, `provider`, `source_url`);
  harness `source_type` uses stable domain categories:
  `market_data`, `financials`, and `news`.
- Mock mode remains the default for deterministic tests. Real data is enabled
  separately via `UTEKI_USE_MOCK_DATA=false`.
- No broker/order execution was added. Capital planning remains risk-bounded
  sizing guidance only.
- The company pipeline now attaches evidence `source_refs` to gate artifacts,
  final report, and decision artifacts, not just raw evidence artifacts.

## Validation

- `cd services/api && uv run ruff check src/uteki_api/skills/company src/uteki_api/tools src/uteki_api/core/config.py tests/unit/test_real_data_tools.py tests/unit/test_company_pipeline.py`
  passed.
- `cd services/api && uv run pytest tests/unit/test_real_data_tools.py tests/unit/test_company_pipeline.py -q`
  passed: 7 tests.
- Real provider smoke confirmed:
  - `market_quote(AAPL)`: yfinance.
  - `financials(AAPL)`: yfinance.
  - `news_search(AAPL ...)`: DDGS fallback.
  - `kline(AAPL)`: yfinance.
- Real end-to-end run completed:
  - run id: `1044e9446897`
  - skill: `company_research_pipeline`
  - model: `deepseek/deepseek-chat`
  - status: `ok`
  - artifacts: 17
  - source catalog entries: 28
  - source types: `financials`, `market_data`, `news`
  - `gate-01-business_analysis.md`, `gate-06-valuation.md`,
    `final-report.md`, and `decision.json` each persisted 28 `source_refs`.
  - decision: `AVOID`
  - target rank: `4`
  - initial/max position: `0% / 0%`
  - real order execution: `false`

## Review

- Autonomy: the pipeline completed evidence collection, six gates, peer ranking,
  capital plan, capability review, final memo, and decision without user
  intervention.
- Observability: run events include 12 tool calls/results, 6 subagent
  start/end pairs, and artifact writes for the complete research chain.
- Traceability: source catalog generation now works with live providers, and
  final artifacts link back to source ids through manifest metadata.
- Self-iteration: persisted artifacts and trace diagnosis provide a concrete
  basis for comparing future reruns against new evidence.

## Remaining Gaps

- Some final-report claims still use `[src:none]` when the LLM makes qualitative
  judgments beyond the retrieved evidence. This is acceptable for now but should
  become a stricter eval threshold before production use.
- yfinance/DDGS are pragmatic live providers, not institutional-grade data.
  Paid filings/news APIs can be layered in later behind the same tool contracts.
