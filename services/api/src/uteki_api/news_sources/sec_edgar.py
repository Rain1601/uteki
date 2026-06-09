"""SEC EDGAR Atom feed fetcher + parser.

EDGAR exposes a public Atom feed per CIK that lists recent filings. We
use it as the highest-quality, zero-noise source for material company
events: 8-K (current report), 10-Q (quarterly), 10-K (annual).

Compliance notes:

- SEC's Fair Access policy requires a descriptive ``User-Agent`` with a
  contact email. Configure via ``UTEKI_SEC_USER_AGENT`` env or pass
  ``user_agent=`` explicitly. We refuse to fetch if it's empty.
- Rate limit is 10 requests / second. We're well below that — one
  request per (CIK, form) pair per ingest cycle.

Atom shape (real example):

    <entry>
      <category term="8-K" label="form type" />
      <content type="text/xml">
        <accession-number>0000320193-26-000011</accession-number>
        <filing-date>2026-04-30</filing-date>
        <filing-type>8-K</filing-type>
        <form-name>Current report</form-name>
        <items-desc>items 2.02 and 9.01</items-desc>
        <filing-href>https://www.sec.gov/.../index.htm</filing-href>
      </content>
      <title>8-K  - Current report</title>
      <summary type="html"><b>Filed:</b> 2026-04-30 <b>AccNo:</b> ...
                          Item 2.02: Results of Operations...</summary>
      <updated>2026-04-30T16:30:41-04:00</updated>
    </entry>

The ``items-desc`` field is the key signal for 8-K event classification.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Iterable

import httpx

ATOM_NS = "http://www.w3.org/2005/Atom"
BASE_URL = "https://www.sec.gov/cgi-bin/browse-edgar"

# 8-K Item code → our 事件 tag name. Most observed Items map cleanly;
# anything not listed falls through to ``regulation`` (the catch-all).
# See https://www.sec.gov/files/form8-k.pdf for the canonical list.
ITEM_TO_EVENT_TAG: dict[str, str] = {
    "1.01": "m_and_a",       # Entry into a Material Definitive Agreement
    "1.02": "m_and_a",       # Termination of a Material Definitive Agreement
    "1.03": "regulation",    # Bankruptcy / Receivership
    "2.01": "m_and_a",       # Completion of Acquisition/Disposition
    "2.02": "earnings",      # Results of Operations and Financial Condition
    "2.03": "regulation",    # Direct Financial Obligation
    "2.04": "regulation",    # Triggering Events Accelerating Obligation
    "3.01": "regulation",    # Notice of Delisting / Failure to Satisfy
    "3.02": "regulation",    # Unregistered Sale of Equity Securities
    "5.02": "regulation",    # Departure of Directors / Officers
    "5.03": "regulation",    # Amendments to Articles / Bylaws
    "5.07": "regulation",    # Submission of Matters to Vote
    "7.01": "guidance",      # Regulation FD Disclosure
    "8.01": "regulation",    # Other Events
    "9.01": "regulation",    # Financial Statements and Exhibits
}

_ITEM_RE = re.compile(r"(\d+\.\d+)")


@dataclass
class Filing:
    accession: str          # SEC's unique filing ID, e.g. "0000320193-26-000011"
    cik: str                # zero-padded 10-digit
    form: str               # "8-K" | "10-Q" | "10-K" | "10-Q/A" | etc.
    title: str              # raw Atom <title>
    url: str                # filing index page URL
    filed_at: datetime      # UTC
    summary_html: str       # raw <summary> body (HTML markup)
    items: list[str]        # parsed item codes for 8-K, e.g. ["2.02", "9.01"]

    @property
    def event_tags(self) -> list[str]:
        """Mapped 事件 tag names for this filing's items. De-duplicated."""
        if not self.items:
            return ["regulation"] if self.form == "8-K" else ["earnings"]
        seen: list[str] = []
        for code in self.items:
            mapped = ITEM_TO_EVENT_TAG.get(code, "regulation")
            if mapped not in seen:
                seen.append(mapped)
        return seen


