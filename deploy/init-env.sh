#!/bin/sh
# Generate deploy/.env with random secrets (never committed). Re-run with --force to rotate.
set -e
cd "$(dirname "$0")"
if [ -f .env ] && [ "$1" != "--force" ]; then echo "deploy/.env exists (use --force to rotate)"; exit 0; fi
rand() { python3 -c "import secrets;print(secrets.token_urlsafe(32))"; }
umask 077
cat > .env <<ENV
SEEN_TEAM_DB_PASSWORD=$(rand)
SEEN_TEAM_BOOTSTRAP_KEY=$(rand)
ENV
echo "wrote deploy/.env (0600). The bootstrap admin key is in it: keep it out of chat and tickets."
