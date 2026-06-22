#!/usr/bin/env -S uv run --project services/api python
"""Fetch SEC EDGAR filings into a 016-retrieval-benchmark corpus snapshot.

Usage:
    ./scripts/fetch-sec-into-corpus.py GOOGL \\
        --snapshot 2024q4-googl-capex \\
        --since 2024-07-01 --until 2024-12-31 \\
        --forms 10-Q,10-K,8-K

Why this exists: 016 benchmark cases need real public filings as fixture
material. SEC EDGAR is the cleanest immutable source — filings cannot be
backdated or republished, so the (ticker, accession_number) tuple uniquely
identifies a piece of content that will never change.

This script fetches once, into a sealed local corpus. The corpus is then
hash-locked. The benchmark NEVER re-fetches at runtime; it only reads
the frozen local copies.

Output layout:
    data/eval-benchmark/snapshots/<snapshot_id>/
        manifest.json
        docs/
            googl-2024-q3-10q.md
            googl-2024-q4-8k-001.md
            ...

Each doc gets frontmatter:
    ---
    id: <stable_id>
    observed_at: <filing_date>      ← legally immutable
    published_at: <filing_date>
    source: sec_edgar
    source_url: https://www.sec.gov/Archives/...
    ticker: GOOGL
    stance: NA
    filing_type: 10-Q
    accession_number: 0001652044-24-000118
    fetched_at: <iso>
    fetched_by: scripts/fetch-sec-into-corpus.py
    ---
    [extracted plain text body]

Body extraction strategy: SEC HTML filings are JS-free static HTML. We
use BeautifulSoup (already a uteki-api dep via web_extract) to strip
HTML to readable text. Filings can be 100KB+; we keep them full-text
for the benchmark — the agent will retrieve sections.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

# Default User-Agent — SEC Fair Access policy requires identifying contact.
# Reads from env first; falls back to a placeholder that SEC will accept
# but rate-limit harder.
DEFAULT_UA = os.environ.get(
    "UTEKI_SEC_USER_AGENT",
    "uteki-benchmark fetch script wyq5ycdkrqh1d@yahoo.com",
)
SEC_RATE_DELAY = 0.15  # seconds between requests; SEC asks ≤10 req/sec

REPO_ROOT = Path(__file__).resolve().parents[1]
CORPUS_ROOT = REPO_ROOT / "data" / "eval-benchmark" / "snapshots"


def _lookup_cik(ticker: str, client: httpx.Client) -> tuple[str, str]:
    """Resolve a ticker to (cik_padded_10, company_title) via SEC's master list."""
    url = "https://www.sec.gov/files/company_tickers.json"
    resp = client.get(url, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    target = ticker.upper().strip()
    for entry in data.values():
        if entry.get("ticker") == target:
            cik = str(entry["cik_str"]).zfill(10)
            return cik, entry.get("title", target)
    raise ValueError(
        f"ticker {ticker!r} not found in SEC master list "
        "(check spelling; mega-cap US equities should be present)"
    )


def _list_filings(
    cik: str,
    *,
    forms: set[str],
    since: str | None,
    until: str | None,
    client: httpx.Client,
) -> list[dict[str, Any]]:
    """Return filtered filings list for a CIK.

    SEC submissions API returns ``recent`` (last ~1000 filings) inline plus
    older shards via separate URLs. For our use case (last 12-24 months) the
    ``recent`` block is sufficient.
    """
    url = f"https://data.sec.gov/submissions/CIK{cik}.json"
    resp = client.get(url, timeout=30)
    resp.raise_for_status()
    payload = resp.json()
    recent = payload.get("filings", {}).get("recent", {})

    out: list[dict[str, Any]] = []
    for form, date, acc, doc, primary_doc_desc in zip(
        recent.get("form", []),
        recent.get("filingDate", []),
        recent.get("accessionNumber", []),
        recent.get("primaryDocument", []),
        recent.get("primaryDocDescription", []),
        strict=False,
    ):
        if form not in forms:
            continue
        if since and date < since:
            continue
        if until and date > until:
            continue
        out.append({
            "form": form,
            "filing_date": date,
            "accession_number": acc,
            "primary_document": doc,
            "primary_doc_desc": primary_doc_desc,
        })
    return out


def _fetch_filing_body(
    cik: str, accession: str, primary_doc: str, client: httpx.Client
) -> str:
    """Download the primary document HTML and extract plain text."""
    acc_no_dashes = accession.replace("-", "")
    url = (
        f"https://www.sec.gov/Archives/edgar/data/"
        f"{int(cik)}/{acc_no_dashes}/{primary_doc}"
    )
    resp = client.get(url, timeout=60)
    resp.raise_for_status()
    return _html_to_text(resp.text)


def _html_to_text(html: str) -> str:
    """Strip HTML to readable plaintext."""
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        # Fallback: regex strip (loses some structure, but works without dep)
        text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.S | re.I)
        text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.S | re.I)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = soup.get_text(separator="\n")
    # Collapse runs of blank lines but preserve paragraph breaks
    text = re.sub(r"\n\s*\n", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def _stable_doc_id(ticker: str, form: str, filing_date: str, accession: str) -> str:
    """Generate a stable, human-readable doc id.

    Examples:
        googl-10q-2024-q3
        googl-8k-2024-10-15-001
    """
    t = ticker.lower()
    f = form.lower().replace("-", "")
    # For periodic filings (10-Q/10-K), use the fiscal-style label
    if form == "10-K":
        return f"{t}-{f}-{filing_date[:4]}"
    if form == "10-Q":
        # Map filing month to fiscal quarter roughly
        month = int(filing_date[5:7])
        # SEC filings hit ~30 days after period end; map back
        if 4 <= month <= 5:
            q = "q1"
        elif 7 <= month <= 8:
            q = "q2"
        elif 10 <= month <= 11:
            q = "q3"
        else:
            # 1-3 or 12 — assume previous year Q4 (which is usually a 10-K)
            q = "q4"
        return f"{t}-{f}-{filing_date[:4]}-{q}"
    # 8-K, DEF 14A, others — disambiguate by accession-number suffix
    acc_short = accession.split("-")[-1].lstrip("0") or "0"
    return f"{t}-{f}-{filing_date}-{acc_short.zfill(3)}"


def _frontmatter(meta: dict[str, Any]) -> str:
    lines = ["---"]
    for k, v in meta.items():
        if v is None:
            continue
        if isinstance(v, str) and ("\n" in v or '"' in v or ":" in v):
            # Quote-safe YAML scalar
            v_escaped = v.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")
            lines.append(f'{k}: "{v_escaped}"')
        else:
            lines.append(f"{k}: {v}")
    lines.append("---")
    return "\n".join(lines)


def _write_doc(
    snapshot_dir: Path,
    *,
    doc_id: str,
    ticker: str,
    form: str,
    filing_date: str,
    accession: str,
    primary_doc: str,
    body: str,
) -> tuple[Path, str, dict[str, Any]]:
    """Write a doc file and return (path, sha256, manifest_entry)."""
    docs_dir = snapshot_dir / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)

    cik_int = int(_cik_padded_from_accession(accession))
    source_url = (
        f"https://www.sec.gov/Archives/edgar/data/{cik_int}/"
        f"{accession.replace('-', '')}/{primary_doc}"
    )

    fm = {
        "id": doc_id,
        "observed_at": filing_date,
        "published_at": filing_date,
        "source": "sec_edgar",
        "source_url": source_url,
        "ticker": ticker.upper(),
        "stance": "NA",
        "filing_type": form,
        "accession_number": accession,
        "fetched_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "fetched_by": "scripts/fetch-sec-into-corpus.py",
    }
    text = _frontmatter(fm) + "\n\n" + body + "\n"
    path = docs_dir / f"{doc_id}.md"
    path.write_text(text, encoding="utf-8")

    sha256 = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return path, sha256, {
        "path": str(path.relative_to(snapshot_dir)),
        "sha256": sha256,
        "observed_at": filing_date,
        "source": "sec_edgar",
        "ticker": ticker.upper(),
        "filing_type": form,
        "accession_number": accession,
    }


