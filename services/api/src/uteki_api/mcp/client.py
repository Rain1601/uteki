"""HTTP client to uteki's REST API.

Owned by the MCP server. Holds one ``httpx.AsyncClient`` configured to
talk to ``UTEKI_API_BASE`` (default ``http://localhost:8000``). No auth
headers — MVP relies on uteki's anonymous mode falling back to
``demo@local``. If ``UTEKI_AUTH_REQUIRED=true``, every call will 401 and
the MCP server will surface that error.
"""

from __future__ import annotations

import os
from typing import Any

import httpx


class UtekiClient:
    """Async HTTP client for uteki's REST API.

    Used inside MCP tool handlers. One instance per MCP server process.
    """

    def __init__(self, base_url: str | None = None, timeout: float = 30.0) -> None:
        # Env override lets `claude mcp add` point at a non-default host
        # without rebuilding the script wrapper.
        self.base_url = (
            base_url
            or os.getenv("UTEKI_API_BASE")
            or "http://localhost:8000"
        ).rstrip("/")
        # 30s default; /api/agent/start returns in <2s but pipeline status
        # polling occasionally goes slower under load. Read-only endpoints
        # are well below this.
        self._client = httpx.AsyncClient(timeout=timeout)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _get(self, path: str, **kwargs: Any) -> Any:
        r = await self._client.get(f"{self.base_url}{path}", **kwargs)
        r.raise_for_status()
        return r.json()

    async def _post(self, path: str, **kwargs: Any) -> Any:
        r = await self._client.post(f"{self.base_url}{path}", **kwargs)
        r.raise_for_status()
        return r.json()

    # ── skills catalog ──────────────────────────────────────────────

    async def list_skills(self) -> list[dict[str, Any]]:
        body = await self._get("/api/agents")
        return body.get("items", [])

    # ── runs ────────────────────────────────────────────────────────

    async def start_run(
        self,
        agent: str,
        question: str,
        session_id: str | None = None,
        model: str | None = None,
    ) -> dict[str, Any]:
        """Fire-and-forget. Returns ``{run_id, agent, status: 'running'}``."""
        return await self._post(
            "/api/agent/start",
            json={
                "messages": [{"role": "user", "content": question}],
                "agent": agent,
                "session_id": session_id,
                "model": model,
            },
        )

    async def get_run(self, run_id: str) -> dict[str, Any]:
        """Full run record including events list."""
        return await self._get(f"/api/runs/{run_id}")

    # ── artifacts ───────────────────────────────────────────────────

    async def list_artifacts(self, run_id: str) -> list[dict[str, Any]]:
        body = await self._get(f"/api/runs/{run_id}/artifacts")
        return body.get("items", [])

    async def read_artifact(self, run_id: str, name: str) -> tuple[bytes, str]:
        """Return (content_bytes, content_type)."""
        r = await self._client.get(
            f"{self.base_url}/api/runs/{run_id}/artifacts/{name}"
        )
        r.raise_for_status()
        return r.content, r.headers.get("content-type", "application/octet-stream")
