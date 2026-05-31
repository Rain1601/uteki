# Harness Spec Delta

## ADDED Requirements

### Requirement: Trace Diagnosis Artifact

The harness MUST write `trace-diagnosis.json` before `done` when artifacts are available.

### Requirement: Deterministic Diagnosis

Trace diagnosis MUST be derived from events, usage totals, source catalog, and final text without requiring an LLM call.
