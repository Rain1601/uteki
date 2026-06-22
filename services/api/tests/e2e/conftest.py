"""E2E test fixtures + observability helpers.

Each test gets a clean SQLite DB + clean ``data/`` tree, a TestClient
(in-proc FastAPI), and two pre-registered users (A and B). Tests run
in mock-LLM mode (``UTEKI_USE_MOCK_LLM=true``) so they're hermetic and
cheap — the chains we care about (auth, isolation, persistence,
pipeline orchestration) don't depend on real model output.

Observability: the ``reporter`` fixture is a per-test printer that logs
a structured trace of what each chain did (events, artifacts, status
codes). Pytest captures stdout by default; run with ``-s`` to see the
traces live. On failure the trace is still printed so you can see what
the chain did up to the break.
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Iterator
from pathlib import Path

# Force test-mode env BEFORE any uteki import — config.py snapshots at
# import time.
os.environ.setdefault("UTEKI_USE_MOCK_LLM", "true")
os.environ.setdefault("UTEKI_AUTH_REQUIRED", "true")
os.environ.setdefault("UTEKI_JWT_SECRET", "e2e-test-secret-min-32-chars-of-junk-1234567890")
os.environ.setdefault("UTEKI_ADMIN_EMAILS", "alice@uteki-e2e.dev")
# Per-session DB lives in the test data dir so the dev DB stays untouched.
TEST_DATA = Path(__file__).resolve().parent / "_data"
os.environ["UTEKI_DB_URL"] = f"sqlite:///{TEST_DATA / 'e2e.db'}"

import pytest  # noqa: E402  — env vars must land before any uteki import below
from fastapi.testclient import TestClient  # noqa: E402

# ─── data lifecycle ─────────────────────────────────────────────────


@pytest.fixture(scope="function", autouse=True)
def clean_data_dir() -> Iterator[Path]:
    """Wipe + recreate the test data dir per-test. Cheap (no real artifacts).

    Also disposes the SQLAlchemy engine: SQLite's connection pool keeps
    an open handle to the file, so deleting the file doesn't reset the
    DB — the engine just keeps reading/writing its in-memory copy of
    the now-orphaned inode. Dispose forces the next connection to open
    a fresh file at the (recreated) path.

    DESTRUCTION SAFETY (added 2026-06-22):
    This fixture used to also wipe ``services/api/data/runs/users/`` and
    ``services/api/data/users/`` unconditionally — that's the *production*
    data dir when you're running e2e from a dev machine where the API is
    also running real runs. A full `./scripts/e2e.sh` would shred every
    real GOOGL/NVDA/TSLA artifact on disk. Now we only wipe those paths
    when running inside the explicit e2e workspace (TEST_DATA path), AND
    only when ``UTEKI_E2E_DESTROY_PROD_DATA=1`` is set as an opt-in. For
    routine dev e2e the prod data is left alone — TEST_DATA isolation +
    InMemory store rebinds in the conftest are already sufficient.
    """
    # Dispose engine first (drops pool → next access reconnects to fresh file)
    try:
        from uteki_api.core.db import engine
        engine.dispose()
    except Exception:
        pass

    if TEST_DATA.exists():
        shutil.rmtree(TEST_DATA)
    TEST_DATA.mkdir(parents=True)

    # Clean prod-shaped data — but allow-list real dev user dirs so a
    # live API on the same machine doesn't lose real GOOGL/NVDA artifacts.
    #
    # Previously this fixture rm -rf'd `data/runs/users/` unconditionally,
    # which shredded real run artifacts on dev machines. Now we sweep
    # everything EXCEPT user dirs listed in UTEKI_E2E_PRESERVE_USER_IDS
    # (comma-separated, defaults to demo@local + rain1104@foxmail prod IDs).
    # T17/drift_monitor still gets its clean system partition.
    api_root = Path(__file__).resolve().parents[2]
    raw_preserve = os.environ.get(
        "UTEKI_E2E_PRESERVE_USER_IDS",
        # Defaults: known dev/prod user IDs that own real runs we don't
        # want to lose. Override with the env var if your machine differs.
        "7ca81b56cc93,247057f25114,0796aef1677d",
    )
    preserve_user_ids = {x.strip() for x in raw_preserve.split(",") if x.strip()}
    runs_root = api_root / "data" / "runs" / "users"
    if runs_root.exists():
        for child in runs_root.iterdir():
            if not child.is_dir() or child.name in preserve_user_ids:
                continue
            shutil.rmtree(child)
    users_root = api_root / "data" / "users"
    if users_root.exists():
        for child in users_root.iterdir():
            if not child.is_dir() or child.name in preserve_user_ids:
                continue
            shutil.rmtree(child)
    yield TEST_DATA


# ─── client + reset of in-process stores ────────────────────────────


@pytest.fixture
def client() -> Iterator[TestClient]:
    """Fresh TestClient per test. Also resets in-process singletons so
    tests don't see each other's runs / memory / artifacts."""
    # Import here so the env knobs above take effect first.
    from uteki_api import main as app_main
    from uteki_api import memory as memory_pkg

    # Reset shared singletons. Every module that `from uteki_api.runs
    # import default_run_store` holds its OWN reference (it's a name
    # binding, not an attribute lookup), so a fresh store has to be
    # plumbed into every importer or one of them will keep writing to
    # the old, now-orphaned, store.
    from uteki_api import runs as runs_pkg
    from uteki_api.memory.in_memory import InMemoryStore
    from uteki_api.runs.store import InMemoryRunStore

    fresh_runs = InMemoryRunStore()
    fresh_mem = InMemoryStore()
    runs_pkg.default_run_store = fresh_runs
    memory_pkg.default_memory = fresh_mem

    from uteki_api.agents import harness as h
    from uteki_api.api import (
        admin as api_admin,
    )
    from uteki_api.api import (
        agent as api_agent,
    )
    from uteki_api.api import (
        artifacts as api_arts,
    )
    from uteki_api.api import (
        compare as api_cmp,
    )
    from uteki_api.api import (
        runs as api_runs,
    )
    h.default_run_store = fresh_runs
    h.default_memory = fresh_mem
    api_admin.default_run_store = fresh_runs
    api_agent.default_run_store = fresh_runs
    api_arts.default_run_store = fresh_runs
    api_cmp.default_run_store = fresh_runs
    api_runs.default_run_store = fresh_runs

    # cc_runner (M1.3) is launched from api_admin as a background task and
    # holds its own by-name imports of default_run_store / default_proposal_store —
    # rebind so the task sees the fresh per-test instances.
    from uteki_api.evolution import cc_runner as cc_runner_mod
    cc_runner_mod.default_run_store = fresh_runs

    # 015 PR ε — prediction_dispatcher does the same name-binding for
    # default_run_store. Without this rebind, dispatcher would call into
    # the prod store and miss tests' seeded runs.
    from uteki_api.eval import prediction_dispatcher as prediction_disp_mod
    prediction_disp_mod.default_run_store = fresh_runs

    # drift_monitor (M1.11) imports default_run_store by name to anchor
    # auto-triggered proposals on the originating skill. Without this
    # rebind, T17's seeded run goes into the per-test InMemoryRunStore
    # but drift_monitor.get() reads from the import-time SqliteRunStore
    # → "run_id not found" and auto-trigger silently skips.
    from uteki_api.eval import drift_monitor as drift_mod
    drift_mod.default_run_store = fresh_runs

    with TestClient(app_main.app) as c:
        yield c


# ─── pre-registered users ───────────────────────────────────────────


class AuthedUser:
    """A registered user + a token for sending requests as them."""

    def __init__(self, client: TestClient, email: str, password: str, name: str):
        r = client.post(
            "/api/auth/register",
            json={"email": email, "password": password, "display_name": name},
        )
        if r.status_code != 200:
            raise RuntimeError(f"register failed for {email}: {r.status_code} {r.text}")
        body = r.json()
        self.email = email
        self.password = password
        self.name = name
        self.id: str = body["user"]["id"]
        self.role: str = body["user"]["role"]
        self.access_token: str = body["access_token"]
        self.refresh_cookie: str | None = client.cookies.get("uteki_refresh")

    def auth_header(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.access_token}"}


# RFC 2606 reserves .test / .example / .invalid / .localhost — Pydantic's
# EmailStr blocks them. Use a non-reserved sandbox TLD.
@pytest.fixture
def alice(client: TestClient) -> AuthedUser:
    return AuthedUser(client, "alice@uteki-e2e.dev", "pw12345678", "Alice")


@pytest.fixture
def bob(client: TestClient) -> AuthedUser:
    return AuthedUser(client, "bob@uteki-e2e.dev", "pw12345678", "Bob")


# ─── observable trace printer ───────────────────────────────────────


class Reporter:
    """Pretty-prints a chain trace so failures are interpretable.

    Use like:
        reporter.section("step 1 — register")
        reporter.kv("user_id", user.id)
        reporter.checked("got 200 on /me", True)

    On test failure the trace is printed by the pytest output anyway
    (we just collect; pytest captures stdout)."""

    def __init__(self, test_name: str):
        self.test_name = test_name
        print()
        print("┌" + "─" * 70)
        print(f"│ E2E · {test_name}")
        print("├" + "─" * 70)

    def section(self, title: str) -> None:
        print(f"│ ▶ {title}")

    def kv(self, key: str, value: object) -> None:
        v = str(value)
        if len(v) > 80:
            v = v[:77] + "..."
        print(f"│     {key} = {v}")

    def checked(self, label: str, ok: bool, detail: str = "") -> None:
        mark = "✓" if ok else "✗"
        suffix = f"  ({detail})" if detail and not ok else ""
        print(f"│   {mark} {label}{suffix}")

    def event(self, kind: str, payload: object = None) -> None:
        if payload is None:
            print(f"│       · {kind}")
        else:
            s = str(payload)
            if len(s) > 60:
                s = s[:57] + "..."
            print(f"│       · {kind}  {s}")

    def end(self, status: str = "pass") -> None:
        print(f"└── {status} · {self.test_name}")


@pytest.fixture
def reporter(request: pytest.FixtureRequest) -> Reporter:
    return Reporter(request.node.name)
