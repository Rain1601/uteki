"""SEC EDGAR-backed filings analyzer — Phase C.2.

Replaces the mock placeholder with real SEC integration:

1. Symbol → CIK via the (cached) public ticker map at
   ``https://www.sec.gov/files/company_tickers.json``.
2. CIK → most recent filings via
   ``https://data.sec.gov/submissions/CIK{padded}.json``.
3. Filing → primary document URL via the recent-filings table.
4. Document → cleaned text via the same httpx + BeautifulSoup pipeline
   web_extract uses (C.3b).
5. Text → focus-relevant section via heuristic 10-K item-heading match.

Tool inputs:
- ``symbol``  US ticker (preferred — triggers the SEC flow)
- ``url``     direct link to a filing or report (works for non-SEC too)
- ``text``    pre-fetched text (skips the network entirely)
- ``focus``   one of summary / risks / opportunities / financials
- ``filing_type``  default '10-K', also accepts '10-Q', '8-K', etc.

SEC requires every request to carry a descriptive User-Agent
identifying the requester. We use ``uteki-research-agent`` with the
operator's email from ``UTEKI_ADMIN_EMAILS`` if set, falling back to a
placeholder. Operators should set ``UTEKI_ADMIN_EMAILS`` to a real
contact in prod or SEC may rate-limit / block.

Mock-data mode (UTEKI_USE_MOCK_DATA=true) returns the original
deterministic placeholder so the E2E suite remains hermetic.
"""

from __future__ import annotations

import re
import threading
from datetime import UTC, datetime
from typing import Any

import httpx

from uteki_api.core.config import settings
from uteki_api.tools.base import Tool, ToolResult

# ─── Focus → section heading patterns ────────────────────────────────
# Each focus maps to (a) the legacy mock headings (Chinese), still used
# in mock mode, and (b) regex patterns matching the standard 10-K item
# titles used by SEC filings (English, anchored to start of line).

_FOCUS_HEADINGS = {
    "summary": ["核心摘要", "业绩总览", "管理层观点"],
    "risks": ["主要风险", "宏观风险", "经营风险"],
    "opportunities": ["增长机会", "市场扩张", "新产品 / 新业务"],
    "financials": ["营收结构", "盈利能力", "现金流"],
}

# Patterns hunt for the boundary heading. The 10-K item numbering is
# remarkably stable across filers.
_FOCUS_10K_PATTERNS: dict[str, list[re.Pattern[str]]] = {
    "summary": [
        re.compile(r"item\s+1\.?\s+business", re.IGNORECASE),
        re.compile(r"^business$", re.IGNORECASE | re.MULTILINE),
    ],
    "risks": [
        re.compile(r"item\s+1a\.?\s+risk\s+factors", re.IGNORECASE),
        re.compile(r"^risk\s+factors$", re.IGNORECASE | re.MULTILINE),
    ],
    "opportunities": [
        # MD&A — the forward-looking section operators want for growth thesis.
        re.compile(
            r"item\s+7\.?\s+management.{0,3}s\s+discussion\s+and\s+analysis",
            re.IGNORECASE,
        ),
        re.compile(r"management.{0,3}s\s+discussion\s+and\s+analysis", re.IGNORECASE),
    ],
    "financials": [
        re.compile(r"item\s+8\.?\s+financial\s+statements", re.IGNORECASE),
        re.compile(r"^financial\s+statements", re.IGNORECASE | re.MULTILINE),
    ],
}

# The "next item" boundary — any further "Item N" heading ends the
# current section. Used to trim each extracted block.
_NEXT_ITEM_PATTERN = re.compile(r"\n\s*item\s+\d+[a-z]?\.?\s+[a-z]", re.IGNORECASE)

MAX_SECTION_CHARS = 12_000
TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL_TEMPLATE = "https://data.sec.gov/submissions/CIK{cik}.json"
ARCHIVE_URL_TEMPLATE = (
    "https://www.sec.gov/Archives/edgar/data/{cik}/{accession_no_dashes}/{primary_doc}"
)


