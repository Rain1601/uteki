"""User / AuthIdentity / RefreshToken — SQLModel table models.

Design notes (M4):

- **User** is the canonical identity. Email is unique; display_name and
  avatar are best-effort cosmetic fields populated by OAuth providers.
- **AuthIdentity** lets one User log in via multiple providers (password +
  github + google). The (provider, provider_user_id) pair is unique.
- **RefreshToken** is what we issue to the browser. Each token has a
  ``family_id``; rotating mints a new token in the same family and revokes
  the old. If a *revoked* token from the same family is presented again
  (replay attack), the whole family is revoked — see ``auth/jwt.rotate``.
"""

from __future__ import annotations

from datetime import datetime

from sqlmodel import Field, SQLModel, UniqueConstraint


class User(SQLModel, table=True):
    __tablename__ = "user"

    id: str = Field(primary_key=True, max_length=64)
    email: str = Field(unique=True, index=True, max_length=320)
    display_name: str = Field(default="", max_length=120)
    avatar_url: str | None = Field(default=None, max_length=1024)
    created_at: datetime
    status: str = Field(default="active", max_length=16)  # active | suspended | deleted
    role: str = Field(default="reader", max_length=16)  # reader | admin


class AuthIdentity(SQLModel, table=True):
    __tablename__ = "auth_identity"
    __table_args__ = (UniqueConstraint("provider", "provider_user_id"),)

    id: str = Field(primary_key=True, max_length=64)
    user_id: str = Field(foreign_key="user.id", index=True, max_length=64)
    provider: str = Field(max_length=24)  # password | github | google
    provider_user_id: str = Field(index=True, max_length=320)
    password_hash: str | None = Field(default=None, max_length=255)
    created_at: datetime


class RefreshToken(SQLModel, table=True):
    __tablename__ = "refresh_token"

    jti: str = Field(primary_key=True, max_length=64)
    user_id: str = Field(foreign_key="user.id", index=True, max_length=64)
    family_id: str = Field(index=True, max_length=64)
    issued_at: datetime
    expires_at: datetime
    revoked: bool = False
