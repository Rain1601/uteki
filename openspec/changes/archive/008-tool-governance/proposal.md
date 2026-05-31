# 008 · Tool governance

## Why

As the agent gains tools beyond read-only research, the harness needs a hard safety boundary. High-risk tools must not execute just because an LLM asked for them.

## What changes

- Add `Tool.risk_level`: `low`, `medium`, `high`.
- Include risk level in tool specs shown to LLMs.
- Block high-risk tool execution in the harness.
- Emit `await_review` and a blocked `tool_result` for high-risk tool calls.

## Out of scope

- Human approval resume flow.
- Order execution tools.
- Policy UI.
