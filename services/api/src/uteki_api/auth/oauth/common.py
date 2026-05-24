"""OAuth common utilities — state CSRF + identity upsert.

State token: HMAC-signed string ``<urlsafe(payload)>.<urlsafe(sig)>``.
Payload is ``{"n": next_url, "t": issued_at}``. Verify rejects on bad sig
or age > 10 min. Stateless; no DB roundtrip; survives backend restart.

Identity upsert: same email coming in from any provider → same User row.
This means a user who first signed up with password can later "Continue
with GitHub" using the same email and we attach the new identity to the
existing account.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlmodel import Session, select

from uteki_api.core.config import settings
from uteki_api.users import default_user_store
from uteki_api.users.models import AuthIdentity, User

STATE_MAX_AGE_SECONDS = 10 * 60


@dataclass(frozen=True)
class ProviderUser:
    """Normalized shape returned by each provider's `fetch_user`."""

    provider: str
    provider_user_id: str
    email: str | None
    name: str
    avatar_url: str | None


# ─── state token (CSRF + next-url roundtrip) ────────────────────────────


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")


def _b64d(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def _sign(payload: bytes) -> bytes:
    return hmac.new(
        settings.jwt_secret.encode("utf-8"),
        payload,
        hashlib.sha256,
    ).digest()


def make_state(next_url: str) -> str:
    body = {"n": next_url or "/", "t": int(datetime.now(UTC).timestamp())}
    raw = json.dumps(body, separators=(",", ":")).encode("utf-8")
    sig = _sign(raw)
    return f"{_b64(raw)}.{_b64(sig)}"


def verify_state(state: str) -> str:
    """Return the original ``next_url`` or raise ``ValueError``."""
    if not state or "." not in state:
        raise ValueError("malformed state")
    raw_b64, sig_b64 = state.rsplit(".", 1)
    try:
        raw = _b64d(raw_b64)
        sig = _b64d(sig_b64)
    except Exception as e:
        raise ValueError("state decode failed") from e
    expected = _sign(raw)
    if not hmac.compare_digest(sig, expected):
        raise ValueError("state signature mismatch")
    try:
        body = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"state payload not json: {e}") from e
    issued = int(body.get("t") or 0)
    if datetime.now(UTC).timestamp() - issued > STATE_MAX_AGE_SECONDS:
        raise ValueError("state expired")
    nxt = body.get("n") or "/"
    if not isinstance(nxt, str) or not nxt.startswith("/"):
        return "/"
    return nxt


# ─── upsert ─────────────────────────────────────────────────────────────


def _new_identity_id() -> str:
    return uuid.uuid4().hex[:16]


def upsert_user_from_identity(db: Session, pu: ProviderUser) -> User:
    """Find-or-create the User backing this provider identity.

    Resolution order:
    1. Match by (provider, provider_user_id) → return its User.
    2. Else if ``pu.email`` is set and matches an existing User → attach new
       identity to that User.
    3. Else create a brand new User + identity.

    On match (1), also refresh display_name / avatar from the provider's
    latest values — cheap and keeps profile pics fresh.
    """
    statement = select(AuthIdentity).where(
        AuthIdentity.provider == pu.provider,
        AuthIdentity.provider_user_id == pu.provider_user_id,
    )
    existing_identity = db.exec(statement).first()
    if existing_identity is not None:
        user = db.get(User, existing_identity.user_id)
        if user is None:
            # orphan identity; recover by treating as new
            db.delete(existing_identity)
            db.commit()
        else:
            # Refresh cosmetic fields
            changed = False
            if pu.name and user.display_name != pu.name:
                user.display_name = pu.name
                changed = True
            if pu.avatar_url and user.avatar_url != pu.avatar_url:
                user.avatar_url = pu.avatar_url
                changed = True
            if changed:
                db.add(user)
                db.commit()
                db.refresh(user)
            return user

    # Try email-merge
    user = None
    if pu.email:
        user = default_user_store.get_by_email(db, pu.email)

    if user is None:
        # Create new user. Fallback email to "<provider>:<id>@oauth.local"
        # when the provider didn't give one (GitHub users can hide email).
        email = pu.email or f"{pu.provider}_{pu.provider_user_id}@oauth.local"
        user = default_user_store.create(
            db,
            email=email,
            display_name=pu.name or email.split("@")[0],
            avatar_url=pu.avatar_url,
        )

    identity = AuthIdentity(
        id=_new_identity_id(),
        user_id=user.id,
        provider=pu.provider,
        provider_user_id=pu.provider_user_id,
        password_hash=None,
        created_at=datetime.now(UTC),
    )
    db.add(identity)
    db.commit()
    return user
