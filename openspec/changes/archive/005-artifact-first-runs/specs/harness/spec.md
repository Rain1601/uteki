# Harness Spec Delta

## ADDED Requirements

### Requirement: Primary Artifact Fallback

The harness SHOULD create `final-report.md` after skill execution when the skill did not already create one and there is final content available.

### Requirement: Event Trace As Supporting Signal

The harness MUST continue to persist events, but user-facing run detail SHOULD prioritize artifacts over delta reconstruction.
