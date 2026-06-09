"""SQLite / Postgres database engine + session dependency.

Local dev defaults to SQLite (``sqlite:///data/uteki.db``). Production
points ``UTEKI_DB_URL`` at Cloud SQL Postgres (``postgresql+psycopg://…``)
— see ``services/api/MIGRATION_PG.md`` for the deployment flow.

For M4 we use SQLModel for table definitions. ``init_db`` creates tables
via ``SQLModel.metadata.create_all`` — good enough for dev / v0. The
hand-rolled ``_ensure_*_column`` helpers ALTER TABLE in place when an
older SQLite file is missing newer columns. Production should switch to
alembic for schema evolution; see MIGRATION_PG.md for the migration plan.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine

from uteki_api.core.config import settings


def _is_postgres_url(url: str) -> bool:
    """Return True for any libpq/psycopg flavoured URL.

    Accepts ``postgresql://``, ``postgresql+psycopg://``, ``postgresql+asyncpg://``
    and the legacy ``postgres://`` alias. Cloud SQL Unix-socket form
    ``postgresql+psycopg://user:pass@/db?host=/cloudsql/...`` is a valid PG
    URL — the empty host segment is intentional, libpq treats ``host`` as
    the connection's UDS path. No special handling needed here.
    """
    return url.startswith(("postgresql://", "postgresql+", "postgres://"))


def _make_engine() -> Engine:
    url = settings.db_url
    # ── SQLite (local dev / tests) ─────────────────────────────────────
    if url.startswith("sqlite:///"):
        rel = url.removeprefix("sqlite:///")
        path = Path(rel).expanduser()
        # Make non-absolute paths relative to services/api/ (CWD of api process).
        if not path.is_absolute():
            path = Path.cwd() / path
        path.parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False: FastAPI uses one connection per request via
        # the dependency, but the SqliteRunStore's in-flight cache can be
        # touched from background tasks.
        return create_engine(
            url, connect_args={"check_same_thread": False}, echo=False
        )

    # ── Postgres (Cloud SQL prod) ──────────────────────────────────────
    if _is_postgres_url(url):
        # Cloud SQL idle-disconnect timeout is 600s; recycle before that so
        # we never hand a dead socket to a request. pool_size + max_overflow
        # are sized for a single Cloud Run instance — multiply by max
        # instances to get the total connection ceiling (see MIGRATION_PG.md).
        return create_engine(
            url,
            echo=False,
            pool_size=5,
            max_overflow=10,
            pool_recycle=300,
            pool_pre_ping=True,
        )

    # ── Anything else (in-memory sqlite, custom dialects) ──────────────
    return create_engine(url, echo=False)


engine: Engine = _make_engine()


def init_db() -> None:
    """Create tables if missing. Idempotent. Imports models for side-effects."""
    # Import here so SQLModel metadata picks up every table-bearing class
    # without circular imports at module load time.
    from uteki_api.companies.models import Company  # noqa: F401
    from uteki_api.news.models import (  # noqa: F401
        ArticleTag,
        NewsArticle,
        NewsFeedback,
        Tag,
        TagGroup,
        TriggerHit,
    )
    from uteki_api.runs.sql_models import RunRow  # noqa: F401
    from uteki_api.users.models import AuthIdentity, RefreshToken, User  # noqa: F401

    SQLModel.metadata.create_all(engine)
    _ensure_user_role_column(engine)
    _ensure_run_assessment_columns(engine)
    _ensure_run_visibility_column(engine)


def _ensure_user_role_column(db_engine: Engine) -> None:
    """Lightweight schema repair until Alembic migrations are enabled."""
    inspector = inspect(db_engine)
    try:
        columns = {column["name"] for column in inspector.get_columns("user")}
    except Exception:
        return
    if "role" in columns:
        return
    with db_engine.begin() as conn:
        conn.execute(text('ALTER TABLE "user" ADD COLUMN role VARCHAR(16) DEFAULT \'reader\''))
        conn.execute(text('UPDATE "user" SET role = \'reader\' WHERE role IS NULL OR role = \'\''))


def _ensure_run_assessment_columns(db_engine: Engine) -> None:
    """M1.9: add harness_status / evaluator_decision / overall_assessment
    columns to existing ``run`` tables. SQLite supports ADD COLUMN.

    For fresh DBs ``create_all`` already includes these columns and the
    inspector finds them; for upgraded DBs the missing ones get added
    with sane defaults backfilled from the legacy ``status`` field where
    possible (status == harness_status for runs that pre-date M1.9).
    """
    inspector = inspect(db_engine)
    try:
        columns = {column["name"] for column in inspector.get_columns("run")}
    except Exception:
        return  # run table doesn't exist yet — create_all will handle it
    additions: list[str] = []
    if "harness_status" not in columns:
        additions.append(
            'ALTER TABLE run ADD COLUMN harness_status VARCHAR(16) DEFAULT \'running\''
        )
    if "evaluator_decision" not in columns:
        additions.append(
            "ALTER TABLE run ADD COLUMN evaluator_decision VARCHAR(16)"
        )
    if "overall_assessment" not in columns:
        additions.append(
            'ALTER TABLE run ADD COLUMN overall_assessment VARCHAR(32) DEFAULT \'running\''
        )
    if not additions:
        return
    with db_engine.begin() as conn:
        for stmt in additions:
            conn.execute(text(stmt))
        # Backfill harness_status from status (they're synonymous for pre-M1.9
        # runs) so historical rows have meaningful values on first read.
        if "harness_status" in (stmt for stmt in additions if "harness_status" in stmt):
            pass  # default already 'running'; legacy status preserved separately
        conn.execute(text(
            "UPDATE run SET harness_status = status WHERE harness_status = 'running' AND status != 'running'"
        ))
        conn.execute(text(
            "UPDATE run SET overall_assessment = CASE "
            "WHEN status = 'ok' THEN 'ok_no_judge' "
            "WHEN status IN ('error', 'timeout') THEN 'failed' "
            "ELSE 'running' END "
            "WHERE overall_assessment = 'running' AND status != 'running'"
        ))


def _ensure_run_visibility_column(db_engine: Engine) -> None:
    """010: add ``visibility`` column to existing ``run`` tables.

    Defaults to ``private`` for all pre-010 rows — safe choice, owner can
    promote curated runs to ``public`` post-deploy. Adds an index because
    every anon list query filters by this column.
    """
    inspector = inspect(db_engine)
    try:
        columns = {column["name"] for column in inspector.get_columns("run")}
    except Exception:
        return  # run table doesn't exist yet — create_all will handle it
    if "visibility" in columns:
        return
    with db_engine.begin() as conn:
        conn.execute(text(
            "ALTER TABLE run ADD COLUMN visibility VARCHAR(16) DEFAULT 'private'"
        ))
        conn.execute(text(
            "UPDATE run SET visibility = 'private' WHERE visibility IS NULL"
        ))
        # Index name matches SQLModel's auto-generated convention
        # (ix_<table>_<col>) so create_all on fresh DBs is consistent.
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_run_visibility ON run (visibility)"
        ))


def get_db() -> Iterator[Session]:
    """FastAPI dependency that yields a Session per request."""
    with Session(engine) as session:
        yield session
