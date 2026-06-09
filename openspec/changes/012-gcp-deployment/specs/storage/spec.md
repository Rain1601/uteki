## ADDED Requirements

### Requirement: New `ArtifactStore` implementation — `GCSArtifactStore`

A new implementation of the `ArtifactStore` ABC, **`GCSArtifactStore`**, SHALL store artifact bytes + manifest JSON in a Google Cloud Storage bucket. It is selected at module-load time via `UTEKI_STORAGE_BACKEND=gcs`; the default `fs` value continues to select `LocalFileArtifactStore`. Both implementations SHALL be byte-equivalent for the same input.

#### Scenario: Backend selection via env

- **GIVEN** `UTEKI_STORAGE_BACKEND` is unset or set to `fs`
- **WHEN** `services/api/src/uteki_api/artifacts/__init__.py` is imported
- **THEN** `default_artifact_store` SHALL be a `LocalFileArtifactStore`

- **GIVEN** `UTEKI_STORAGE_BACKEND=gcs` and `UTEKI_GCS_BUCKET=<name>`
- **WHEN** the module is imported
- **THEN** `default_artifact_store` SHALL be a `GCSArtifactStore(bucket_name=<name>)`

- **GIVEN** `UTEKI_STORAGE_BACKEND=gcs` and `UTEKI_GCS_BUCKET` is missing or empty
- **WHEN** the module is imported
- **THEN** import SHALL raise `RuntimeError("UTEKI_GCS_BUCKET must be set when UTEKI_STORAGE_BACKEND=gcs")`

#### Scenario: ABC signature unchanged

- **WHEN** any consumer of `ArtifactStore` (e.g. `RunArtifacts`, `api/artifacts.py`) calls `write` / `read` / `list` / `exists`
- **THEN** the call SHALL succeed with identical method signature regardless of backend
- **AND** no caller SHALL need to know which backend is active

#### Scenario: Path scheme mirrors LocalFile

`GCSArtifactStore` SHALL use blob names that mirror the on-disk layout of `LocalFileArtifactStore`:

```
gs://<bucket>/users/<safe(user_id)>/runs/<sha2(run_id[:2])>/<run_id>/artifacts/<name>
gs://<bucket>/users/<safe(user_id)>/runs/<sha2(run_id[:2])>/<run_id>/manifest.json
```

- **AND** for the legacy `user_id=None` code path (`system` / internal calls), the blob name SHALL be `<sha2>/<run_id>/...` (no `users/` prefix), matching the LocalFile fallback
- **AND** the sha2 sharding SHALL use `run_id[:2]` exactly as LocalFile does
- **AND** name validation (`_validate_name`, allowed chars `[A-Za-z0-9._-]+`, reject `.` / `..`) SHALL be reused via shared helper

#### Scenario: write is atomic and last-write-wins

- **WHEN** `write(run_id, name, content, ...)` is called
- **THEN** the body blob SHALL be uploaded via `blob.upload_from_string` (single-PUT, strongly consistent)
- **AND** the manifest blob SHALL be re-uploaded with the latest artifact entry merged in (last-write-wins on the artifact name)
- **AND** no two-step temp-then-rename SHALL be required (GCS single-PUT is atomic at the object level)

#### Scenario: read returns 404-shaped error on cross-user access

- **GIVEN** run `R` belongs to user A, with artifact `r.md` written
- **WHEN** `read(R, "r.md", user_id="<B>")` is called by the API layer
- **THEN** the blob lookup at `users/<B>/runs/.../R/artifacts/r.md` SHALL miss
- **AND** the call SHALL raise `FileNotFoundError`
- **AND** the API layer SHALL map this to HTTP 404 (same shape as "doesn't exist", per existing M4 invariant)

#### Scenario: manifest race condition handled by run-singleton invariant

- **GIVEN** the platform invariant that exactly one worker writes artifacts for a given `run_id` at any time (010 + 011)
- **THEN** concurrent manifest blob writes for the same `run_id` SHALL NOT occur in practice
- **AND** the GCS last-write-wins semantic is acceptable
- **AND** future distributed-worker scenarios that violate this invariant SHALL require a follow-up change (replacing the shared manifest blob with per-artifact GCS object metadata)

### Requirement: GCS bucket-level permission model

The Cloud Run service account `uteki-api-sa` SHALL have `roles/storage.objectAdmin` on the entire `uteki-artifacts` bucket. Cross-user isolation SHALL be enforced **at the application layer** via the existing `_owner_id(run_id, user)` ownership helper, not via IAM conditions.

