"""MCP Server — exposes uteki skills as 5 tools.

Tool surface (intentionally small):

    uteki_list_skills      — discover what skills are registered
    uteki_run_skill        — kick off a run; returns run_id immediately
    uteki_get_run          — read run state (status / summary / events)
    uteki_list_artifacts   — list files produced by a run
    uteki_read_artifact    — read one file by name

Why these five: this is the minimum surface that lets CC drive a full
research workflow end-to-end (start → poll → read result). Anything
larger is incremental; smaller leaves CC unable to read the output it
just kicked off.

Why ``uteki_`` prefix and not the MCP-namespaced ``mcp__uteki__``: the
namespacing is applied by the *client* based on the server name in its
config. The server itself just names tools with a uteki_ prefix for
clarity in logs.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from mcp.server import Server
from mcp.types import TextContent, Tool

from uteki_api.mcp.client import UtekiClient

logger = logging.getLogger(__name__)

# Module-level client; ``build_server()`` constructs it once per process.
_client: UtekiClient | None = None


def _get_client() -> UtekiClient:
    global _client
    if _client is None:
        _client = UtekiClient()
    return _client


# ─── tool schemas ─────────────────────────────────────────────────


TOOLS: list[Tool] = [
    Tool(
        name="uteki_list_skills",
        description=(
            "List uteki's registered skills (research, earnings, planner, "
            "evaluator, research_pipeline, ...). Returns name, description, "
            "version, default tools, and whether each is a leaf skill or a "
            "pipeline meta-skill. No arguments."
        ),
        inputSchema={"type": "object", "properties": {}, "additionalProperties": False},
    ),
    Tool(
        name="uteki_run_skill",
        description=(
            "Kick off a uteki skill with a question. Returns immediately "
            "with a run_id; the run continues in the background. Poll with "
            "uteki_get_run to check status. For pipeline runs "
            "(research_pipeline) expect 1-3 minutes; leaf skills are faster."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "skill": {
                    "type": "string",
                    "description": "Skill name; see uteki_list_skills.",
                },
                "question": {
                    "type": "string",
                    "description": "User-facing question for the skill.",
                },
                "session_id": {
                    "type": "string",
                    "description": "Optional session id for grouping related runs.",
                },
                "model": {
                    "type": "string",
                    "description": (
                        "Optional model override, e.g. 'anthropic/claude-sonnet-4-6' "
                        "or 'deepseek/deepseek-chat'. Skill default is used otherwise."
                    ),
                },
            },
            "required": ["skill", "question"],
            "additionalProperties": False,
        },
    ),
    Tool(
        name="uteki_get_run",
        description=(
            "Get a run's current state: status (running/ok/error/timeout), "
            "summary, started_at/ended_at, usage_summary (tokens, cost), "
            "tags, and the full event list. Poll periodically while a run "
            "is in progress."
        ),
        inputSchema={
            "type": "object",
            "properties": {"run_id": {"type": "string"}},
            "required": ["run_id"],
            "additionalProperties": False,
        },
    ),
    Tool(
        name="uteki_list_artifacts",
        description=(
            "List artifacts a run produced. Each entry has name, kind "
            "(markdown/json/text/binary), size_bytes, written_by, "
            "description. Use uteki_read_artifact to fetch one by name."
        ),
        inputSchema={
            "type": "object",
            "properties": {"run_id": {"type": "string"}},
            "required": ["run_id"],
            "additionalProperties": False,
        },
    ),
    Tool(
        name="uteki_read_artifact",
        description=(
            "Read one artifact by name. Returns the file's text content "
            "(text and JSON artifacts are returned verbatim; binary is "
            "base64-encoded). Common names: plan.md, sprint-contract.json, "
            "final-research.md, eval-report.json, judge-*.json, run-trace.json."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "run_id": {"type": "string"},
                "name": {"type": "string"},
            },
            "required": ["run_id", "name"],
            "additionalProperties": False,
        },
    ),
]


# ─── tool handlers ────────────────────────────────────────────────


async def _tool_list_skills(_args: dict[str, Any]) -> list[TextContent]:
    items = await _get_client().list_skills()
    return [TextContent(type="text", text=json.dumps({"items": items}, ensure_ascii=False))]


async def _tool_run_skill(args: dict[str, Any]) -> list[TextContent]:
    res = await _get_client().start_run(
        agent=args["skill"],
        question=args["question"],
        session_id=args.get("session_id"),
        model=args.get("model"),
    )
    return [TextContent(type="text", text=json.dumps(res, ensure_ascii=False))]


async def _tool_get_run(args: dict[str, Any]) -> list[TextContent]:
    res = await _get_client().get_run(args["run_id"])
    # Run records can be 100KB+ with full event lists. CC's context is
    # precious — strip the verbose ``events`` array down to a summary.
    # If the caller needs raw events, they can read run-trace.json
    # (the pipeline writes it) or query the API directly.
    events = res.pop("events", [])
    res["events_count"] = len(events)
    res["events_summary"] = _events_summary(events)
    return [TextContent(type="text", text=json.dumps(res, ensure_ascii=False))]


def _events_summary(events: list[dict[str, Any]]) -> dict[str, int]:
    """Type → count, so CC can see the shape of the run without the bulk."""
    counts: dict[str, int] = {}
    for e in events:
        t = e.get("type", "?")
        counts[t] = counts.get(t, 0) + 1
    return counts


async def _tool_list_artifacts(args: dict[str, Any]) -> list[TextContent]:
    items = await _get_client().list_artifacts(args["run_id"])
    return [TextContent(type="text", text=json.dumps({"items": items}, ensure_ascii=False))]


async def _tool_read_artifact(args: dict[str, Any]) -> list[TextContent]:
    import base64

    content, content_type = await _get_client().read_artifact(args["run_id"], args["name"])
    # Text-ish content_types (markdown/json/text) return UTF-8 directly;
    # binary falls back to base64. CC reasons well over markdown/json.
    if content_type.startswith(("text/", "application/json", "application/x-ndjson")):
        try:
            return [TextContent(type="text", text=content.decode("utf-8"))]
        except UnicodeDecodeError:
            pass
    encoded = base64.b64encode(content).decode("ascii")
    return [
        TextContent(
            type="text",
            text=json.dumps(
                {"encoding": "base64", "content_type": content_type, "data": encoded},
                ensure_ascii=False,
            ),
        )
    ]


_HANDLERS: dict[str, Any] = {
    "uteki_list_skills": _tool_list_skills,
    "uteki_run_skill": _tool_run_skill,
    "uteki_get_run": _tool_get_run,
    "uteki_list_artifacts": _tool_list_artifacts,
    "uteki_read_artifact": _tool_read_artifact,
}


# ─── server factory ───────────────────────────────────────────────


def build_server() -> Server:
    """Construct an MCP ``Server`` with all uteki tools wired up.

    Decorators register the handlers on the underlying ``Server`` instance;
    the caller is responsible for connecting it to a transport (stdio in
    ``__main__.py``, in-process in tests).
    """
    server: Server = Server("uteki")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return TOOLS

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
        handler = _HANDLERS.get(name)
        if handler is None:
            return [TextContent(type="text", text=f"unknown tool: {name}")]
        try:
            return await handler(arguments or {})
        except Exception as e:  # noqa: BLE001 — surface to client, never raise out of MCP loop
            logger.exception("tool %s failed", name)
            return [
                TextContent(
                    type="text",
                    text=json.dumps(
                        {"error": str(e), "tool": name, "type": type(e).__name__},
                        ensure_ascii=False,
                    ),
                )
            ]

    return server
