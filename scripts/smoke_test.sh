#!/usr/bin/env bash
# scripts/smoke_test.sh — verify a freshly staged Cloud Run revision before
# flipping 100% traffic to it.
#
# Called from cloudbuild.yaml's `smoke` step after both `uteki-api` and
# `uteki-web` revisions have been deployed with --no-traffic --tag=rev-$SHORT_SHA.
#
# Inputs (all from cloudbuild substitutions / env):
#   SHORT_SHA           the 7-char git SHA, used as the revision tag
#   PROJECT_ID          GCP project ID, used by gcloud describe
#   REGION              Cloud Run region (default us-central1)
#
# Strategy:
# 1. Look up each service's base URL via `gcloud run services describe`.
#    The tagged-revision URL is the base URL with the host's first dotted
#    segment prefixed by `rev-${SHORT_SHA}---`.
# 2. Probe the tagged URLs (not the live ones) so we test the new revision
#    before it serves any user traffic.
# 3. Exit non-zero on the first failure. cloudbuild's `waitFor` chain gates
#    the promote-* steps on this script's exit code.
#
# What this catches (real failure modes from past deploys):
#   - container can't import / boots crashes        → /healthz never 200s
#   - DB unreachable (Cloud SQL connector misset)   → /healthz 503
#   - GCS bucket / IAM misconfigured                 → /healthz still 200 (intentional;
#                                                       artifact write is lazy, smoke can't
#                                                       trigger without auth — caught at
#                                                       first real chat run instead)
#   - LB → api routing broken                        → /api/health via web 404
#   - web container build broken (no <title>)        → web /  doesn't render shell
#
# Exit codes: 0 = green, anything else = red.

set -euo pipefail

REGION="${REGION:-us-central1}"
PROJECT_ID="${PROJECT_ID:?PROJECT_ID is required}"
SHORT_SHA="${SHORT_SHA:?SHORT_SHA is required}"

step() { printf '\n[smoke] %s\n' "$*"; }

# Convert a Cloud Run base URL into the per-revision tag URL.
# Input:  https://uteki-api-xxxxxxxxxx-uc.a.run.app
# Output: https://rev-abc1234---uteki-api-xxxxxxxxxx-uc.a.run.app
tag_url() {
  local base="$1" tag="$2"
  echo "$base" | sed -E "s|^https://([^/]+)|https://${tag}---\1|"
}

step "resolve service URLs"
API_BASE="$(gcloud run services describe uteki-api \
  --region="$REGION" --project="$PROJECT_ID" \
  --format='value(status.url)')"
WEB_BASE="$(gcloud run services describe uteki-web \
  --region="$REGION" --project="$PROJECT_ID" \
  --format='value(status.url)')"

API_URL="$(tag_url "$API_BASE" "rev-${SHORT_SHA}")"
WEB_URL="$(tag_url "$WEB_BASE" "rev-${SHORT_SHA}")"

echo "  api revision URL: $API_URL"
echo "  web revision URL: $WEB_URL"

# Retry loop — Cloud Run revisions can take ~30s to be reachable after a
# deploy returns. Probe with a short timeout, up to ~90s total.
probe() {
  local url="$1" desc="$2" tries=0 max=18 status=0
  while [ "$tries" -lt "$max" ]; do
    if curl --fail --silent --show-error --max-time 8 "$url" >/tmp/smoke_body 2>/dev/null; then
      status=200
      break
    fi
    tries=$((tries + 1))
    sleep 5
  done
  if [ "$status" != "200" ]; then
    echo "[smoke] FAIL: $desc — $url did not return 2xx after $((max * 5))s" >&2
    return 1
  fi
}

step "api /healthz (liveness + DB)"
probe "${API_URL}/healthz" "api healthz"
grep -q '"db":"ok"' /tmp/smoke_body || {
  echo "[smoke] FAIL: api healthz missing db=ok marker" >&2
  cat /tmp/smoke_body >&2
  exit 1
}

step "web / (shell renders)"
probe "${WEB_URL}/" "web root"
grep -qi '<title>' /tmp/smoke_body || {
  echo "[smoke] FAIL: web root has no <title> — shell broken" >&2
  exit 1
}

# Same-origin LB routing check: hitting /api/* on the WEB host must
# reach the api container. If this returns HTML, the LB rule isn't
# set up; if it returns 401, the LB is fine and auth is doing its job
# (which is the expected prod behavior).
step "lb: web /api/health → api"
http_code=$(curl --silent --output /tmp/smoke_body --write-out '%{http_code}' \
  --max-time 8 "${WEB_URL}/api/health" || echo "000")
case "$http_code" in
  200)
    grep -q '"status":"ok"' /tmp/smoke_body || {
      echo "[smoke] FAIL: /api/health via web returned 200 but wrong body" >&2
      cat /tmp/smoke_body >&2
      exit 1
    }
    ;;
  401|403)
    # If the LB-routed /api/health is auth-gated in prod, that's still proof
    # routing works. Health is currently public so this branch is a safety net.
    echo "[smoke] note: /api/health via web returned $http_code (LB routing OK)"
    ;;
  *)
    echo "[smoke] FAIL: /api/health via web returned $http_code — LB routing broken" >&2
    head -c 500 /tmp/smoke_body >&2
    exit 1
    ;;
esac

echo
echo "[smoke] all checks passed for rev-${SHORT_SHA}"
