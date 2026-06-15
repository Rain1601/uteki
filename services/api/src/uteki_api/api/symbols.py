"""Symbol search — live ticker lookup against SEC EDGAR.

Provides ``GET /api/symbols/search?q=...`` for the watchlist sidebar. The
universe is SEC's ``company_tickers.json`` (all US-listed: NASDAQ + NYSE +
AMEX, including the entire S&P 500). It's the official, no-key, daily-updated
source — no static fixture.

Cache: in-memory, 24h TTL. The same JSON powers ``tools/report_analysis.py``
but that module's cache is keyed on ticker→CIK only and discards the name;
search needs the name too, so we maintain a parallel list cache here.

Ranking: exact symbol > symbol-prefix > symbol-substring > name-substring.
Stable secondary order is the SEC's own order (which roughly tracks CIK
issuance, useful as a tie-breaker but not semantically meaningful).
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from uteki_api.auth.deps import current_user
from uteki_api.users.models import User

router = APIRouter(prefix="/api/symbols", tags=["symbols"])


_TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"
_CACHE_TTL_SECONDS = 24 * 60 * 60


class _SymbolEntry(BaseModel):
    symbol: str
    name: str
    cik: str


class SymbolHit(BaseModel):
    symbol: str
    name: str
    cik: str
    source: str = "sec"


def _sec_user_agent() -> str:
    """SEC's fair-access policy requires a descriptive UA with contact info."""
    from uteki_api.core.config import settings

    admin_emails = (settings.admin_emails or "").split(",")
    contact = next(
        (e.strip() for e in admin_emails if "@" in e),
        "uteki-ops@example.invalid",
    )
    return f"uteki-research-agent ({contact})"


_cache: list[_SymbolEntry] | None = None
_cache_at: float = 0.0
_cache_lock = asyncio.Lock()


async def _load_universe() -> list[_SymbolEntry]:
    """Fetch + cache the SEC ticker universe (24h TTL)."""
    global _cache, _cache_at
    now = time.monotonic()
    if _cache is not None and (now - _cache_at) < _CACHE_TTL_SECONDS:
        return _cache
    async with _cache_lock:
        if _cache is not None and (time.monotonic() - _cache_at) < _CACHE_TTL_SECONDS:
            return _cache
        async with httpx.AsyncClient(
            timeout=20.0,
            headers={"User-Agent": _sec_user_agent()},
        ) as client:
            resp = await client.get(_TICKER_MAP_URL)
            resp.raise_for_status()
            raw: dict[str, Any] = resp.json()
        entries: list[_SymbolEntry] = []
        for value in raw.values():
            ticker = str(value.get("ticker", "")).strip().upper()
            title = str(value.get("title", "")).strip()
            cik = str(value.get("cik_str", "")).strip()
            if ticker and title and cik:
                entries.append(
                    _SymbolEntry(symbol=ticker, name=title, cik=cik.zfill(10))
                )
        _cache = entries
        _cache_at = time.monotonic()
        return entries


def _rank(entry: _SymbolEntry, q: str) -> int:
    """Lower is better. Returns a sortable rank or ``-1`` for no match."""
    sym = entry.symbol
    if sym == q:
        return 0
    if sym.startswith(q):
        return 1
    if q in sym:
        return 2
    if q in entry.name.upper():
        return 3
    return -1


@router.get("/search", response_model=list[SymbolHit])
async def search_symbols(
    q: str = Query(..., min_length=1, max_length=64, description="Ticker or name fragment"),
    limit: int = Query(10, ge=1, le=50),
    _user: User = Depends(current_user),
) -> list[SymbolHit]:
    needle = q.strip().upper()
    if not needle:
        return []
    try:
        universe = await _load_universe()
    except httpx.HTTPError as e:
        raise HTTPException(502, detail=f"SEC ticker universe unavailable: {e}") from e

    scored: list[tuple[int, int, _SymbolEntry]] = []
    for idx, entry in enumerate(universe):
        rank = _rank(entry, needle)
        if rank >= 0:
            scored.append((rank, idx, entry))
            # Short-circuit: an exact-symbol match is the only thing the user
            # wants. Anything ranked > 0 still needs the full sweep because
            # name-substring matches can be anywhere in the universe.
            if rank == 0 and len(scored) >= limit:
                break

    scored.sort(key=lambda t: (t[0], t[1]))
    return [
        SymbolHit(symbol=e.symbol, name=e.name, cik=e.cik)
        for _, _, e in scored[:limit]
    ]
