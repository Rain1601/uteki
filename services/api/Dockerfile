# syntax=docker/dockerfile:1.7
#
# Production Dockerfile for services/api (FastAPI, Python 3.13, uv-managed).
# Build context MUST be the monorepo root. The Cloud Build step uses:
#   docker build -f services/api/Dockerfile -t ... .
#
# Two stages:
#   1. deps    — install uv-resolved virtualenv from uv.lock (cached layer)
#   2. runtime — slim python image with just the venv + source
#
# Cloud Run binds to $PORT (defaults to 8080). For Cloud SQL access, the
# Postgres connector mounts a unix socket at /cloudsql/<conn>/.s.PGSQL.5432
# when --add-cloudsql-instances is set on the Cloud Run service. No extra
# Dockerfile config needed for that — the runtime sees it as a filesystem
# path and any standard pg driver (psycopg, asyncpg) connects via that
# socket.

# ─── Stage 1: uv sync into /api/.venv ───────────────────────────────────────
FROM python:3.13-slim AS deps
WORKDIR /api

# uv is a single static binary. Install via the official installer.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && curl -LsSf https://astral.sh/uv/install.sh | sh \
    && cp /root/.local/bin/uv /usr/local/bin/uv \
    && apt-get purge -y --auto-remove curl \
    && rm -rf /var/lib/apt/lists/*

# Copy lock + manifest + README (referenced by pyproject's readme=) first so
# this layer caches across source edits. hatchling reads README.md during the
# editable install of the project itself triggered by `uv sync`.
COPY services/api/pyproject.toml services/api/uv.lock services/api/README.md /api/

# Extras pulled in for production deployment:
#   --extra gcs       → google-cloud-storage (GCS-backed ArtifactStore).
#   --extra postgres  → psycopg[binary] (Cloud SQL Postgres driver).
#   --extra cloudsql  → cloud-sql-python-connector (recommended Cloud Run
#                       path to Cloud SQL, avoids needing a proxy sidecar).
# uv will FAIL on an unknown extra, so if a sister PR is still in flight and
# one of these isn't yet in pyproject.toml, drop it from the flags below.
#
# --frozen ensures the build uses the exact uv.lock pins (CI-safe).
# --no-dev skips dev/test deps (ruff, pytest, …).
# --no-install-project skips installing uteki-api itself here — we install
# deps only in this layer so source edits don't bust the cache. The project
# source is imported via PYTHONPATH in the runtime stage.
RUN uv sync --frozen --no-dev --no-install-project \
    --extra gcs --extra postgres --extra cloudsql

# ─── Stage 2: runtime ───────────────────────────────────────────────────────
FROM python:3.13-slim AS runtime
WORKDIR /api

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8080 \
    PATH="/api/.venv/bin:$PATH" \
    PYTHONPATH="/api/src"

# Install minimal runtime deps. libpq is needed if/when the postgres extra
# lands (psycopg[binary] bundles libpq, but psycopg w/o [binary] doesn't —
# safe to ship libpq either way; ~3MB).
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Copy the uv-managed virtualenv from the deps stage.
COPY --from=deps /api/.venv /api/.venv

# Source last so edits don't invalidate the venv layer.
COPY services/api/src /api/src

WORKDIR /api/src

EXPOSE 8080
# Bind to 0.0.0.0:$PORT — Cloud Run requires this. Shell form so $PORT expands.
CMD ["sh", "-c", "uvicorn uteki_api.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
