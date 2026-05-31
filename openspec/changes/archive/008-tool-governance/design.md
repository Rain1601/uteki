# 008 · Design

## Key Design

Governance belongs in the harness because tool execution is a side effect. Skills and models may request a tool, but the harness decides whether execution is allowed.

## Behavior

- Low/medium risk tools execute as before.
- High-risk tools do not execute.
- High-risk tool calls produce:
  - `await_review` with checkpoint `high_risk_tool`
  - `tool_result(ok=false, error="high_risk_tool_requires_review")`

## Compatibility

All existing tools default to `low`, so current research behavior remains unchanged.

## Future

Approval/resume can be added by persisting pending tool call payloads and adding an approve endpoint. This change deliberately only establishes the no-execution invariant.