def _cik_padded_from_accession(accession: str) -> str:
    """Accession numbers are CIK-YR-NNNNNN; the CIK chunk is variable width.

    Pad to 10 zeros so it matches the EDGAR URL format.
    """
    cik_chunk = accession.split("-")[0]
    return cik_chunk.zfill(10)


def _update_manifest(
    snapshot_dir: Path, new_entries: dict[str, dict[str, Any]], snapshot_id: str
) -> Path:
    """Idempotent manifest update — preserves existing entries, upserts new ones."""
    manifest_path = snapshot_dir / "manifest.json"
    existing: dict[str, Any]
    if manifest_path.exists():
        existing = json.loads(manifest_path.read_text(encoding="utf-8"))
    else:
        existing = {
            "snapshot_id": snapshot_id,
            "created_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
            "documents": {},
        }
    existing["documents"].update(new_entries)
    existing["updated_at"] = datetime.now(UTC).replace(microsecond=0).isoformat()
    # Compute a snapshot-level hash for cheap "did anything change" checks
    doc_hash_concat = "|".join(
        f"{k}:{v['sha256']}" for k, v in sorted(existing["documents"].items())
    )
    existing["snapshot_hash"] = hashlib.sha256(
        doc_hash_concat.encode("utf-8")
    ).hexdigest()
    manifest_path.write_text(
        json.dumps(existing, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return manifest_path


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Fetch SEC EDGAR filings into a 016 corpus snapshot."
    )
    parser.add_argument("ticker", help="e.g. GOOGL")
    parser.add_argument(
        "--snapshot", required=True, help="snapshot id, e.g. 2024q4-googl-capex"
    )
    parser.add_argument("--since", help="YYYY-MM-DD lower bound on filing_date")
    parser.add_argument("--until", help="YYYY-MM-DD upper bound on filing_date")
    parser.add_argument(
        "--forms",
        default="10-K,10-Q,8-K",
        help="comma-separated SEC form types (default: 10-K,10-Q,8-K)",
    )
    parser.add_argument(
        "--user-agent",
        default=DEFAULT_UA,
        help="SEC User-Agent (must include contact email)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="list filings that would be fetched, but don't download",
    )
    args = parser.parse_args(argv)

    forms = {f.strip() for f in args.forms.split(",") if f.strip()}

    snapshot_dir = CORPUS_ROOT / args.snapshot
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    headers = {"User-Agent": args.user_agent, "Accept-Encoding": "gzip, deflate"}
    print(f"→ ticker={args.ticker}  snapshot={args.snapshot}  forms={sorted(forms)}")
    print(f"  range: {args.since or '<begin>'} .. {args.until or '<end>'}")
    print(f"  output: {snapshot_dir.relative_to(REPO_ROOT)}")
    print()

    with httpx.Client(headers=headers, follow_redirects=True) as client:
        # Step 1 — CIK lookup
        cik, title = _lookup_cik(args.ticker, client)
        print(f"  CIK {cik}  ({title})")
        time.sleep(SEC_RATE_DELAY)

        # Step 2 — list filings
        filings = _list_filings(
            cik, forms=forms, since=args.since, until=args.until, client=client
        )
        print(f"  matched filings: {len(filings)}")
        for f in filings:
            print(
                f"    {f['form']:6s}  {f['filing_date']}  "
                f"{f['accession_number']}  ({f['primary_doc_desc']})"
            )
        if args.dry_run:
            print("\n  dry-run: nothing downloaded")
            return 0
        if not filings:
            print("  no filings to fetch — exit clean")
            return 0
        time.sleep(SEC_RATE_DELAY)

        # Step 3 — fetch + write
        new_entries: dict[str, dict[str, Any]] = {}
        for f in filings:
            doc_id = _stable_doc_id(
                args.ticker, f["form"], f["filing_date"], f["accession_number"]
            )
            existing_path = snapshot_dir / "docs" / f"{doc_id}.md"
            if existing_path.exists():
                # Idempotent: skip already-fetched docs (hash-locked already)
                print(f"  skip (already on disk): {doc_id}")
                continue
            print(f"  fetch: {doc_id} ... ", end="", flush=True)
            try:
                body = _fetch_filing_body(
                    cik, f["accession_number"], f["primary_document"], client
                )
            except Exception as e:
                print(f"ERROR  ({e})")
                continue
            _path, sha, entry = _write_doc(
                snapshot_dir,
                doc_id=doc_id,
                ticker=args.ticker,
                form=f["form"],
                filing_date=f["filing_date"],
                accession=f["accession_number"],
                primary_doc=f["primary_document"],
                body=body,
            )
            new_entries[doc_id] = entry
            print(f"OK  {len(body):>7d}B  sha256={sha[:12]}…")
            time.sleep(SEC_RATE_DELAY)

        manifest_path = _update_manifest(snapshot_dir, new_entries, args.snapshot)
        print()
        print(f"  manifest: {manifest_path.relative_to(REPO_ROOT)}")
        print(f"  new docs: {len(new_entries)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
