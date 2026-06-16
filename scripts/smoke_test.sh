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
#   - container can't import / boots crashes        → /api/healthz never 200s
#   - DB unreachable (Cloud SQL connector misset)   → /api/healthz 503
#   - GCS bucket / IAM misconfigured                 → /api/healthz still 200 (intentional;
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

step "api /api/healthz (liveness + DB)"
probe "${API_URL}/api/healthz" "api healthz"
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

# Same-origin LB routing check: hitting /api/* on the WEB host should
# reach the api container IF a load balancer is configured to do that.
# Phase 1 deploys don't set up an LB yet — the web bundle calls the api
# directly via its public Cloud Run URL (NEXT_PUBLIC_API_BASE baked in
# at build time). In that mode ``${WEB_URL}/api/health`` is just the
# web container's Next.js handler for an unknown path → typically 404,
# and that's fine. So this check is informational only: print what we
# saw, never fail.
#
# Once a real LB / custom domain fronts both services, flip this into a
# hard check by ``exit 1``-ing in the non-200 case.
step "lb: web /api/health → api (informational, no LB yet)"
http_code=$(curl --silent --output /tmp/smoke_body --write-out '%{http_code}' \
  --max-time 8 "${WEB_URL}/api/health" || echo "000")
case "$http_code" in
  200)
    if grep -q '"status":"ok"' /tmp/smoke_body; then
      echo "[smoke] note: web /api/health → 200 + api body — LB routing wired"
    else
      echo "[smoke] note: web /api/health → 200 but not api body — web is handling the path itself (no LB)"
    fi
    ;;
  401|403)
    echo "[smoke] note: web /api/health → $http_code — LB routed it to api which auth-gated"
    ;;
  *)
    echo "[smoke] note: web /api/health → $http_code — no LB; web bundle calls api directly via baked-in URL"
    ;;
esac

echo
echo "[smoke] all checks passed for rev-${SHORT_SHA}"
