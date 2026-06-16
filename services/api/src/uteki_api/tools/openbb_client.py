"""Thin async client for the OpenBB Platform API sidecar.

OpenBB is AGPL-3.0; we deliberately do NOT import any openbb_* Python module
into this process. Instead the sidecar (services/openbb/) runs the OpenBB
Platform API on its own venv + Python interpreter, and we talk to it over
HTTP. License contamination is avoided as long as the sidecar runs as a
separate process — see services/openbb/README.md for the rationale.

Endpoint layout follows the OpenBB Platform router structure:
  /api/v1/economy/fred_series     — FRED historical series
  /api/v1/economy/fred_search     — FRED catalog search
  /api/v1/equity/fundamental/...  — financial statements
  /api/v1/equity/calendar/...     — earnings + dividends
  /api/v1/equity/estimates/...    — analyst targets, EPS surprises
  /api/v1/equity/ownership/...    — insider + institutional + 13F

The OpenBB response envelope is consistent: ``{"results": [...], "warnings":
[...], "chart": null, "extra": {...}}``. We unwrap ``results`` for the
caller; warnings/extra are surfaced via ``warnings`` for source pruning.
"""

from __future__ import annotations

import os
from typing import Any

import httpx


class OpenBBSidecarError(Exception):
    """Raised when the sidecar is unreachable or returns a non-2xx response.

    Tools catch this and degrade to ``ToolResult(ok=False, error=...)``
    rather than throwing — the agent loop should keep going with a clear
    "tool failed" signal, not crash the harness.
    """


class OpenBBClient:
    """HTTP client for the sidecar. One instance per process is fine — httpx
    keeps a small connection pool internally."""

    def __init__(self, base_url: str | None = None, timeout: float = 20.0) -> None:
        self.base_url = (
            base_url
            or os.getenv("UTEKI_OPENBB_BASE_URL")
            or "http://127.0.0.1:6900"
        ).rstrip("/")
        self.timeout = timeout

    async def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """GET ``{base}/api/v1{path}`` and return the parsed JSON envelope.

        Drops keys whose value is None — OpenBB rejects ``key=None``
        rather than treating it as "unset", so we strip before sending.
        """
        cleaned = {k: v for k, v in (params or {}).items() if v is not None}
        url = f"{self.base_url}/api/v1{path}"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                resp = await client.get(url, params=cleaned)
            except httpx.HTTPError as e:
                raise OpenBBSidecarError(f"sidecar unreachable: {e}") from e
        if resp.status_code >= 400:
            raise OpenBBSidecarError(
                f"sidecar {resp.status_code} on {path}: {resp.text[:200]}"
            )
        try:
            return resp.json()
        except ValueError as e:
            raise OpenBBSidecarError(f"sidecar returned non-JSON: {e}") from e


default_openbb_client = OpenBBClient()
