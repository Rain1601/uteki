"""Auth package — JWT issuance / rotation, FastAPI dependency, OAuth flows."""

from __future__ import annotations

from uteki_api.auth.deps import current_user, optional_user, require_admin
from uteki_api.auth.jwt import (
    InvalidRefresh,
    decode_access,
    issue_access,
    issue_refresh,
    rotate_refresh,
)

__all__ = [
    "InvalidRefresh",
    "current_user",
    "decode_access",
    "issue_access",
    "issue_refresh",
    "optional_user",
    "require_admin",
    "rotate_refresh",
]
