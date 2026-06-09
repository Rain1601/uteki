"""Company (watchlist) CRUD endpoints.

- ``GET /api/companies`` — list watchlist; any authed user (the research
  desk and admin views both read this).
- ``POST /api/companies`` — upsert by symbol; admin-only. Re-POSTing an
  archived symbol revives it (watch=True).
- ``PATCH /api/companies/{symbol}`` — partial update; admin-only.
- ``DELETE /api/companies/{symbol}`` — soft archive (watch=False);
  admin-only. Use ``?hard=true`` to actually delete the row (rare).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlmodel import Session

from uteki_api.auth.deps import current_user, require_admin
from uteki_api.companies.models import Company
from uteki_api.companies.store import default_company_store
from uteki_api.core.db import get_db
from uteki_api.users.models import User

router = APIRouter(prefix="/api/companies", tags=["companies"])


# ─── Schemas ─────────────────────────────────────────────────────────


class CompanyOut(BaseModel):
    symbol: str
    name: str
    market: str
    sector: str
    peers: list[str]
    cik: str | None
    ir_rss_url: str | None
    watch: bool
    verdict: str
    conviction: float | None
    notes: str
    created_at: str
    updated_at: str


class CompanyCreate(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=16)
    name: str = Field(..., min_length=1, max_length=200)
    market: str = Field("US", pattern=r"^(US|CN|HK|TW)$")
    sector: str = ""
    peers: list[str] = Field(default_factory=list)
    cik: str | None = Field(default=None, max_length=12)
    ir_rss_url: str | None = Field(default=None, max_length=512)
    verdict: str = Field("UNRATED", pattern=r"^(BUY|WATCH|AVOID|UNRATED)$")
    conviction: float | None = Field(default=None, ge=0, le=1)
    notes: str = ""


class CompanyUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    market: str | None = Field(default=None, pattern=r"^(US|CN|HK|TW)$")
    sector: str | None = None
    peers: list[str] | None = None
    cik: str | None = Field(default=None, max_length=12)
    ir_rss_url: str | None = Field(default=None, max_length=512)
    watch: bool | None = None
    verdict: str | None = Field(default=None, pattern=r"^(BUY|WATCH|AVOID|UNRATED)$")
    conviction: float | None = Field(default=None, ge=0, le=1)
    notes: str | None = None


def _split_csv(raw: str) -> list[str]:
    return [s.strip() for s in raw.split(",") if s.strip()]


def _join_csv(items: list[str]) -> str:
    return ",".join(s.strip().upper() for s in items if s.strip())


def _out(company: Company) -> CompanyOut:
    return CompanyOut(
        symbol=company.symbol,
        name=company.name,
        market=company.market,
        sector=company.sector,
        peers=_split_csv(company.peers),
        cik=company.cik,
        ir_rss_url=company.ir_rss_url,
        watch=company.watch,
        verdict=company.verdict,
        conviction=company.conviction,
        notes=company.notes,
        created_at=company.created_at.isoformat(),
        updated_at=company.updated_at.isoformat(),
    )


# ─── Routes ──────────────────────────────────────────────────────────


@router.get("", response_model=list[CompanyOut])
async def list_companies(
    watch_only: bool = Query(True, description="Only return watch=True rows"),
    market: str | None = Query(None, pattern=r"^(US|CN|HK|TW)$"),
    _user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> list[CompanyOut]:
    rows = default_company_store.list(db, watch_only=watch_only, market=market)
    return [_out(c) for c in rows]


@router.post("", response_model=CompanyOut, status_code=201)
async def create_or_revive_company(
    body: CompanyCreate,
    _user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> CompanyOut:
    company = default_company_store.upsert(
        db,
        symbol=body.symbol,
        name=body.name,
        market=body.market,
        sector=body.sector,
        peers=_join_csv(body.peers),
        cik=body.cik,
        ir_rss_url=body.ir_rss_url,
        watch=True,
        verdict=body.verdict,
        conviction=body.conviction,
        notes=body.notes,
    )
    return _out(company)


@router.patch("/{symbol}", response_model=CompanyOut)
async def update_company(
    symbol: str,
    body: CompanyUpdate,
    _user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> CompanyOut:
    patch: dict = body.model_dump(exclude_unset=True)
    if "peers" in patch and patch["peers"] is not None:
        patch["peers"] = _join_csv(patch["peers"])
    updated = default_company_store.update(db, symbol, **patch)
    if updated is None:
        raise HTTPException(404, detail=f"company {symbol} not found")
    return _out(updated)


@router.delete("/{symbol}", status_code=204)
async def delete_company(
    symbol: str,
    hard: bool = Query(False, description="Permanently delete vs. archive"),
    _user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> None:
    company = default_company_store.get(db, symbol)
    if company is None:
        raise HTTPException(404, detail=f"company {symbol} not found")
    if hard:
        db.delete(company)
        db.commit()
    else:
        default_company_store.archive(db, symbol)
