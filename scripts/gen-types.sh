#!/usr/bin/env bash
set -euo pipefail

# Pull OpenAPI schema from the running api and regenerate TS types.
# Requires api to be reachable at $UTEKI_API_URL (default http://localhost:8000).

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
exec bash "$ROOT/packages/shared-types/scripts/generate.sh"
