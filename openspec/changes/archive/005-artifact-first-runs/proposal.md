# 005 · Artifact-first runs

## Why

Runs should be read as durable research deliverables, not reconstructed chat transcripts. `004-provenance-citation` made sources durable through `source-catalog.json`; the next invariant is that every completed run exposes a stable primary artifact and an artifact index through the run API.

## What changes

- Add artifact metadata roles (`primary`, `draft`, `plan`, `contract`, `evaluation`, `trace`, `source_catalog`, `diagnosis`, `auxiliary`).
- Ensure the harness writes `final-report.md` as the primary run deliverable when the skill produced final markdown or streamed deltas.
- Extend `/api/runs` and `/api/runs/{id}` with `primary_artifact`, artifact count/index, and `events_summary`.
- Update the run detail UI to show the primary artifact first and keep event trace as supporting observability.

## Out of scope

- Rich markdown rendering.
- External object storage migration.
- Removing event replay from the API.
