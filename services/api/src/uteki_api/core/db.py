"""SQLite (or any SQLAlchemy URL) database engine + session dependency.

For M4 we use SQLModel + SQLite by default. ``init_db`` creates tables via
``SQLModel.metadata.create_all`` — good enough for dev / v0. Production
migrations should switch to alembic; the alembic skeleton lives at
``services/api/alembic/`` (added in M4.1 but not generating migrations yet —
SQLModel.metadata stays the source of truth until the schema stabilizes).
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine

from uteki_api.core.config import settings


def _make_engine() -> Engine:
    url = settings.db_url
    # For sqlite, ensure parent dir exists + relax thread check (FastAPI uses
    # one connection per request via dependency).
    if url.startswith("sqlite:///"):
        rel = url.removeprefix("sqlite:///")
        path = Path(rel).expanduser()
        # Make non-absolute paths relative to services/api/ (CWD of api process).
        if not path.is_absolute():
            path = Path.cwd() / path
        path.parent.mkdir(parents=True, exist_ok=True)
        return create_engine(
            url, connect_args={"check_same_thread": False}, echo=False
        )
    return create_engine(url, echo=False)


engine: Engine = _make_engine()


def init_db() -> None:
    """Create tables if missing. Idempotent. Imports models for side-effects."""
    # Import here so SQLModel metadata picks up every table-bearing class
    # without circular imports at module load time.
    from uteki_api.runs.sql_models import RunRow  # noqa: F401
    from uteki_api.users.models import AuthIdentity, RefreshToken, User  # noqa: F401

    SQLModel.metadata.create_all(engine)


def get_db() -> Iterator[Session]:
    """FastAPI dependency that yields a Session per request."""
    with Session(engine) as session:
        yield session
