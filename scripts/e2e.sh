#!/usr/bin/env bash
# E2E suite runner — one command, observable per-chain output.
#
#   ./scripts/e2e.sh                  # full suite, structured trace + pass/fail
#   ./scripts/e2e.sh -k auth          # only the auth chain
#   ./scripts/e2e.sh -k pipeline -x   # pipeline chain, stop on first fail
#
# Outputs each chain's trace (▶ section / · event / ✓✗ check / kv pairs)
# even when tests fail, so iteration loops know exactly where the chain
# broke before the assertion fired.
set -euo pipefail

cd "$(dirname "$0")/.."

# Mock LLM + auth-required by default. Override per invocation if
# someone wants a real-LLM smoke run.
export UTEKI_USE_MOCK_LLM="${UTEKI_USE_MOCK_LLM:-true}"
export UTEKI_AUTH_REQUIRED="${UTEKI_AUTH_REQUIRED:-true}"

cd services/api

# -s   : show prints (the Reporter trace)
# -v   : test names, not dots
# --tb=short : compact tracebacks
# -p no:cacheprovider : keeps the cache from leaking between runs
uv run pytest tests/e2e \
  -s -v --tb=short \
  -p no:cacheprovider \
  "$@"
