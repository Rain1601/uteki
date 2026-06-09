"""Company / watchlist domain.

Replaces the frontend-hardcoded ``INITIAL_WATCHLIST`` in
``apps/web/app/(app)/company-agent/page.tsx``. The Company table is the
single source of truth for "which tickers do we follow", and feeds both
the research desk watchlist and the upcoming SEC EDGAR / Yahoo news
ingestion pipelines (which need ``cik`` and ``ir_rss_url`` respectively).
"""

from uteki_api.companies.models import Company
from uteki_api.companies.store import CompanyStore, default_company_store

__all__ = ["Company", "CompanyStore", "default_company_store"]
