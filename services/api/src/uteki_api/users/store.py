"""UserStore — thin DB-backed facade over the ``user`` table.

Keeps the call sites (api/auth.py, auth/deps.py, OAuth upsert) from sprinkling
SQLModel sessions / SQL everywhere. Identity rows live in their own model
file and are persisted via the same session.
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from datetime import UTC, datetime

from sqlmodel import Session, select

from uteki_api.users.models import User

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
    ) -> User: ...

    @abstractmethod
    def get(self, db: Session, user_id: str) -> User | None: ...

    @abstractmethod
    def get_by_email(self, db: Session, email: str) -> User | None: ...


class SqlUserStore(UserStore):
    def create(
        self,
        db: Session,
        *,
        email: str,
        display_name: str = "",
        avatar_url: str | None = None,
    ) -> User:
        user = User(
            id=_new_id(),
            email=email.lower().strip(),
            display_name=display_name or email.split("@")[0],
            avatar_url=avatar_url,
            created_at=_utcnow(),
            status="active",
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


default_user_store: UserStore = SqlUserStore()


def ensure_demo_user(db: Session) -> User:
    """Idempotently materialize the dev/anonymous fallback user.

    Called at startup and by ``current_user`` when AUTH_REQUIRED is false.
    Cheap (single index lookup); guaranteed to return a persisted ``User``.
    """
    existing = default_user_store.get_by_email(db, DEMO_USER_EMAIL)
    if existing is not None:
        return existing
    return default_user_store.create(
        db,
        email=DEMO_USER_EMAIL,
        display_name="Demo (dev)",
    )
