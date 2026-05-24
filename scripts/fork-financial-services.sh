#!/usr/bin/env bash
# Fork selected markdown from anthropics/financial-services into uteki's
# skills tree. Idempotent — re-running overwrites local copies (the loader
# stamps SHA so evolution store auto-bumps to a new version when content
# changes).
#
# Requires `gh` (GitHub CLI) authenticated. License compliance lives in
# THIRD_PARTY_NOTICES.md at the repo root.

set -euo pipefail

REPO="anthropics/financial-services"
COMMIT="96bc9615bccdff61c190cc3e29687f5885bc3929"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SKILLS="$ROOT/services/api/src/uteki_api/skills"

mappings=(
  # research (market-researcher)
  "plugins/agent-plugins/market-researcher/agents/market-researcher.md|research/SKILL.md"
  "plugins/agent-plugins/market-researcher/skills/sector-overview/SKILL.md|research/references/sector-overview.md"
  "plugins/agent-plugins/market-researcher/skills/competitive-analysis/SKILL.md|research/references/competitive-analysis.md"
  "plugins/agent-plugins/market-researcher/skills/comps-analysis/SKILL.md|research/references/comps-analysis.md"
  "plugins/agent-plugins/market-researcher/skills/idea-generation/SKILL.md|research/references/idea-generation.md"

  # earnings (earnings-reviewer) — Excel sub-skills excluded
  "plugins/agent-plugins/earnings-reviewer/agents/earnings-reviewer.md|earnings/SKILL.md"
  "plugins/agent-plugins/earnings-reviewer/skills/earnings-analysis/SKILL.md|earnings/references/earnings-analysis.md"
  "plugins/agent-plugins/earnings-reviewer/skills/morning-note/SKILL.md|earnings/references/morning-note.md"
  "plugins/agent-plugins/earnings-reviewer/skills/earnings-preview/SKILL.md|earnings/references/earnings-preview.md"
)

count=0
for entry in "${mappings[@]}"; do
  src="${entry%%|*}"
  dst="${entry##*|}"
  out="$SKILLS/$dst"
  mkdir -p "$(dirname "$out")"

  # Fetch raw markdown (base64) → decode
  raw=$(gh api "repos/$REPO/contents/$src?ref=$COMMIT" \
    --jq '.content' | tr -d '\n' | base64 --decode)

  # Stamp fork header
  {
    echo "<!--"
    echo "Adapted from $REPO@$COMMIT · Apache-2.0"
    echo "Source: $src"
    echo "Local modifications: shared guardrails + Chinese addendum are"
    echo "prepended/appended by skills/loader.py at runtime, not inlined here."
    echo "Editing this file directly is allowed; the skill loader hashes"
    echo "content and the evolution store auto-bumps the version."
    echo "-->"
    echo
    echo "$raw"
  } > "$out"

  count=$((count + 1))
  echo "  ✓ $dst"
done

echo
echo "Forked $count markdown files from $REPO@${COMMIT:0:7}"
echo "Next: restart api · evolution store will auto-bump affected skills"
