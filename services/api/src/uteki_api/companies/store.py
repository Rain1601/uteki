"""CompanyStore — thin DB facade over the ``company`` table.

Follows the same pattern as ``UserStore`` and ``NewsStore``: ABC + sql
impl + module-level singleton ``default_company_store``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import UTC, datetime

from sqlalchemy import func
from sqlmodel import Session, select

from uteki_api.companies.models import Company


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _normalize_symbol(symbol: str) -> str:
    return symbol.strip().upper()


class CompanyStore(ABC):
    @abstractmethod
    def list(
        self,
        db: Session,
        *,
        watch_only: bool = True,
        market: str | None = None,
    ) -> list[Company]: ...

    @abstractmethod
    def count_watching(self, db: Session) -> int: ...

    @abstractmethod
    def get(self, db: Session, symbol: str) -> Company | None: ...

    @abstractmethod
    def upsert(
        self,
        db: Session,
        *,
        symbol: str,
        name: str,
        market: str = "US",
        sector: str = "",
        peers: str = "",
        cik: str | None = None,
        ir_rss_url: str | None = None,
        watch: bool = True,
        verdict: str = "UNRATED",
        conviction: float | None = None,
        notes: str = "",
    ) -> Company: ...

    @abstractmethod
    def update(
        self,
        db: Session,
        symbol: str,
        **fields: object,
    ) -> Company | None: ...

    @abstractmethod
    def archive(self, db: Session, symbol: str) -> Company | None:
        """Soft-delete: set watch=False. Preserves notes + verdict history."""
        ...


class SqlCompanyStore(CompanyStore):
    def list(
        self,
        db: Session,
        *,
        watch_only: bool = True,
        market: str | None = None,
    ) -> list[Company]:
        stmt = select(Company)
        if watch_only:
            stmt = stmt.where(Company.watch == True)  # noqa: E712
        if market:
            stmt = stmt.where(Company.market == market)
        # Stable display order: market → symbol.
        return list(db.exec(stmt.order_by(Company.market, Company.symbol)).all())

    def count_watching(self, db: Session) -> int:
        return int(
            db.exec(
                select(func.count()).select_from(  # type: ignore[arg-type]
                    select(Company).where(Company.watch == True).subquery()  # noqa: E712
                )
            ).one()
        )

    def get(self, db: Session, symbol: str) -> Company | None:
        return db.get(Company, _normalize_symbol(symbol))

    def upsert(
        self,
        db: Session,
        *,
        symbol: str,
        name: str,
        market: str = "US",
        sector: str = "",
        peers: str = "",
        cik: str | None = None,
        ir_rss_url: str | None = None,
        watch: bool = True,
        verdict: str = "UNRATED",
        conviction: float | None = None,
        notes: str = "",
    ) -> Company:
        normalized = _normalize_symbol(symbol)
        now = _utcnow()
        existing = db.get(Company, normalized)
        if existing is None:
            company = Company(
                symbol=normalized,
                name=name,
                market=market,
                sector=sector,
                peers=peers,
                cik=cik,
                ir_rss_url=ir_rss_url,
                watch=watch,
                verdict=verdict,
                conviction=conviction,
                notes=notes,
                created_at=now,
                updated_at=now,
            )
        else:
            existing.name = name
            existing.market = market
            existing.sector = sector
            existing.peers = peers
            existing.cik = cik
            existing.ir_rss_url = ir_rss_url
            existing.watch = watch
            existing.verdict = verdict
            existing.conviction = conviction
            existing.notes = notes
            existing.updated_at = now
            company = existing
        db.add(company)
        db.commit()
        db.refresh(company)
        return company

    def update(
        self,
        db: Session,
        symbol: str,
        **fields: object,
    ) -> Company | None:
        normalized = _normalize_symbol(symbol)
        company = db.get(Company, normalized)
        if company is None:
            return None
        for key, value in fields.items():
            if value is None and key in {"sector", "peers", "name", "notes", "verdict", "market"}:
                # null patch on required fields = no-op (don't blank string columns).
                continue
            setattr(company, key, value)
        company.updated_at = _utcnow()
        db.add(company)
        db.commit()
        db.refresh(company)
        return company

    def archive(self, db: Session, symbol: str) -> Company | None:
        return self.update(db, symbol, watch=False)


default_company_store: CompanyStore = SqlCompanyStore()
