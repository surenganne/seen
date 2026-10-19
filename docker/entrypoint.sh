#!/bin/sh
# Serve on 0.0.0.0 inside the container. Compose publishes the port on 127.0.0.1 only; the API has no login.
# SEEN_HOME is a snapshot of the real ~/.seen made by `seen docker-sync` (ADR 0011). Mock data is seeded only
# when SEEN_DEV_SEED=1 (the throwaway test stacks).
set -e
if [ "${SEEN_DEV_SEED:-0}" = "1" ]; then
  [ -f "$SEEN_HOME/ledger.db" ] || seen dev-seed --home "$SEEN_HOME"
elif [ ! -f "$SEEN_HOME/ledger.db" ]; then
  echo "No snapshot at $SEEN_HOME. Run 'seen docker-sync' on the host, then restart this container." >&2
  exit 1
fi
exec seen serve --host 0.0.0.0 --port 47821 --allow-remote
