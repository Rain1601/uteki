"""Role assignment helpers for reader/admin access control."""

from __future__ import annotations

from uteki_api.core.config import settings


def _csv_set(raw: str) -> set[str]:
    return {item.strip().lower() for item in raw.split(",") if item.strip()}


def role_for_email(email: str | None) -> str:
    if email and email.lower().strip() in _csv_set(settings.admin_emails):
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
        if username and username.lower().strip() in _csv_set(settings.admin_github_logins):
            return "admin"
        if provider_user_id and provider_user_id.lower().strip() in _csv_set(settings.admin_github_ids):
            return "admin"
    return "reader"


def elevate_role(current: str, candidate: str) -> str:
    if current == "admin" or candidate == "admin":
        return "admin"
    return "reader"
