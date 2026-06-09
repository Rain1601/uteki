# SQLite → Cloud SQL Postgres migration

Production deploys point `UTEKI_DB_URL` at Cloud SQL Postgres 17. Local dev
stays on SQLite — nothing changes for `make dev`.

## Pointing at Cloud SQL

Cloud SQL Postgres 17 instance, Cloud Run consumer. Cloud Run sets up a
Unix socket at `/cloudsql/<conn-name>` when you bind the instance to the
service; libpq accepts that path via the `host` query parameter:

```bash
UTEKI_DB_URL='postgresql+psycopg://uteki_app:<pw>@/uteki?host=/cloudsql/myproj:us-central1:uteki-pg'
```

Install the prod driver: `uv sync --extra postgres`. Defaults stay SQLite
so `uv sync` alone keeps dev light (`psycopg[binary]` is ~50 MB).

## Cloud SQL Connector vs Auth Proxy — pick Connector

| Option | How it runs | Pros | Cons |
| --- | --- | --- | --- |
| **Cloud SQL Python Connector** (`cloud-sql-python-connector`) | Library inside the app process | No sidecar, no extra container, IAM auth via ADC, automatic mTLS, no port to expose | Python-only, adds a dep |
| Cloud SQL Auth Proxy | Sidecar binary listening on a local socket | Language-agnostic, no app code change | Cloud Run sidecars are extra config + cold-start cost; networking surface bigger |

**Recommendation: Cloud SQL Connector.** Cloud Run already runs a single
container per instance; piping the DB through an in-process Connector
keeps the deploy shape simple (one container, one process tree, ADC
already wired). The `cloudsql` optional extra installs it. The
connection flow is:

```python
# Hook the Connector into the SQLAlchemy engine at startup
from google.cloud.sql.connector import Connector, IPTypes

connector = Connector()
def getconn():
    return connector.connect(
        "myproj:us-central1:uteki-pg",
        "psycopg",
        user="uteki_app",
        password=secret,  # or use IAM auth
        db="uteki",
        ip_type=IPTypes.PRIVATE,
    )

engine = create_engine(
    "postgresql+psycopg://",
    creator=getconn,
    pool_size=5, max_overflow=10, pool_recycle=300, pool_pre_ping=True,
)
```

`core/db.py:_make_engine` covers the simpler Unix-socket case. If we move
to the Connector, wire `creator=` into `_make_engine` behind a feature
flag — don't rip out the socket path, it's the fallback when ADC isn't
available (e.g. local-with-cloud-db debug).

## Schema migration — alembic, run once at deploy

`core/db.py` currently has hand-rolled `_ensure_*_column` helpers that
ALTER TABLE if a column is missing. They're load-bearing for local
SQLite dev (a checkout from before column X exists is one `init_db()`
away from working). They are *also* PG-compatible by accident — the
ALTER TABLE / UPDATE / CREATE INDEX statements they emit work as-is on
Postgres 17. So the deploy can ship without rewriting them.

That said: production should use alembic. Migration plan:

| `_ensure_*` helper | Column it adds | Alembic migration | Removable when |
| --- | --- | --- | --- |
| `_ensure_user_role_column` | `user.role VARCHAR(16) DEFAULT 'reader'` | NOT YET WRITTEN | first alembic baseline lands and every existing SQLite dev DB has been touched by it |
| `_ensure_run_assessment_columns` | `run.harness_status`, `run.evaluator_decision`, `run.overall_assessment` | NOT YET WRITTEN | same |
| `_ensure_run_visibility_column` | `run.visibility VARCHAR(16) DEFAULT 'private'` + `ix_run_visibility` | NOT YET WRITTEN | same |

There is no `services/api/alembic/` directory yet despite the comment in
`core/db.py` claiming one was scaffolded in M4.1 — it never landed.
Bootstrap:

```bash
cd services/api
uv run alembic init alembic        # creates alembic/ + alembic.ini
# Wire env.py: target_metadata = SQLModel.metadata + import models for side-effects
uv run alembic revision --autogenerate -m "baseline — M4 schema as of <commit>"
```

Then for prod deploy:

```bash
uv run alembic upgrade head        # runs once at deploy, NOT request-time
```

Run this as a Cloud Run Job (or `gcloud builds run`), not from the
request-serving service. The serving service must NOT call `init_db()`
in prod once alembic exists — concurrent `CREATE TABLE IF NOT EXISTS`
across replicas is racy enough on PG to log warnings, and we want one
authoritative migration step per deploy.

Until alembic lands: `init_db()` + `_ensure_*` are still safe on PG
because every ALTER TABLE / CREATE INDEX statement uses syntax PG
accepts. Audit findings (full table in this doc's PR description):
every raw-SQL line in `core/db.py` is PG-compatible.

## Connection pool sizing

`core/db.py` configures: `pool_size=5, max_overflow=10, pool_recycle=300,
pool_pre_ping=True`.

- Total per-instance connections = `pool_size + max_overflow = 15`.
- Cloud Run scales horizontally → multiply by `max-instances`. Default
  Cloud Run cap is 100 instances → 1500 connections. **That overruns
  every shared-core Cloud SQL tier.**
- Tier limits (Postgres 17, default `max_connections`):
  - `db-f1-micro` → 25
  - `db-g1-small` → 50
  - `db-custom-1-3840` → 100
  - `db-custom-2-7680` → 200
- Concrete recommendation for v0: cap Cloud Run `max-instances` at the
  level that keeps `instances × 15` under the DB's `max_connections`,
  leaving 10 connections of headroom for `alembic upgrade`, `psql`
  debugging, and the Connector's reservations.
- `pool_recycle=300` is below Cloud SQL's 600s idle timeout so we never
  hand a dead socket to a request. `pool_pre_ping=True` adds a one-RTT
  `SELECT 1` before each checkout — slight latency cost, but bulletproof
  against network-level disconnects that the recycle timer doesn't
  catch.

## Audit — raw SQL inventory

Every raw `text(...)` execution in the backend lives in
`services/api/src/uteki_api/core/db.py`. All eight statements are PG 17
compatible as-is (`ALTER TABLE ... ADD COLUMN`, default literals,
`UPDATE ... CASE WHEN`, `CREATE INDEX IF NOT EXISTS`). No code path
uses `PRAGMA`, `VACUUM`, `AUTOINCREMENT`, `INSERT OR REPLACE`, or any
SQLite-specific dialect. The other store layers (`SqliteRunStore`,
`SqlUserStore`) go through SQLModel session APIs only — fully
dialect-neutral.

## Things that change at deploy time vs don't

Changes:
- `UTEKI_DB_URL` → PG connection string
- Install `[postgres]` extra (and optionally `[cloudsql]`)
- Run alembic once per deploy
- Don't run `init_db()` in the serving process once alembic is the SSOT

Doesn't change:
- SQLModel definitions
- Any application code (the dialect is invisible above the engine)
- The `_ensure_*` helpers (still safe; remove after alembic catches up)
- The E2E test suite (stays on SQLite — would be slower + needs a CI PG
  service to be worth the move)
