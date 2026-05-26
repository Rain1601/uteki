#!/usr/bin/env bash
# Launch uteki MCP server (stdio) for Claude Code.
#
# Wire this into Claude Code with:
#   claude mcp add uteki -- /absolute/path/to/uteki/scripts/uteki-mcp.sh
#
# Then in any CC session you'll see tools: uteki_list_skills,
# uteki_run_skill, uteki_get_run, uteki_list_artifacts, uteki_read_artifact.
#
# Prerequisite: the uteki HTTP API must be running at
# ${UTEKI_API_BASE:-http://localhost:8000} with UTEKI_AUTH_REQUIRED=false
# (the MCP server uses the demo@local anonymous fallback for now).
#
# Override UTEKI_API_BASE in the environment of this script if the API is
# on a non-default port/host.
set -euo pipefail
cd "$(dirname "$0")/.."
exec uv run --directory services/api python -m uteki_api.mcp
