#!/usr/bin/env bash
#
# Background warm-up: hits every dev route once after the web server is up,
# so Next.js + Turbopack compiles them ahead of time. After this finishes,
# clicking through the app in the browser doesn't show the "Compiling..."
# toast for the warmed routes — they're already in Turbopack's cache.
#
# Called from scripts/dev.sh in the background. Safe to run standalone too.
#
# Costs: ~5-15s of one-time CPU after dev server boots, ~200 MB extra RAM.
# Saves: the per-route first-visit "Compiling..." flash that interrupts
# the first navigation to each page.

set -euo pipefail

WEB_URL="${WEB_URL:-http://localhost:3000}"
MAX_WAIT_SECS="${WARMUP_MAX_WAIT:-60}"

# Routes to warm. Add new ones here when adding new pages.
ROUTES=(
  /
  /runs
  /agents
  /tasks
  /compare
  /evals
  /company-agent
  /login
  /register
)

# 1. Wait until the web server actually responds (don't curl into the void)
echo "[warmup] waiting for $WEB_URL ..."
waited=0
until curl -fsS -o /dev/null "$WEB_URL/" 2>/dev/null; do
  sleep 1
  waited=$((waited + 1))
  if [ "$waited" -ge "$MAX_WAIT_SECS" ]; then
    echo "[warmup] gave up after ${MAX_WAIT_SECS}s — web server not responding" >&2
    exit 0  # don't kill the parent dev.sh; just bail
  fi
done

# 2. Hit each route, suppressing output. Failures are non-fatal (auth pages
# may 401, dynamic pages may 404 — that's still enough to trigger compile).
echo "[warmup] pre-compiling ${#ROUTES[@]} routes ..."
for route in "${ROUTES[@]}"; do
  start=$(date +%s)
  curl -fsS -o /dev/null "$WEB_URL$route" 2>/dev/null || true
  elapsed=$(( $(date +%s) - start ))
  printf "[warmup] %-20s %ds\n" "$route" "$elapsed"
done
echo "[warmup] ✓ done — first-visit Compiling toast should now be absent for these routes"
