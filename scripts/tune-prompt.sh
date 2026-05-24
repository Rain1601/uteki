#!/usr/bin/env bash
# tune-prompt.sh — interactive prompt-tuning loop.
#
# Workflow:
#   1. Capture baseline `/api/eval/run` results
#   2. Open the named SKILL.md (or any prompt markdown) in $EDITOR
#   3. Hot-reload the skill via /api/admin/reload-skills
#   4. Re-run eval; show baseline vs new
#   5. Ask: keep / rollback
#
# Requires the API to be running on http://localhost:8000.
# Set EVAL_TIMEOUT (default 600s) for the long pipeline cases.

set -euo pipefail

PATH_MD="${1:?usage: tune-prompt.sh <path/to/SKILL.md>}"
API="${UTEKI_API_URL:-http://localhost:8000}"
TIMEOUT="${EVAL_TIMEOUT:-600}"

if [[ ! -f "$PATH_MD" ]]; then
  echo "error: file not found: $PATH_MD" >&2
  exit 1
fi

if ! curl -fs "$API/health" >/dev/null; then
  echo "error: API not reachable at $API; start with 'make api'" >&2
  exit 1
fi

print_summary() {
  python3 -c '
import json, sys
r = json.load(sys.stdin)
print(f"  pass_rate: {r[\"pass_rate\"]*100:.0f}%  ({len(r[\"results\"])} cases, {r[\"duration_ms\"]} ms)")
for x in r["results"]:
    flag = "✓" if x["passed"] else "✗"
    print(f"    {flag} {x[\"case_id\"]:30s}  sub={x[\"scores\"][\"substring\"]*100:.0f}%  tool={x[\"scores\"][\"tool\"]*100:.0f}%")
'
}

echo "── baseline (pre-edit) ──"
curl -s -X POST "$API/api/eval/run" --max-time "$TIMEOUT" | print_summary

echo
echo "→ opening editor on $PATH_MD ..."
cp "$PATH_MD" "$PATH_MD.bak"
"${EDITOR:-vi}" "$PATH_MD"

echo
echo "→ reloading skills (POST $API/api/admin/reload-skills) ..."
curl -s -X POST "$API/api/admin/reload-skills" | python3 -c 'import json,sys;r=json.load(sys.stdin);print(f"  reloaded {r[\"count\"]} skills: {r[\"cleared\"]}")'

echo
echo "── new (post-edit) ──"
curl -s -X POST "$API/api/eval/run" --max-time "$TIMEOUT" | print_summary

echo
read -rp "Decision? (keep / rollback / quit): " DECISION
case "$DECISION" in
  keep|k)
    rm "$PATH_MD.bak"
    echo "✓ kept new prompt; backup discarded"
    ;;
  rollback|r)
    mv "$PATH_MD.bak" "$PATH_MD"
    curl -s -X POST "$API/api/admin/reload-skills" >/dev/null
    echo "↶ rolled back; skills reloaded"
    ;;
  *)
    echo "left $PATH_MD.bak in place; no reload"
    ;;
esac