#### Scenario: api SA can read/write any blob in bucket

- **GIVEN** `uteki-api-sa` has `roles/storage.objectAdmin` on `uteki-artifacts/`
- **WHEN** the api process performs any GCS operation
- **THEN** the GCS API SHALL allow it (no IAM-side ownership check)

#### Scenario: Application layer enforces ownership

- **GIVEN** request to `GET /api/runs/{run_id}/artifacts/{name}` from user B for a private run owned by A
- **WHEN** the handler resolves ownership via `_owner_id(run_id, user)`
- **THEN** the handler SHALL invoke the store with `user_id = run.user_id` (= A)
- **AND** if the requesting user is not A and the run is not public, the handler SHALL return 404 before any GCS call is made

#### Scenario: No condition-IAM per-user partitioning in MVP

- **WHEN** auditing IAM bindings on `uteki-artifacts/`
- **THEN** no `iam.gserviceaccount.com` member SHALL have a condition like `resource.name.startsWith("projects/_/buckets/uteki-artifacts/objects/users/<uid>/")`
- **AND** future multi-tenant scenarios MAY introduce condition-IAM as defense-in-depth, tracked in a future change

### Requirement: web service account has no data-plane access

The Cloud Run service account `uteki-web-sa` SHALL NOT have any of:

- `roles/storage.*` on `uteki-artifacts/`
- `roles/cloudsql.*` on the project
- `roles/secretmanager.*` on any secret

It SHALL only have `roles/logging.logWriter` (auto-bound by Cloud Run).

#### Scenario: web container compromise containment

- **GIVEN** the `uteki-web` container is compromised (RCE, dependency vuln, etc.)
- **WHEN** the attacker attempts to read GCS / SQL / Secret Manager from inside the container
- **THEN** all calls SHALL fail with `permission denied`
- **AND** the blast radius SHALL be limited to whatever NEXT_PUBLIC env vars the container holds (no secrets)

## MODIFIED Requirements

### Requirement: Storage partitioning table includes backend swap dimension

The "Storage — spec" table that lists user-owned stores SHALL be extended with a column indicating the **prod-time backend**:

| Store | Partition key | Dev impl | Prod impl |
|---|---|---|---|
| RunStore | `Run.user_id` column | `SqliteRunStore` (SQLite) | `SqliteRunStore` (Postgres via SQLAlchemy URL swap) |
| ArtifactStore | path prefix `users/<user_id>/runs/...` | `LocalFileArtifactStore` | `GCSArtifactStore` |
| Memory (short-term) | dict key `(user_id, session_id)` | `InMemoryStore` | `InMemoryStore` (per-instance; ephemeral) |
| EvalHistoryStore | path prefix `users/<user_id>/eval-history/...` | `JsonFileEvalHistory` (local) | unchanged — eval is internal-only, runs from owner laptop |

- **AND** the backend selection SHALL be controlled by env (`UTEKI_STORAGE_BACKEND` for artifacts; `UTEKI_DB_URL` scheme for runs/users)
- **AND** the SQLModel ORM layer SHALL be backend-agnostic — all stores read DB URL from `settings.db_url` and call SQLModel/SQLAlchemy abstractions, never raw dialect-specific SQL

#### Scenario: Path scheme equivalence across backends

- **GIVEN** identical inputs to `LocalFileArtifactStore.write` and `GCSArtifactStore.write`
- **WHEN** an artifact is written with `(user_id=U, run_id=R, name=N)`
- **THEN** LocalFile SHALL place it at `<root>/users/<U>/runs/<sha2(R)>/<R>/artifacts/<N>`
- **AND** GCS SHALL place it at `gs://<bucket>/users/<U>/runs/<sha2(R)>/<R>/artifacts/<N>`
- **AND** the byte contents of the body blob SHALL be identical
- **AND** the manifest JSON SHALL be byte-identical (after sort)

#### Scenario: Memory store ephemerality is acceptable

- **GIVEN** Cloud Run instances scale to zero between idle periods
- **WHEN** short-term memory (`InMemoryStore`) is consulted after a cold start
- **THEN** prior `(user_id, session_id)` history MAY be gone
- **AND** this is acceptable because session-scoped chat history is recoverable from the persisted `Run.events_json` / `RunEventStore` (011)
- **AND** future hardening MAY introduce a `RedisMemory` impl; out of scope for this change
