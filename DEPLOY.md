# Deploying uteki to Google Cloud Run

This runbook covers the one-time GCP setup, the first manual deploy, env var
wiring, rollbacks, and how to test the Docker images locally before shipping.

Region: **us-central1** (Cloud Run + Cloud SQL + GCS all available, lowest cost
for first-tier traffic).

## 0. Prerequisites

- `gcloud` CLI installed and on PATH (`brew install --cask google-cloud-sdk`)
- A GCP project (replace `$PROJECT_ID` below with yours)
- Billing enabled on the project
- Docker daemon running locally if you want to test images before pushing

```bash
gcloud auth login
gcloud config set project $PROJECT_ID
gcloud config set run/region us-central1
```

Enable the APIs we need:

```bash
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  sqladmin.googleapis.com \
  secretmanager.googleapis.com \
  storage.googleapis.com
```

## 1. One-time infra setup

### Artifact Registry

```bash
gcloud artifacts repositories create uteki \
  --repository-format=docker \
  --location=us-central1 \
  --description="uteki container images"
```

### Cloud Run services (placeholders, deployed empty)

Cloud Build expects the services to already exist so `gcloud run deploy` can
update them with `--no-traffic`. Bootstrap with a stock image:

```bash
gcloud run deploy uteki-api \
  --image=gcr.io/cloudrun/hello \
  --region=us-central1 \
  --allow-unauthenticated \
  --port=8080

gcloud run deploy uteki-web \
  --image=gcr.io/cloudrun/hello \
  --region=us-central1 \
  --allow-unauthenticated \
  --port=8080
```

### Cloud SQL (Postgres 16)

```bash
gcloud sql instances create uteki-pg \
  --database-version=POSTGRES_16 \
  --region=us-central1 \
  --tier=db-f1-micro \
  --storage-size=10GB \
  --storage-auto-increase

gcloud sql databases create uteki --instance=uteki-pg
gcloud sql users create uteki --instance=uteki-pg --password=<set-a-strong-one>
```

Grab the instance connection name (format `PROJECT:REGION:INSTANCE`):

```bash
gcloud sql instances describe uteki-pg --format='value(connectionName)'
```

### GCS bucket (artifact store)

```bash
gcloud storage buckets create gs://$PROJECT_ID-uteki-artifacts \
  --location=us-central1 \
  --uniform-bucket-level-access
```

### Secret Manager

```bash
echo -n "<your-32+char-jwt-secret>" | gcloud secrets create uteki-jwt-secret --data-file=-
echo -n "sk-ant-..."                | gcloud secrets create uteki-anthropic-key --data-file=-
echo -n "<32+char-webhook-secret>"  | gcloud secrets create uteki-webhook-secret --data-file=-

# The full Postgres DSN goes in as one secret — including the password.
# The application code reads UTEKI_DB_URL and feeds it straight to
# sqlalchemy.create_engine; there is no separate UTEKI_DB_PASSWORD env.
# Format below uses the Unix-socket path Cloud Run gets via
# --add-cloudsql-instances; for IP-based connections use host=<ip>.
SQL_CONN=$(gcloud sql instances describe uteki-pg --format='value(connectionName)')
echo -n "postgresql+psycopg://uteki:<db-password>@/uteki?host=/cloudsql/$SQL_CONN" \
  | gcloud secrets create uteki-db-url --data-file=-
```

Grant the Cloud Run runtime SA access (default SA shown — replace if you use a
dedicated one):

```bash
PROJECT_NUMBER=$(gcloud projects describe $PROJECT_ID --format='value(projectNumber)')
RUNTIME_SA=$PROJECT_NUMBER-compute@developer.gserviceaccount.com

for s in uteki-jwt-secret uteki-db-url uteki-anthropic-key uteki-webhook-secret; do
  gcloud secrets add-iam-policy-binding $s \
    --member=serviceAccount:$RUNTIME_SA \
    --role=roles/secretmanager.secretAccessor
done
```

### Cloud Build SA permissions

```bash
CB_SA=$PROJECT_NUMBER@cloudbuild.gserviceaccount.com
for role in roles/run.admin roles/iam.serviceAccountUser roles/artifactregistry.writer; do
  gcloud projects add-iam-policy-binding $PROJECT_ID \
    --member=serviceAccount:$CB_SA --role=$role
done
```

## 2. First manual deploy

From the repo root:

```bash
gcloud builds submit --config=cloudbuild.yaml
```

This runs the whole pipeline: build → push → deploy api + web with
`--no-traffic` → smoke-probe the tagged revisions → flip 100% traffic on
green. The smoke step runs `scripts/smoke_test.sh` against
`https://rev-${SHORT_SHA}---uteki-{api,web}-<hash>-uc.a.run.app` and exits
non-zero on any of: `/api/healthz` not 200, DB roundtrip failed, web root
missing `<title>`, web→api LB routing broken. If smoke fails the build is
red and the staged revisions stay at 0% traffic — fix forward, re-run.

