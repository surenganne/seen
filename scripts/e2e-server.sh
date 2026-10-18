#!/bin/sh
# Seed a fresh scratch SEEN_HOME, build the web app, serve both on $1 (default 47831).
set -e
PORT=${1:-47831}
ROOT=$(cd "$(dirname "$0")/.." && pwd)
HOME_DIR=$(mktemp -d "${TMPDIR:-/tmp}/seen-e2e.XXXXXX")
cd "$ROOT/web" && npm run build >/dev/null
cd "$ROOT" && SEEN_HOME="$HOME_DIR" uv run seen dev-seed --home "$HOME_DIR" >/dev/null
SEEN_HOME="$HOME_DIR" SEEN_WEB_DIST="$ROOT/web/dist" exec uv run seen serve --port "$PORT"
