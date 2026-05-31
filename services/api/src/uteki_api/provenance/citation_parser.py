"""Citation parser for source markers.

Canonical model-facing citations are `[src:N]` and `[src:none]`. Older
company reports also emitted compact ledger citations such as `[24]` or
`[24][27][31]`; parse those too so quality gates can catch orphan ids instead
of silently treating them as plain text.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

NO_SOURCE_TOKEN = "none"
_CITATION_RE = re.compile(
    r"\[src:\s*([0-9,\s]+|none)\s*\]|\[([0-9]{1,6}(?:\s*,\s*[0-9]{1,6})*)\]",
    re.IGNORECASE,
)


def _match_body(match: re.Match[str]) -> str:
    return (match.group(1) or match.group(2) or "").strip().lower()


@dataclass
class Citation:
    """One citation marker found in text."""

    span: tuple[int, int]
    raw: str
    ids: list[int] = field(default_factory=list)
    is_no_source: bool = False


@dataclass
class CitationExtraction:
    """Result of citation extraction."""

    text: str
    citations: list[Citation] = field(default_factory=list)
    orphan_ids: list[int] = field(default_factory=list)
    no_source_count: int = 0

    def all_cited_ids(self) -> set[int]:
        out: set[int] = set()
        for citation in self.citations:
            out.update(citation.ids)
        return out

    def stripped(self) -> str:
        """Return text without citation markers."""
        return _CITATION_RE.sub("", self.text).strip()

    def cleaned(self, valid_ids: set[int]) -> str:
        """Return text with invalid numeric citations neutralized."""

        def _replace(match: re.Match[str]) -> str:
            body = _match_body(match)
            if body == NO_SOURCE_TOKEN:
                return match.group(0)
            kept: list[int] = []
            for part in body.split(","):
                try:
                    n = int(part.strip())
                except ValueError:
                    continue
                if n in valid_ids and n not in kept:
                    kept.append(n)
            if not kept:
                return "[src:none]"
            return f"[src:{','.join(str(n) for n in kept)}]"

        return _CITATION_RE.sub(_replace, self.text)


def extract_citations(text: str, valid_ids: set[int] | None = None) -> CitationExtraction:
    """Extract and optionally validate source citations."""
    if not text:
        return CitationExtraction(text="")

    citations: list[Citation] = []
    orphan_ids: list[int] = []
    no_source_count = 0

    for match in _CITATION_RE.finditer(text):
        body = _match_body(match)
        if body == NO_SOURCE_TOKEN:
            citations.append(
                Citation(
                    span=(match.start(), match.end()),
                    raw=match.group(0),
                    is_no_source=True,
                )
            )
            no_source_count += 1
            continue

        ids: list[int] = []
        for part in body.split(","):
            part = part.strip()
            if not part:
                continue
            try:
                n = int(part)
            except ValueError:
                logger.debug("non-integer citation component in %r: %r", match.group(0), part)
                continue
            if n in ids:
                continue
            if valid_ids is not None and n not in valid_ids:
                orphan_ids.append(n)
                continue
            ids.append(n)

        citations.append(
            Citation(
                span=(match.start(), match.end()),
                raw=match.group(0),
                ids=ids,
            )
        )

    return CitationExtraction(
        text=text,
        citations=citations,
        orphan_ids=orphan_ids,
        no_source_count=no_source_count,
    )


class CitationParser:
    """Stateful parser bound to a source catalog."""

    def __init__(self, catalog) -> None:
        from uteki_api.provenance.catalog import SourceCatalog

        if not isinstance(catalog, SourceCatalog):
            raise TypeError(f"expected SourceCatalog, got {type(catalog).__name__}")
        self._catalog = catalog

    @property
    def valid_ids(self) -> set[int]:
        return self._catalog.valid_ids()

    def parse(self, text: str) -> CitationExtraction:
        return extract_citations(text, valid_ids=self.valid_ids)
