"""Role and permission helpers for access control.

Roles answer "who is this user administratively?". Permissions answer "what
can this request do right now?". Keeping those separate lets local dev grant
all permissions without rewriting a user's role, and leaves room for a future
subscriber tier that expands read scope without becoming admin.
"""

from __future__ import annotations

from uteki_api.core.config import settings

PERM_VIEW_RESULTS = "results:view"
PERM_VIEW_TRACE = "trace:view"
PERM_OPERATE_AGENT = "agent:operate"
PERM_OPERATE_COMPANY_RESEARCH = "agent:company_research"
PERM_ADMIN_TOOLS = "admin:*"
# 013 — gates the human-feedback / annotation surface on runs.
# Phase 1: granted to ``admin`` role only (so the single product owner
# can label production runs to seed the calibration set). Phase 2: a
# parallel ``User.extra_permissions`` field will let admins single out
# trusted readers as annotators without elevating them to admin.
PERM_ANNOTATE_RUNS = "runs:annotate"

AGENT_PERMISSION_MAP = {
    "company_research_pipeline": PERM_OPERATE_COMPANY_RESEARCH,
}


def _csv_set(raw: str) -> set[str]:
    return {item.strip().lower() for item in raw.split(",") if item.strip()}


def _admin_emails_set() -> set[str]:
    """Union of admin_emails and owner_emails (010). Both env vars feed the
    same allowlist — owner_emails is the preferred name going forward, but
    legacy admin_emails configs keep working."""
    return _csv_set(settings.admin_emails) | _csv_set(settings.owner_emails)


def _admin_github_logins_set() -> set[str]:
    return _csv_set(settings.admin_github_logins) | _csv_set(settings.owner_github_logins)


def role_for_email(email: str | None) -> str:
    if email and email.lower().strip() in _admin_emails_set():
        return "admin"
    return "reader"


def role_for_identity(
    *,
    provider: str,
    email: str | None = None,
    username: str | None = None,
    provider_user_id: str | None = None,
) -> str:
    if role_for_email(email) == "admin":
        return "admin"
    if provider == "github":
        if username and username.lower().strip() in _admin_github_logins_set():
            return "admin"
        if provider_user_id and provider_user_id.lower().strip() in _csv_set(settings.admin_github_ids):
            return "admin"
    return "reader"


def elevate_role(current: str, candidate: str) -> str:
    if current == "admin" or candidate == "admin":
        return "admin"
    return "reader"


def permissions_for_role(role: str) -> list[str]:
    if settings.local_all_permissions or role == "admin":
        return [
            PERM_VIEW_RESULTS,
            PERM_VIEW_TRACE,
            PERM_OPERATE_AGENT,
            PERM_OPERATE_COMPANY_RESEARCH,
            PERM_ADMIN_TOOLS,
            PERM_ANNOTATE_RUNS,
        ]
    return [PERM_VIEW_RESULTS, PERM_VIEW_TRACE]


def can_annotate_runs(user: object) -> bool:
    return PERM_ANNOTATE_RUNS in permissions_for_user(user)


def permissions_for_user(user: object) -> list[str]:
    return permissions_for_role(str(getattr(user, "role", "reader") or "reader"))


def can_operate(user: object) -> bool:
    return PERM_OPERATE_AGENT in permissions_for_user(user)


def can_admin(user: object) -> bool:
    return PERM_ADMIN_TOOLS in permissions_for_user(user)


def is_owner(user: object) -> bool:
    """010 — single-owner deployment: owner == the one admin account.

    Aliased to can_admin so route signatures can read with product
    vocabulary (``if not is_owner(...)``) without introducing a parallel
    permission system. If the product later supports multiple admins
    distinct from the sole owner, this is where they diverge.
    """
    return can_admin(user)


def required_permission_for_agent(agent_name: str | None) -> str:
    return AGENT_PERMISSION_MAP.get(agent_name or "", PERM_OPERATE_AGENT)


def can_run_agent(user: object, agent_name: str | None) -> bool:
    permissions = set(permissions_for_user(user))
    return PERM_OPERATE_AGENT in permissions or required_permission_for_agent(agent_name) in permissions
