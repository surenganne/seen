#!/bin/sh
# Seed mock data on first start when SEEN_DEV_SEED=1, then serve on 0.0.0.0 inside the container.
# Compose publishes the port on 127.0.0.1 only; the API has no login.
set -e
if [ "${SEEN_DEV_SEED:-0}" = "1" ] && [ ! -f "$SEEN_HOME/ledger.db" ]; then
  seen dev-seed --home "$SEEN_HOME"
fi
exec seen serve --host 0.0.0.0 --port 47821 --allow-remote
