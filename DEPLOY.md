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
echo -n "<db-password>"              | gcloud secrets create uteki-db-password --data-file=-
echo -n "sk-ant-..."                  | gcloud secrets create uteki-anthropic-key --data-file=-
```

Grant the Cloud Run runtime SA access (default SA shown — replace if you use a
dedicated one):

```bash
PROJECT_NUMBER=$(gcloud projects describe $PROJECT_ID --format='value(projectNumber)')
RUNTIME_SA=$PROJECT_NUMBER-compute@developer.gserviceaccount.com

for s in uteki-jwt-secret uteki-db-password uteki-anthropic-key; do
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
`--no-traffic`. The smoke step is a no-op (TODO PR ε) and the traffic-flip
steps are commented out — meaning the first deploy stages revisions but does
NOT serve them. To promote manually:

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
UTEKI_DB_URL=postgresql+psycopg://uteki@/uteki?host=/cloudsql/$SQL_CONN,\
UTEKI_ARTIFACT_BACKEND=gcs,\
UTEKI_GCS_BUCKET=$PROJECT_ID-uteki-artifacts" \
  --set-secrets="\
UTEKI_JWT_SECRET=uteki-jwt-secret:latest,\
UTEKI_DB_PASSWORD=uteki-db-password:latest,\
ANTHROPIC_API_KEY=uteki-anthropic-key:latest"
```

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
# then: curl http://localhost:8080/healthz
```

### web

```bash
docker build -f apps/web/Dockerfile -t uteki-web:dev .
docker run --rm -p 8080:8080 uteki-web:dev
# then: open http://localhost:8080
```

## 6. Things that don't work yet

- `scripts/smoke_test.sh` referenced by the `smoke` step in `cloudbuild.yaml`:
  TODO PR ε. The step currently exits 0 unconditionally — meaning the
  pipeline will mark itself green even if the staged revision is broken. The
  traffic-flip steps are commented out as a safety net until smoke is real.
- Automatic traffic promotion after smoke: commented out in `cloudbuild.yaml`.
  Un-comment the two `promote-*` steps once smoke is real.
- Cloud Build trigger creation itself: do this once in the GCP console
  (Cloud Build → Triggers → connect repo → push to main → use
  `/cloudbuild.yaml`).
- `/healthz` route on the api: not yet implemented (api responds on `/`).
  Smoke should hit `/` until `/healthz` lands, or the smoke step adds the
  route as part of PR ε.