def _sec_user_agent() -> str:
    """SEC requires a descriptive UA with contact email. Prefer the first
    admin email if configured, fall back to a placeholder."""
    admin_emails = (settings.admin_emails or "").split(",")
    contact = next(
        (e.strip() for e in admin_emails if "@" in e),
        "uteki-ops@example.invalid",
    )
    return f"uteki-research-agent ({contact})"


# ─── Lazy in-memory ticker → CIK cache ───────────────────────────────
_TICKER_CACHE: dict[str, str] | None = None
_TICKER_LOCK = threading.Lock()


async def _load_ticker_map() -> dict[str, str]:
    """Fetch + cache the SEC ticker→CIK map. Returns symbol-upper → 10-digit-CIK."""
    global _TICKER_CACHE
    if _TICKER_CACHE is not None:
        return _TICKER_CACHE
    async with httpx.AsyncClient(
        timeout=15.0,
        headers={"User-Agent": _sec_user_agent()},
    ) as client:
        resp = await client.get(TICKER_MAP_URL)
        resp.raise_for_status()
        raw = resp.json()
    # The map's keys are arbitrary integer strings; values have cik_str + ticker.
    mapping: dict[str, str] = {}
    for entry in raw.values():
        ticker = str(entry.get("ticker", "")).strip().upper()
        cik = str(entry.get("cik_str", "")).strip()
        if ticker and cik:
            mapping[ticker] = cik.zfill(10)
    with _TICKER_LOCK:
        _TICKER_CACHE = mapping
    return mapping


async def _resolve_cik(symbol: str) -> str | None:
    mapping = await _load_ticker_map()
    return mapping.get(symbol.strip().upper())


async def _fetch_latest_filing(
    cik_padded: str, filing_type: str
) -> dict[str, Any] | None:
    """Pull the recent-filings table and return the most recent entry of
    ``filing_type`` (e.g. '10-K'). Returns dict with accessionNumber,
    primaryDocument, filingDate, form."""
    url = SUBMISSIONS_URL_TEMPLATE.format(cik=cik_padded)
    async with httpx.AsyncClient(
        timeout=15.0,
        headers={"User-Agent": _sec_user_agent()},
    ) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        payload = resp.json()
    recent = payload.get("filings", {}).get("recent", {}) or {}
    forms: list[str] = recent.get("form", []) or []
    accessions: list[str] = recent.get("accessionNumber", []) or []
    docs: list[str] = recent.get("primaryDocument", []) or []
    dates: list[str] = recent.get("filingDate", []) or []
    target = filing_type.upper()
    for i, form in enumerate(forms):
        if str(form).upper() == target:
            return {
                "form": form,
                "accession_number": accessions[i] if i < len(accessions) else "",
                "primary_document": docs[i] if i < len(docs) else "",
                "filing_date": dates[i] if i < len(dates) else "",
            }
    return None


def _filing_doc_url(cik_padded: str, accession_no: str, primary_doc: str) -> str:
    # accession looks like "0000320193-23-000106"; archive paths use the dashless form.
    cik_no_pad = cik_padded.lstrip("0") or "0"
    accession_no_dashes = accession_no.replace("-", "")
    return ARCHIVE_URL_TEMPLATE.format(
        cik=cik_no_pad,
        accession_no_dashes=accession_no_dashes,
        primary_doc=primary_doc,
    )


async def _fetch_clean_text(url: str) -> str:
    """Fetch a filing HTML doc and reduce to plain text. Reuses the same
    bs4 approach as web_extract but skips structural prefixes — we want
    the LLM to see prose, not '# heading' markdown."""
    from bs4 import BeautifulSoup  # lazy import (same pattern as web_extract)

    async with httpx.AsyncClient(
        timeout=20.0,
        headers={"User-Agent": _sec_user_agent()},
        follow_redirects=True,
    ) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        html = resp.text
    soup = BeautifulSoup(html, "lxml")
    for noisy in soup.find_all(("script", "style", "noscript")):
        noisy.decompose()
    text = soup.get_text(separator="\n", strip=True)
    # Collapse run-on whitespace SEC filings sometimes emit
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _extract_focus_section(text: str, focus: str) -> str:
    """Find the focus's heading in the raw filing text, return a window
    from there up to the next ``Item N`` heading (capped)."""
    patterns = _FOCUS_10K_PATTERNS.get(focus, [])
    for pat in patterns:
        m = pat.search(text)
        if not m:
            continue
        start = m.start()
        rest = text[start:]
        # find next item boundary AFTER our heading match
        next_m = _NEXT_ITEM_PATTERN.search(rest, pos=len(m.group(0)))
        end = next_m.start() if next_m else len(rest)
        section = rest[:end].strip()
        if len(section) > MAX_SECTION_CHARS:
            section = section[:MAX_SECTION_CHARS] + (
                f"\n\n…[truncated, full section {len(section)} chars]"
            )
        return section
    return ""


