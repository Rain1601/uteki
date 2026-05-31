"""Derive compact run diagnosis from the event trace."""

from __future__ import annotations

from typing import Any

from uteki_api.provenance import SourceCatalog, extract_citations
from uteki_api.schemas.events import AgentEvent


def build_trace_diagnosis(
    events: list[AgentEvent],
    *,
    usage_totals: dict[str, int] | None = None,
    source_catalog: SourceCatalog | None = None,
    final_text: str = "",
) -> dict[str, Any]:
    counts: dict[str, int] = {}
    failures: list[dict[str, Any]] = []
    tool_calls: dict[str, int] = {}
    tool_failures: list[dict[str, Any]] = []
    artifacts: list[str] = []

    for event in events:
        counts[event.type] = counts.get(event.type, 0) + 1
        if event.type == "error":
            failures.append({"type": "error", "reason": event.data.get("reason")})
        if event.type == "tool_call":
            name = str(event.data.get("name") or "")
            if name:
                tool_calls[name] = tool_calls.get(name, 0) + 1
        if event.type == "tool_result" and event.data.get("ok") is False:
            item = {
                "tool": event.data.get("name"),
                "error": event.data.get("error"),
                "summary": event.data.get("summary"),
            }
            failures.append({"type": "tool_result", **item})
            tool_failures.append(item)
        if event.type == "artifact_written":
            name = event.data.get("name")
            if isinstance(name, str) and name:
                artifacts.append(name)

    valid_ids = source_catalog.valid_ids() if source_catalog is not None else set()
    citation_info = extract_citations(final_text, valid_ids=valid_ids) if final_text else None
    source_count = len(source_catalog) if source_catalog is not None else 0
    orphan_ids = citation_info.orphan_ids if citation_info is not None else []
    cited_ids = sorted(citation_info.all_cited_ids()) if citation_info is not None else []

    warnings: list[str] = []
    if source_count > 0 and citation_info is not None and not cited_ids and citation_info.no_source_count == 0:
        warnings.append("source catalog exists but final text has no citation markers")
    if orphan_ids:
        warnings.append(f"orphan citation ids: {orphan_ids}")
    if tool_failures:
        warnings.append(f"{len(tool_failures)} tool failure(s)")
    if not artifacts:
        warnings.append("no artifacts written")

    status = "ok"
    if failures:
        status = "error"
    elif warnings:
        status = "warn"

    return {
        "status": status,
        "event_counts": counts,
        "failures": failures,
        "warnings": warnings,
        "tools": {
            "calls": tool_calls,
            "failures": tool_failures,
        },
        "usage": usage_totals or {},
        "artifacts": sorted(set(artifacts)),
        "citations": {
            "source_count": source_count,
            "cited_ids": cited_ids,
            "orphan_ids": orphan_ids,
            "no_source_count": citation_info.no_source_count if citation_info is not None else 0,
        },
    }