# ─── Public API ──────────────────────────────────────────────────────


async def fetch_filings(
    cik: str,
    *,
    forms: Iterable[str] = ("8-K", "10-Q", "10-K"),
    limit_per_form: int = 40,
    user_agent: str,
    timeout_s: float = 20.0,
) -> list[Filing]:
    """Fetch recent filings for a single CIK, across multiple forms.

    Aggregates results across all requested forms into one flat list.
    Caller decides how to dedup across runs (we use accession PK).
    """
    if not user_agent or "@" not in user_agent:
        raise ValueError(
            "SEC requires a User-Agent with contact email. "
            "Set UTEKI_SEC_USER_AGENT or pass user_agent= explicitly."
        )
    cik_padded = cik.strip().zfill(10)
    all_filings: list[Filing] = []
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(timeout_s),
        headers={"User-Agent": user_agent, "Accept-Encoding": "gzip"},
    ) as client:
        for form in forms:
            params = {
                "action": "getcompany",
                "CIK": cik_padded,
                "type": form,
                "dateb": "",
                "owner": "include",
                "count": str(limit_per_form),
                "output": "atom",
            }
            resp = await client.get(BASE_URL, params=params)
            resp.raise_for_status()
            all_filings.extend(_parse_atom(resp.text, cik=cik_padded))
    return all_filings


# ─── Parser ──────────────────────────────────────────────────────────


def _q(name: str) -> str:
    """Qualify an element name with the Atom namespace."""
    return f"{{{ATOM_NS}}}{name}"


def _parse_atom(xml_text: str, *, cik: str) -> list[Filing]:
    """Parse one EDGAR Atom response into Filing objects."""
    root = ET.fromstring(xml_text)
    out: list[Filing] = []
    for entry in root.findall(_q("entry")):
        # <content> children inherit the Atom namespace (the feed has
        # xmlns="..." on the root and no override on <content>), so we
        # have to query for them with the namespace too.
        content = entry.find(_q("content"))
        if content is None:
            continue

        accession = _text(content, "accession-number")
        form = _text(content, "filing-type")
        items_desc = _text(content, "items-desc")
        filing_href = _text(content, "filing-href")

        if not accession or not form:
            continue

        title = (entry.findtext(_q("title")) or "").strip()
        summary_html = (entry.findtext(_q("summary")) or "").strip()
        updated = entry.findtext(_q("updated"))
        filed_at = _parse_iso(updated) or datetime.now(UTC)

        items = _ITEM_RE.findall(items_desc) if items_desc else []

        out.append(
            Filing(
                accession=accession,
                cik=cik,
                form=form,
                title=title,
                url=filing_href,
                filed_at=filed_at,
                summary_html=summary_html,
                items=items,
            )
        )
    return out


def _text(parent: ET.Element, tag: str) -> str:
    el = parent.find(_q(tag))
    return (el.text or "").strip() if el is not None and el.text else ""


def _parse_iso(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        # SEC uses ISO 8601 with timezone, e.g. "2026-04-30T16:30:41-04:00"
        dt = datetime.fromisoformat(raw)
        return dt.astimezone(UTC)
    except ValueError:
        return None


# ─── Summary cleanup helper ──────────────────────────────────────────


_TAG_RE = re.compile(r"<[^>]+>")


def clean_summary(html: str) -> str:
    """Strip HTML tags from a SEC summary block while keeping line breaks.

    EDGAR puts ``<br>`` between bullet points and ``<b>`` around labels;
    we want a plain-text summary suitable for the news card.
    """
    if not html:
        return ""
    # Normalize line breaks first, then strip.
    text = re.sub(r"<br\s*/?>", "\n", html, flags=re.IGNORECASE)
    text = _TAG_RE.sub("", text)
    # Collapse whitespace per line.
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return "\n".join(lines)
