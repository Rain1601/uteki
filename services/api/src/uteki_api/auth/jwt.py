"""JWT issuance + rotation with replay detection.

Tokens
------
- **access** — HS256, ~15 min, payload ``{sub, exp, jti, iat, kind="access"}``.
  Carried by the frontend in the ``Authorization: Bearer`` header.
- **refresh** — HS256, ~30 day, payload ``{sub, exp, jti, family, kind="refresh"}``.
  Carried as an httpOnly cookie. Each call to ``rotate_refresh`` mints a new
  refresh in the *same family* and revokes the old one. If a *revoked*
  token from a known family is presented again (replay), the **entire family
  is revoked** so a stolen-then-rotated token can't be reused indefinitely.

Why a family at all? Without it, rotation is just renaming; we can't tell a
legitimate "I lost track of my new token, here's the old one" from a real
attack. With a family + revocation, the attacker's window collapses to "one
use after theft, then the legit user is forced to re-login".
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import jwt
from sqlmodel import Session

from uteki_api.core.config import settings
from uteki_api.users.models import RefreshToken

_ALGO = "HS256"


class InvalidRefresh(Exception):
    """Raised when a refresh token is invalid, expired, revoked, or replayed."""


def _now() -> datetime:
    return datetime.now(UTC)


def _new_jti() -> str:
    return uuid.uuid4().hex[:24]


# ── access token ────────────────────────────────────────────────────────


def issue_access(user_id: str) -> str:
    now = _now()
    payload = {
        "sub": user_id,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=settings.access_token_ttl_seconds)).timestamp()),
        "jti": _new_jti(),
        "kind": "access",
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=_ALGO)


def decode_access(token: str) -> dict:
    """Decode + validate an access token. Raises jwt.InvalidTokenError on any issue."""
    claims = jwt.decode(token, settings.jwt_secret, algorithms=[_ALGO])
    if claims.get("kind") != "access":
        raise jwt.InvalidTokenError("not an access token")
    return claims


# ── refresh token ───────────────────────────────────────────────────────


def issue_refresh(db: Session, user_id: str, family_id: str | None = None) -> str:
    """Persist a new RefreshToken row + return the signed JWT.

    ``family_id`` defaults to a new family (first login / OAuth callback).
    Reuses the family during rotation.
    """
    now = _now()
    expires = now + timedelta(seconds=settings.refresh_token_ttl_seconds)
    jti = _new_jti()
    fam = family_id or _new_jti()

    db.add(
        RefreshToken(
            jti=jti,
            user_id=user_id,
            family_id=fam,
            issued_at=now,
            expires_at=expires,
            revoked=False,
        )
    )
    db.commit()

    payload = {
        "sub": user_id,
        "iat": int(now.timestamp()),
        "exp": int(expires.timestamp()),
        "jti": jti,
        "family": fam,
        "kind": "refresh",
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=_ALGO)


def rotate_refresh(db: Session, refresh_token: str) -> tuple[str, str]:
    """Validate the given refresh; revoke it; mint a new one in the same family.

    Returns ``(new_access, new_refresh)``. Raises ``InvalidRefresh`` on:
    - bad signature / expired
    - kind != refresh
    - jti not found in DB (token never issued by us)
    - jti already revoked → **replay**: revoke the entire family
    """
    try:
        claims = jwt.decode(refresh_token, settings.jwt_secret, algorithms=[_ALGO])
    except jwt.InvalidTokenError as e:
        raise InvalidRefresh(f"decode failed: {e}") from e

    if claims.get("kind") != "refresh":
        raise InvalidRefresh("not a refresh token")

    jti = claims.get("jti")
    family_id = claims.get("family")
    user_id = claims.get("sub")
    if not jti or not family_id or not user_id:
        raise InvalidRefresh("missing claims")

    row = db.get(RefreshToken, jti)
    if row is None:
        raise InvalidRefresh("token not on file")

    if row.revoked:
        # Replay attack: someone is presenting a token we've already rotated.
        # Burn the whole family so neither the attacker nor the legit user
        # can use any token in this chain.
        _revoke_family(db, family_id)
        raise InvalidRefresh("token replay detected; family revoked")

    # Happy path: revoke old, mint new in same family.
    row.revoked = True
    db.add(row)
    db.commit()

    new_refresh = issue_refresh(db, user_id, family_id=family_id)
    new_access = issue_access(user_id)
    return new_access, new_refresh


def revoke_refresh(db: Session, refresh_token: str) -> None:
    """Logout: mark the presented refresh as revoked. Silent on already-invalid."""
    try:
        claims = jwt.decode(
            refresh_token,
            settings.jwt_secret,
            algorithms=[_ALGO],
            options={"verify_exp": False},
        )
    except jwt.InvalidTokenError:
        return
    jti = claims.get("jti")
    if not jti:
        return
    row = db.get(RefreshToken, jti)
    if row and not row.revoked:
        row.revoked = True
        db.add(row)
        db.commit()


def _revoke_family(db: Session, family_id: str) -> None:
    from sqlmodel import select

    statement = select(RefreshToken).where(RefreshToken.family_id == family_id)
    for row in db.exec(statement).all():
        if not row.revoked:
            row.revoked = True
            db.add(row)
    db.commit()
