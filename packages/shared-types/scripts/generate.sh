#!/usr/bin/env bash
set -euo pipefail

API_URL="${UTEKI_API_URL:-http://localhost:8000}/openapi.json"
OUT="$(cd "$(dirname "$0")/.." && pwd)/src/index.ts"

echo "→ Pulling OpenAPI schema from $API_URL"
npx --yes openapi-typescript "$API_URL" --output "$OUT"
echo "✓ Generated $OUT"
