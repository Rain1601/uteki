# Harness Spec Delta

## ADDED Requirements

### Requirement: Tool Risk Levels

Every tool MUST expose a risk level: `low`, `medium`, or `high`. The default is `low`.

### Requirement: High-Risk Tool Intercept

The harness MUST NOT execute a high-risk tool call by default. It MUST emit an `await_review` checkpoint and a blocked `tool_result`.

### Requirement: Governance At Execution Boundary

Risk enforcement MUST happen in the harness, not only in prompts or skill code.
