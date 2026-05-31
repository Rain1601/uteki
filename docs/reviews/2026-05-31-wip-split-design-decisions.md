# WIP Split Design Decisions

Date: 2026-05-31

## await_review semantics

Choice: immediate reject, fail-closed.

`await_review` is currently a governance checkpoint event, not a real paused
state. High-risk tools emit `await_review` for audit/UI visibility and then an
immediate failed `tool_result(error="high_risk_tool_requires_review")`. Real
human review / paused compliance mode remains a future extension.

## agent:company_research permission

Choice: tier-gating foundation.

`AGENT_PERMISSION_MAP` is the backend-authoritative place for dedicated agent
permissions. Most skills should keep using `agent:operate`; split a skill only
when it has materially different cost, entitlement, compliance, or product-tier
requirements. `company_research_pipeline` is split because it generates a full
company dossier with multi-source artifacts and is a natural premium capability.

## AGENTS.md vs CLAUDE.md

Choice: single authority.

`AGENTS.md` is reduced to a pointer to `CLAUDE.md` so repository guidance does
not drift across two overlapping files.
