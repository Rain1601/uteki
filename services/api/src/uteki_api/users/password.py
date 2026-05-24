"""bcrypt password hashing helpers.

We use bcrypt (cost=12) directly — no passlib (passlib's bcrypt backend has
deprecation warnings on newer bcrypt + the wrapper offers little value here).

``hash_password`` returns the standard ``$2b$12$...`` string, safely storable
in a single column. ``verify_password`` returns False on any malformed input
rather than raising — we never want auth to crash on bad data.
"""

from __future__ import annotations

import bcrypt


def hash_password(password: str) -> str:
    if not password:
        raise ValueError("password must be non-empty")
    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def verify_password(password: str, hashed: str | None) -> bool:
    if not password or not hashed:
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False
