#!/usr/bin/env bash
# scripts/deploy.sh — one-shot manual Cloud Build invocation.
#
# Why this wrapper: ``$COMMIT_SHA`` and ``$SHORT_SHA`` are Cloud Build
# system substitutions that are only auto-populated for builds triggered
# from a git source (Cloud Build Trigger, GitHub push, etc.). For an
# ad-hoc ``gcloud builds submit`` from your laptop they're empty strings,
# so the resulting image tag becomes ``uteki/api:`` (trailing colon) and
# Cloud Build rejects the build with INVALID_ARGUMENT.
#
# This script reads the current HEAD's SHA and passes it through. The
# YAML's ``substitution_option: ALLOW_LOOSE`` allows the override.
#
# Once you set up a Cloud Build Trigger on push-to-main (DEPLOY.md §6),
# the trigger populates these automatically and this wrapper is no
# longer needed for CI — but it's still the right thing for manual
# re-runs / fix-forward iterations.

set -euo pipefail

cd "$(dirname "$0")/.."

if ! git diff --quiet HEAD; then
  echo "[deploy] WARNING: working tree has uncommitted changes." >&2
  echo "         The build will use the local files, but the COMMIT_SHA" >&2
  echo "         tag will point at HEAD — recreating this exact image from" >&2
  echo "         the git SHA later will NOT reproduce the build." >&2
fi

COMMIT=$(git rev-parse HEAD)
SHORT=$(git rev-parse --short HEAD)

echo "[deploy] commit: $COMMIT"
echo "[deploy] short:  $SHORT"
echo "[deploy] launching cloud build…"
echo

exec gcloud builds submit \
  --config=cloudbuild.yaml \
  --substitutions="COMMIT_SHA=${COMMIT},SHORT_SHA=${SHORT}" \
  "$@"
