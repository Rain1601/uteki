# Pipeline Spec Delta

## ADDED Requirements

### Requirement: Company Research Pipeline

The system MUST provide a `company_research_pipeline` skill that turns a company ticker request into an artifact-first investment memo.

### Requirement: Seven Gate Structure

The company pipeline MUST preserve the migrated gate sequence from `uteki.open`: business analysis, Fisher growth QA, moat assessment, management assessment, reverse test, valuation, and final verdict synthesis.

### Requirement: Gate Artifacts

Each analytical gate MUST persist a markdown artifact named `gate-<NN>-<gate_name>.md`.

### Requirement: Evidence Collection

The pipeline SHOULD seed the run with quote, financial, and news evidence via harness-managed tools before gate synthesis.
