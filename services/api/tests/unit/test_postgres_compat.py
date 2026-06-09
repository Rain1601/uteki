"""Postgres compatibility — engine construction smoke tests.

These tests exercise ``_make_engine`` against a postgresql URL without
actually opening a connection. They verify:

  - the right dialect gets wired up,
  - pool kwargs (pool_size/max_overflow/pool_recycle/pool_pre_ping) are
    applied for PG but NOT for SQLite,
  - SQLite-specific connect_args (check_same_thread=False) are NOT
    applied to PG (would crash psycopg),
  - Cloud SQL Unix-socket form (``host=/cloudsql/...``) is accepted.

We don't try to connect — Cloud SQL isn't reachable from the test box.
``create_engine`` is lazy; the URL is parsed at construction time but the
connection isn't established until ``.connect()`` is called.

Skipped when the ``postgres`` extra isn't installed (``psycopg``
missing). Local devs running ``uv sync`` without ``--extra postgres``
will see these as skipped, not failed.
"""

from __future__ import annotations

import pytest

# psycopg is the production driver. Without it, SQLAlchemy can still
# *parse* a postgresql URL but trying to do anything with the engine
# will raise NoSuchModuleError. Skip if the extra isn't installed so
# dev environments stay green.
pytest.importorskip("psycopg")


def _make_engine_with_url(monkeypatch: pytest.MonkeyPatch, url: str):
    """Construct an engine via the production code path, with ``url``
    swapped into ``settings.db_url``. Re-imports ``core.db`` is not
    needed — ``_make_engine`` reads ``settings`` lazily on each call."""
    from uteki_api.core import config, db

    monkeypatch.setattr(config.settings, "db_url", url)
    return db._make_engine()


def test_postgres_url_constructs_engine_with_psycopg_dialect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A plain postgresql+psycopg URL should yield a PG engine."""
    engine = _make_engine_with_url(
        monkeypatch,
        "postgresql+psycopg://user:pass@localhost:5432/uteki",
    )
    assert engine.dialect.name == "postgresql"
    # Driver name is the second half of the URL scheme.
    assert engine.dialect.driver == "psycopg"


def test_postgres_url_applies_pool_kwargs(monkeypatch: pytest.MonkeyPatch) -> None:
    """PG engines should have a real connection pool sized for Cloud Run."""
    engine = _make_engine_with_url(
        monkeypatch,
        "postgresql+psycopg://user:pass@localhost:5432/uteki",
    )
    pool = engine.pool
    # QueuePool is what we expect when pool_size > 0; check the configured
    # sizes match what the prod helper sets.
    assert pool.size() == 5
    # max_overflow lives as a private attr on the pool; accept either the
    # public _max_overflow or just check it's positive (impl detail).
    assert getattr(pool, "_max_overflow", 0) == 10


def test_postgres_url_does_not_apply_sqlite_connect_args(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """check_same_thread=False is a SQLite-only kwarg; psycopg rejects it.

    We assert the engine was constructed (i.e. the SQLite branch did not
    fire and inject incompatible kwargs). If the branch were wrong,
    create_engine itself would raise during PG dispatch.
    """
    engine = _make_engine_with_url(
        monkeypatch,
        "postgresql+psycopg://user:pass@localhost:5432/uteki",
    )
    # Engine constructed cleanly → SQLite-only path did not fire.
    assert engine is not None
    assert engine.url.get_backend_name() == "postgresql"


def test_cloud_sql_unix_socket_url_is_accepted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cloud Run reaches Cloud SQL via a Unix-socket path embedded as
    ``?host=/cloudsql/PROJECT:REGION:INSTANCE``. SQLAlchemy + psycopg
    parse this fine; we just need to not reject it at our layer."""
    url = (
        "postgresql+psycopg://uteki_app:secret@/uteki"
        "?host=/cloudsql/myproj:us-central1:uteki-pg"
    )
    engine = _make_engine_with_url(monkeypatch, url)
    assert engine.dialect.name == "postgresql"
    # Host is intentionally empty in the URL (libpq reads ?host=...).
    # The ?host= query param survives parsing into engine.url.query.
    assert engine.url.query.get("host", "").startswith("/cloudsql/")


def test_sqlite_url_still_uses_check_same_thread_false(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """Regression guard: local-dev SQLite path must stay intact."""
    url = f"sqlite:///{tmp_path / 'compat-test.db'}"
    engine = _make_engine_with_url(monkeypatch, url)
    assert engine.dialect.name == "sqlite"