def _sections_from_focus(focus: str, text: str) -> list[dict[str, Any]]:
    """Break the extracted focus block into ~3 reading-sized bullets so
    the tool's return shape stays compatible with the mock's
    ``[{heading, bullets[]}, ...]``."""
    if not text:
        return []
    # Split on paragraph breaks; take the first ~6 substantive paragraphs;
    # group them under the focus heading. Operators (LLM) get clean prose
    # without needing to parse all 12K of section text.
    paras = [p.strip() for p in text.split("\n\n") if len(p.strip()) > 40]
    bullets = paras[:6]
    heading_label = {
        "summary": "Item 1 — Business",
        "risks": "Item 1A — Risk Factors",
        "opportunities": "Item 7 — MD&A",
        "financials": "Item 8 — Financial Statements",
    }.get(focus, focus)
    return [{"heading": heading_label, "bullets": bullets}]


# ─── Mock branch (legacy, kept for hermetic E2E) ─────────────────────


def _mock_sections(focus: str) -> tuple[list[dict[str, Any]], int]:
    sections: list[dict[str, Any]] = []
    bullet_count = 0
    for heading in _FOCUS_HEADINGS[focus]:
        bullets = [
            f"{heading} 要点 #{i + 1}：这是一段占位的结构化结论。"
            for i in range(3)
        ]
        bullet_count += len(bullets)
        sections.append({"heading": heading, "bullets": bullets})
    return sections, bullet_count


