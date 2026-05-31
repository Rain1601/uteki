# 005 · Design

## Key Design

Artifact metadata becomes the run's reading contract. Events remain the audit log; artifacts become the user-facing deliverables.

## Contract

- A successful run SHOULD expose `primary_artifact`.
- `final-report.md` is the canonical primary markdown artifact.
- Existing skill-specific outputs such as `final-research.md` remain valid drafts and may be copied into `final-report.md`.
- `/api/runs/{id}` returns:
  - full legacy run fields,
  - `artifacts`,
  - `primary_artifact`,
  - `events_summary`.
- `/api/runs` returns lightweight artifact hints for list rendering.

## Compatibility

Older runs without artifacts still render from `summary` or `delta` events. Existing `artifact_written` events and `/artifacts` endpoints remain unchanged.

## Review Notes

- The harness owns the fallback primary artifact because not every skill writes a named final file yet.
- Artifact roles are optional with defaults, so old manifest entries validate as `auxiliary`.
