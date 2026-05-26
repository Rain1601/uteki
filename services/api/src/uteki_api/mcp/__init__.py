"""uteki MCP server — exposes uteki skills as MCP tools.

Lets Claude Code (and any MCP-compatible client) invoke uteki's research /
pipeline / artifact-read capabilities as first-class tool calls instead
of going through curl + Bash. See ``design/03-mcp-vs-local.md`` for why
this matters at the agent-cognition layer.

Design (see ``design/01-claude-code-interop.md`` direction B):

  - **Independent process** — ``python -m uteki_api.mcp``, stdio transport.
  - **Thin HTTP adapter** — every MCP tool call → uteki HTTP API call.
    No internal imports of skills/harness/stores. HTTP API stays SSOT;
    the MCP process can be restarted independently.
  - **Async execution** — ``run_skill`` returns ``run_id`` immediately
    (via /api/agent/start), client polls ``get_run`` for completion.
  - **Demo-user binding** — MVP runs in anonymous mode (the API must be
    started with ``UTEKI_AUTH_REQUIRED=false`` so the demo@local fallback
    serves MCP requests without credentials). Real service-account auth
    is future work.
"""

from uteki_api.mcp.server import build_server

__all__ = ["build_server"]
