# 007 · Design

## Key Design

Trace diagnosis is derived, deterministic metadata. It is not another LLM call. The event stream remains the raw audit log; `trace-diagnosis.json` is the compact index for debugging and review.

## Artifact Shape

```json
{
  "status": "ok|warn|error",
  "event_counts": {},
  "failures": [],
  "warnings": [],
  "tools": {"calls": {}, "failures": []},
  "usage": {},
  "artifacts": [],
  "citations": {
    "source_count": 0,
    "cited_ids": [],
    "orphan_ids": [],
    "no_source_count": 0
  }
}
```

## Placement

Harness writes diagnosis after primary/source artifacts and before `done`, so downstream readers can see diagnosis as a normal artifact.

## Review Notes

- Deterministic diagnosis keeps this cheap and testable.
- The artifact intentionally summarizes the trace rather than replacing `/events`.
