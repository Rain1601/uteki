#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if ! command -v uv >/dev/null 2>&1; then
  echo "✗ uv 未安装。装一下：curl -LsSf https://astral.sh/uv/install.sh | sh" >&2
  exit 1
fi

API_CMD="cd $ROOT/services/api && uv run uvicorn uteki_api.main:app --reload --port 8000"
WEB_CMD="cd $ROOT && pnpm --filter @uteki/web dev"

echo "→ Starting api (8000) and web (3000) in parallel..."
echo "  按 Ctrl-C 同时停止两者"

trap 'kill 0' INT TERM EXIT

bash -c "$API_CMD" &
API_PID=$!
bash -c "$WEB_CMD" &
WEB_PID=$!

# Background warm-up: pre-compile all routes so the first browser visit
# to each page doesn't show Next's "Compiling..." toast. Opt out with
# WARMUP=0. The script waits for :3000 to respond before hitting routes.
if [ "${WARMUP:-1}" = "1" ]; then
  bash "$ROOT/scripts/warmup.sh" &
fi

wait $API_PID $WEB_PID
