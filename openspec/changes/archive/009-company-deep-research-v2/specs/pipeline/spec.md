## ADDED Requirements

### Requirement: Company deep research supports peer ranking

`company_research_pipeline` SHALL support a target US stock and up to three peer companies in one run.

#### Scenario: User supplies peers

- **WHEN** the user asks to analyze `AAPL` and compare `MSFT`, `GOOGL`, and `META`
- **THEN** the pipeline SHALL collect evidence for all four symbols
- **AND** write `peer-comparison.json`
- **AND** write `ranking.json` with at most four ranked companies
- **AND** include the target symbol in the ranking

#### Scenario: User omits peers

- **WHEN** the user asks to analyze a target US stock without peers
- **THEN** the pipeline SHALL auto-fill up to three peers
- **AND** record the chosen peers in `company-profile.json`

### Requirement: Company deep research includes capital management without trading

`company_research_pipeline` SHALL produce a bounded capital plan and SHALL NOT execute orders.

#### Scenario: Capital plan is generated

- **WHEN** the company deep research run completes
- **THEN** it SHALL write `capital-plan.json`
- **AND** `max_position_pct` SHALL be at most `10`
- **AND** the plan SHALL contain risk triggers for adding, trimming, and selling

### Requirement: Company deep research reviews agent capability by stage

`company_research_pipeline` SHALL persist a stage-level capability review.

#### Scenario: Review artifact is generated

- **WHEN** the run reaches evidence collection, gates, peer comparison, capital plan, or synthesis
- **THEN** it SHALL update `agent-capability-review.json`
- **AND** each stage entry SHALL include autonomy, observability, traceability, and self-iteration fields