Manual promote (only if you bypassed cloudbuild or smoke is intentionally
disabled):

```bash
gcloud run services update-traffic uteki-api --region=us-central1 --to-latest
gcloud run services update-traffic uteki-web --region=us-central1 --to-latest
```

## 3. Wiring env vars + secrets onto Cloud Run

### api

```bash
SQL_CONN=$(gcloud sql instances describe uteki-pg --format='value(connectionName)')

gcloud run services update uteki-api \
  --region=us-central1 \
  --add-cloudsql-instances=$SQL_CONN \
  --set-env-vars="\
UTEKI_AUTH_REQUIRED=true,\
UTEKI_USE_MOCK_LLM=false,\
UTEKI_DEFAULT_MODEL=anthropic/claude-sonnet-4-5,\
UTEKI_STORAGE_BACKEND=gcs,\
UTEKI_GCS_BUCKET=$PROJECT_ID-uteki-artifacts,\
UTEKI_OWNER_EMAILS=rain1104@foxmail.com" \
  --set-secrets="\
UTEKI_JWT_SECRET=uteki-jwt-secret:latest,\
UTEKI_DB_URL=uteki-db-url:latest,\
UTEKI_WEBHOOK_SECRET=uteki-webhook-secret:latest,\
ANTHROPIC_API_KEY=uteki-anthropic-key:latest"
```

Notes:
- `UTEKI_STORAGE_BACKEND` (NOT `UTEKI_ARTIFACT_BACKEND`) — the older name was
  in earlier drafts of this doc; the code reads `UTEKI_STORAGE_BACKEND`.
- `UTEKI_DB_URL` is a *secret*, not an env var, because it contains the
  password. Cloud Run's secret-env injection makes it indistinguishable from
  a plain env var at runtime.
- `UTEKI_OWNER_EMAILS` is what makes you admin when you OAuth in. Without
  it, every account starts as `reader` and you can't mutate the watchlist.
- `UTEKI_WEBHOOK_SECRET` gates `POST /api/triggers/event` with HMAC-SHA256.
  If unset in prod the endpoint returns 503 by design.

### web

```bash
gcloud run services update uteki-web \
  --region=us-central1 \
  --set-env-vars="\
NEXT_PUBLIC_API_URL=/api,\
NODE_ENV=production"
```

Same-origin Load Balancer routing means the web container talks to `/api/*` and
the LB forwards those to `uteki-api`. No `NEXT_PUBLIC_API_BASE` with a separate
hostname needed.

## 4. Rollback

List revisions:

```bash
gcloud run revisions list --service=uteki-api --region=us-central1
```

Flip 100% traffic back to a previous revision (replace `PREVIOUS` with the
revision name from the list):

```bash
gcloud run services update-traffic uteki-api \
  --region=us-central1 \
  --to-revisions=PREVIOUS=100
```

Same recipe for `uteki-web`.

## 5. Local Docker testing

Both Dockerfiles expect the **monorepo root** as the build context.

### api

```bash
docker build -f services/api/Dockerfile -t uteki-api:dev .
docker run --rm -p 8080:8080 \
  -e UTEKI_USE_MOCK_LLM=true \
  -e UTEKI_AUTH_REQUIRED=false \
  -e UTEKI_JWT_SECRET=$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))') \
  uteki-api:dev
# then: curl http://localhost:8080/api/healthz
```

### web

```bash
docker build -f apps/web/Dockerfile -t uteki-web:dev .
docker run --rm -p 8080:8080 uteki-web:dev
# then: open http://localhost:8080
```

## 6. Things still TODO (Phase 2)

- **OpenBB sidecar deployment**: `services/openbb/` exists as a uv project
  but has no Dockerfile and no entry in `cloudbuild.yaml`. The four tools
  that route through it (`sec_fundamentals`, `macro_fred`, `macro_rates`,
  `company_intel`) degrade gracefully to "sidecar unreachable" tool errors
  if it's not deployed — the rest of the app still works. Phase 2 ships
  this as a 3rd Cloud Run service plus the auth wiring (service-to-service
  identity tokens).
- **Cloud Build trigger**: do this once in the GCP console
  (Cloud Build → Triggers → connect repo → push to main → use
  `/cloudbuild.yaml`).
- **`/admin/users` UI for role management**: backend
  `PATCH /api/admin/users/{id}` exists; no frontend wiring yet, so adding
  a second admin currently requires editing `UTEKI_OWNER_EMAILS` and
  redeploying (or a `gcloud sql ... UPDATE user SET role='admin'`).
