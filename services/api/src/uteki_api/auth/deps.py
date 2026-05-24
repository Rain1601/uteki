"""FastAPI dependencies for authentication.

``current_user`` is the canonical guard — drop into any route as
``user: User = Depends(current_user)`` and it'll either return the authed
user or raise 401.

When ``settings.auth_required is False`` (dev), missing/invalid tokens
fall back to the ``demo@local`` user that ``init_db`` ensures exists.
Production must keep ``auth_required=True``.

``optional_user`` exists for endpoints that *can* be authenticated but
don't require it (none today, but pragmatically useful for telemetry).
"""

from __future__ import annotations

import jwt
from fastapi import Depends, HTTPException, Request, status
from sqlmodel import Session

from uteki_api.auth.jwt import decode_access
from uteki_api.core.config import settings
from uteki_api.core.db import get_db
from uteki_api.users import default_user_store, ensure_demo_user
from uteki_api.users.models import User


def _extract_bearer(request: Request) -> str | None:
    header = request.headers.get("Authorization") or ""
    if not header.lower().startswith("bearer "):
        return None
    token = header[7:].strip()
    return token or None


async def current_user(
    request: Request,
    db: Session = Depends(get_db),
) -> User:
    token = _extract_bearer(request)

    if not token:
        if not settings.auth_required:
            return ensure_demo_user(db)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        claims = decode_access(token)
    except jwt.InvalidTokenError as e:
        # Generic message — the underlying jwt library exception text can
        # leak library internals (codec errors, header structure) that
        # don't help legitimate callers and give attackers free signal.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from e

    user_id = claims.get("sub")
    if not user_id:
        raise HTTPException(401, detail="token missing sub")

    user = default_user_store.get(db, user_id)
    if user is None:
        raise HTTPException(401, detail="user not found")
    if user.status != "active":
        raise HTTPException(403, detail=f"account status: {user.status}")
    return user


async def optional_user(
    request: Request,
    db: Session = Depends(get_db),
) -> User | None:
    """Like current_user, but returns None on missing/invalid token instead of 401."""
    token = _extract_bearer(request)
    if not token:
        if not settings.auth_required:
            return ensure_demo_user(db)
        return None
    try:
        claims = decode_access(token)
    except jwt.InvalidTokenError:
        return None
    user_id = claims.get("sub")
    if not user_id:
        return None
    user = default_user_store.get(db, user_id)
    if user and user.status == "active":
        return user
    return None
