"""UserStore — thin DB-backed facade over the ``user`` table.

Keeps the call sites (api/auth.py, auth/deps.py, OAuth upsert) from sprinkling
SQLModel sessions / SQL everywhere. Identity rows live in their own model
file and are persisted via the same session.
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from datetime import UTC, datetime

from sqlalchemy import func
from sqlmodel import Session, select

from uteki_api.users.models import AuthIdentity, User

DEMO_USER_EMAIL = "demo@local"


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


def _utcnow() -> datetime:
    return datetime.now(UTC)


class UserStore(ABC):
    @abstractmethod
    def create(
        self,
        db: Session,
        *,
        email: str,
        display_name: str = "",
        avatar_url: str | None = None,
        role: str = "reader",
    ) -> User: ...

    @abstractmethod
    def get(self, db: Session, user_id: str) -> User | None: ...

    @abstractmethod
    def get_by_email(self, db: Session, email: str) -> User | None: ...

    @abstractmethod
    def list(
        self,
        db: Session,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[User], int]: ...

    @abstractmethod
    def update_role(self, db: Session, user_id: str, role: str) -> User | None: ...

    @abstractmethod
    def count_admins(self, db: Session) -> int: ...

    @abstractmethod
    def providers_for(self, db: Session, user_id: str) -> list[str]: ...


class SqlUserStore(UserStore):
    def create(
        self,
        db: Session,
        *,
        email: str,
        display_name: str = "",
        avatar_url: str | None = None,
        role: str = "reader",
    ) -> User:
        user = User(
            id=_new_id(),
            email=email.lower().strip(),
            display_name=display_name or email.split("@")[0],
            avatar_url=avatar_url,
            created_at=_utcnow(),
            status="active",
            role=role,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user

    def get(self, db: Session, user_id: str) -> User | None:
        return db.get(User, user_id)

    def get_by_email(self, db: Session, email: str) -> User | None:
        statement = select(User).where(User.email == email.lower().strip())
        return db.exec(statement).first()

    def list(
        self,
        db: Session,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[User], int]:
        # Demo user is hidden from the admin console — it's an internal
        # fallback identity, not a real account.
        base = select(User).where(User.email != DEMO_USER_EMAIL)
        total = db.exec(
            select(func.count()).select_from(base.subquery())  # type: ignore[arg-type]
        ).one()
        rows = db.exec(
            base.order_by(User.created_at.desc()).offset(offset).limit(limit)
        ).all()
        return list(rows), int(total)

    def update_role(self, db: Session, user_id: str, role: str) -> User | None:
        user = db.get(User, user_id)
        if user is None:
            return None
        user.role = role
        db.add(user)
        db.commit()
        db.refresh(user)
        return user

    def count_admins(self, db: Session) -> int:
        return int(
            db.exec(
                select(func.count()).select_from(  # type: ignore[arg-type]
                    select(User).where(User.role == "admin").subquery()
                )
            ).one()
        )

    def providers_for(self, db: Session, user_id: str) -> list[str]:
        rows = db.exec(
            select(AuthIdentity.provider).where(AuthIdentity.user_id == user_id)
        ).all()
        # Stable order for the UI: password first, then OAuth providers alpha.
        unique = sorted(set(rows), key=lambda p: (p != "password", p))
        return list(unique)


default_user_store: UserStore = SqlUserStore()


def ensure_demo_user(db: Session) -> User:
    """Idempotently materialize the dev/anonymous fallback user.

    Called at startup and by ``current_user`` when AUTH_REQUIRED is false.
    Cheap (single index lookup); guaranteed to return a persisted ``User``.

    Role selection follows the auth mode:
    - ``auth_required=False`` (dev/anonymous): the demo user is effectively
      "the local developer" — promoted to ``admin`` so role-based gates
      match production gates. This replaces the previous
      ``local_all_permissions`` magic that returned a ``reader`` with
      ``admin:*`` perms (truthful but confusing).
    - ``auth_required=True``: ``reader`` — never relied upon directly in
      tests/prod, but kept consistent in case a code path exercises it.

    Existing demo users are upgraded in place when the mode demands a
    higher role, never downgraded — toggling AUTH_REQUIRED back and forth
    must not lock the developer out of work they did under admin.
    """
    from uteki_api.core.config import settings

    desired_role = "admin" if not settings.auth_required else "reader"
    existing = default_user_store.get_by_email(db, DEMO_USER_EMAIL)
    if existing is not None:
        if desired_role == "admin" and existing.role != "admin":
            existing.role = "admin"
            db.add(existing)
            db.commit()
            db.refresh(existing)
        return existing
    return default_user_store.create(
        db,
        email=DEMO_USER_EMAIL,
        display_name="Demo (dev)",
        role=desired_role,
    )


def ensure_owner_user(db: Session) -> User | None:
    """010 — idempotently materialize the product owner user at startup.

    The owner record needs to exist before any data is partitioned under
    them. Pulls the email from ``settings.owner_emails`` ONLY — does NOT
    fall back to ``admin_emails``. Reason: ``admin_emails`` is a *role
    allowlist* (anyone matching gets admin permissions on OAuth), not a
    *singleton owner* identity. Conflating them silently auto-creates a
    user account for every admin allowlist entry, which collides with
    OAuth-flow registrations and pollutes test fixtures (the e2e suite
    puts ``alice@uteki-e2e.dev`` in ``UTEKI_ADMIN_EMAILS`` for role-
    elevation tests; that must not also create an "owner" user).

    Picks the first comma-separated owner email — multiple emails can
    still appear in the OAuth allowlist via the role check, but only the
    first becomes the canonical owner record at boot.

    Returns the owner User, or None if ``owner_emails`` is unset
    (acceptable in dev / tests; production must set ``UTEKI_OWNER_EMAILS``).

    Role is set to ``admin`` directly so the owner has full permissions
    even before they OAuth in for the first time.
    """
    from uteki_api.core.config import settings

    raw = settings.owner_emails
    first = next((e.strip().lower() for e in raw.split(",") if e.strip()), None)
    if first is None:
        return None
    existing = default_user_store.get_by_email(db, first)
    if existing is not None:
        # Make sure the role reflects current config — if the email was
        # added to owner_emails after the user was created (e.g. via OAuth),
        # promote them now.
        if existing.role != "admin":
            existing.role = "admin"
            db.add(existing)
            db.commit()
            db.refresh(existing)
        return existing
    return default_user_store.create(
        db,
        email=first,
        display_name="Owner",
        role="admin",
    )
