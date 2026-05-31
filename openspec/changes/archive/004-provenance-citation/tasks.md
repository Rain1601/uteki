# 004 · Tasks

> 每条任务控制在一个 PR-sized unit（≤4h）。先做模型和验证，再接 harness，最后适配 tools。

## Phase 0 — Spec hygiene

- [done] Archive `002-adopt-financial-services` as completed/superseded by current specs.
- [done] Archive `003-anthropic-sdk-integration` as completed; real-key verification moves to ops checklist.
- [done] Update `openspec/README.md` active/archive status.

## Phase 1 — Provenance core

- [done] **T1.1** Add `services/api/src/uteki_api/provenance/datapoint.py`.
- [done] **T1.2** Add `SourceCatalog` with add/dedup/serialize/render helpers.
- [done] **T1.3** Add `citation_parser.py` with `[src:N]` / `[src:none]` support.
- [done] **T1.4** Unit tests for DataPoint, SourceCatalog, CitationParser.

## Phase 2 — Harness and artifacts

- [done] **T2.1** Add optional `BaseAgent.sources` and `RunSources` facade.
- [done] **T2.2** Extend `ToolResult` with `sources: list[dict] = []`.
- [done] **T2.3** Register `ToolResult.sources` in harness `_invoke_tool()`.
- [done] **T2.4** Write `source-catalog.json` artifact before run finish when catalog has items.
- [done] **T2.5** Emit `artifact_written` for auto-written source catalog.

## Phase 3 — Verifier integration

- [done] **T3.1** Add `citation_ids_exist` verifier.
- [done] **T3.2** Add helper to load `source-catalog.json` from artifacts.
- [done] **T3.3** Add unit coverage that intentionally cites orphan source ids.
- [done] **T3.4** Ensure verifier reports orphan ids in notes for `eval-report.json`.

## Phase 4 — First tool adaptation

- [done] **T4.1** Adapt `news_search` to return source metadata.
- [done] **T4.2** Adapt `web_search`, `web_extract`, and mock `financials` to return source metadata.
- [done] **T4.3** Harness smoke unit test verifies tool sources produce `source-catalog.json`.

## Phase 5 — Docs and final spec

- [done] **T5.1** Promote `openspec/changes/004-provenance-citation/specs/provenance/spec.md` to `openspec/specs/provenance/spec.md`.
- [done] **T5.2** Update `openspec/specs/harness/spec.md` with source injection and tool result registration.
- [done] **T5.3** Update `openspec/specs/artifacts/spec.md` with `source-catalog.json`.
- [done] **T5.4** Archive this change after implementation and validation.

## Out of scope follow-ups

- `005-artifact-first-runs`
- `006-company-research-pipeline`
- `007-trace-diagnosis`
- `008-tool-governance`