class ReportAnalysisTool(Tool):
    name = "report_analysis"
    description = (
        "解析公司财报 / 研报。优先支持 SEC EDGAR（传 symbol，自动找最新 10-K/10-Q），"
        "也支持直接 url（PDF / HTML）或纯 text。focus = summary / risks / opportunities / financials。"
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "symbol": {
                "type": "string",
                "description": "美股 ticker，例如 'AAPL'。会去 SEC EDGAR 找最新 filing。",
            },
            "url": {
                "type": "string",
                "format": "uri",
                "description": "财报 / 研报的 URL（非 SEC 也可用）",
            },
            "text": {
                "type": "string",
                "description": "已经准备好的纯文本（跳过抓取）",
            },
            "filing_type": {
                "type": "string",
                "enum": ["10-K", "10-Q", "8-K", "20-F", "DEF 14A", "S-1"],
                "default": "10-K",
                "description": "SEC filing 类型（symbol 模式下使用）",
            },
            "focus": {
                "type": "string",
                "enum": ["summary", "risks", "opportunities", "financials"],
                "default": "summary",
                "description": "聚焦的解析维度",
            },
        },
    }

    async def run(self, **kwargs: Any) -> ToolResult:
        symbol = (kwargs.get("symbol") or "").strip()
        url = kwargs.get("url")
        text = kwargs.get("text")
        focus = kwargs.get("focus", "summary")
        filing_type = (kwargs.get("filing_type") or "10-K").upper()
        if not symbol and not url and not text:
            return ToolResult(ok=False, error="symbol, url, or text is required")
        if focus not in _FOCUS_HEADINGS:
            return ToolResult(ok=False, error=f"invalid focus: {focus}")

        # ── Mock branch — kept hermetic for E2E ──
        if settings.use_mock_data:
            source = (
                f"sec://{symbol}/{filing_type}" if symbol else (url or "inline-text")
            )
            sections, bullet_count = _mock_sections(focus)
            return ToolResult(
                ok=True,
                summary=f"提取到 {bullet_count} 个要点（mock）",
                data={
                    "title": f"[mock] {symbol or 'document'} - {focus}",
                    "source": source,
                    "sections": sections,
                },
            )

        # ── Real branches ──
        if symbol:
            return await self._analyze_symbol(symbol, filing_type, focus)
        if url:
            return await self._analyze_url(url, focus)
        # text branch
        section_text = _extract_focus_section(text or "", focus)
        sections = _sections_from_focus(focus, section_text or (text or "")[:4000])
        bullets = sum(len(s["bullets"]) for s in sections)
        return ToolResult(
            ok=True,
            summary=f"提取到 {bullets} 个段落（from text）",
            data={
                "title": f"inline text — {focus}",
                "source": "inline-text",
                "sections": sections,
            },
        )

    async def _analyze_symbol(
        self, symbol: str, filing_type: str, focus: str
    ) -> ToolResult:
        try:
            cik = await _resolve_cik(symbol)
        except (httpx.HTTPError, TimeoutError) as e:
            return ToolResult(
                ok=False,
                summary=f"SEC ticker lookup failed: {type(e).__name__}",
                error=str(e),
            )
        if not cik:
            return ToolResult(
                ok=False,
                summary=f"symbol {symbol!r} not found in SEC ticker map",
                error="unknown symbol",
            )

        try:
            filing = await _fetch_latest_filing(cik, filing_type)
        except (httpx.HTTPError, TimeoutError) as e:
            return ToolResult(
                ok=False,
                summary=f"SEC submissions fetch failed: {type(e).__name__}",
                error=str(e),
            )
        if not filing:
            return ToolResult(
                ok=False,
                summary=f"no {filing_type} found for {symbol} (CIK {cik})",
                error="no matching filing",
            )

        doc_url = _filing_doc_url(
            cik, filing["accession_number"], filing["primary_document"]
        )
        try:
            full_text = await _fetch_clean_text(doc_url)
        except (httpx.HTTPError, TimeoutError) as e:
            return ToolResult(
                ok=False,
                summary=f"SEC document fetch failed: {type(e).__name__}",
                error=str(e),
            )

        section_text = _extract_focus_section(full_text, focus)
        sections = _sections_from_focus(
            focus, section_text or full_text[:4000]
        )
        bullets = sum(len(s["bullets"]) for s in sections)
        return ToolResult(
            ok=True,
            summary=(
                f"{symbol} {filing['form']} ({filing['filing_date']}) → "
                f"{bullets} 段 from {focus}"
            ),
            data={
                "title": f"{symbol} {filing['form']} — {focus}",
                "source": doc_url,
                "filing": filing,
                "sections": sections,
            },
            sources=[
                {
                    "key": f"sec_edgar:{symbol}:{filing['form']}:{filing['filing_date']}",
                    "value": {
                        "symbol": symbol,
                        "form": filing["form"],
                        "filing_date": filing["filing_date"],
                        "primary_document": filing["primary_document"],
                    },
                    "source_type": "sec_edgar",
                    "source_url": doc_url,
                    "publisher": "SEC EDGAR",
                    "published_at": filing["filing_date"],
                    "fetched_at": datetime.now(UTC).isoformat(),
                    "confidence": "high",
                    "excerpt": (section_text or full_text[:300])[:300],
                }
            ],
        )

    async def _analyze_url(self, url: str, focus: str) -> ToolResult:
        try:
            full_text = await _fetch_clean_text(url)
        except (httpx.HTTPError, TimeoutError) as e:
            return ToolResult(
                ok=False,
                summary=f"fetch failed: {type(e).__name__}",
                error=str(e),
            )
        section_text = _extract_focus_section(full_text, focus)
        sections = _sections_from_focus(focus, section_text or full_text[:4000])
        bullets = sum(len(s["bullets"]) for s in sections)
        return ToolResult(
            ok=True,
            summary=f"提取到 {bullets} 段 from {focus}",
            data={
                "title": f"{url} — {focus}",
                "source": url,
                "sections": sections,
            },
            sources=[
                {
                    "key": f"report:{url}",
                    "value": {"url": url, "focus": focus},
                    "source_type": "report",
                    "source_url": url,
                    "fetched_at": datetime.now(UTC).isoformat(),
                    "confidence": "medium",
                    "excerpt": (section_text or full_text[:300])[:300],
                }
            ],
        )
