## ADDED Requirements

### Requirement: Company research v2 artifacts are persisted

Company deep research SHALL persist structured artifacts for peer comparison, ranking, capital sizing, and stage review.

#### Scenario: Structured artifacts are present

- **WHEN** a company deep research run completes
- **THEN** the run artifact list SHALL include `peer-comparison.json`
- **AND** `ranking.json`
- **AND** `capital-plan.json`
- **AND** `agent-capability-review.json`
