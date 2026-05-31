# Artifacts Spec Delta

## ADDED Requirements

### Requirement: Artifact Role Metadata

Artifacts MUST carry a role with a backward-compatible default of `auxiliary`.

Valid roles are `primary`, `draft`, `plan`, `contract`, `evaluation`, `trace`, `source_catalog`, `diagnosis`, and `auxiliary`.

### Requirement: Primary Run Artifact

Completed runs SHOULD expose a `final-report.md` artifact with role `primary` whenever there is final markdown or streamed assistant output to persist.

### Requirement: Artifact-first Run Detail

Run detail APIs MUST expose an artifact index and identify the primary artifact when present. Event replay remains available for diagnostics.
