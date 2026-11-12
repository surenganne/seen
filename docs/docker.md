# Docker

Hooks and the CLI run on the host (that is where Claude Code and your repos are). Docker runs the dashboard, the test
suites and the team server. Ports avoid the common defaults.

| Command | What | URL |
|---|---|---|
| `seen docker-sync && docker compose up -d --build` | Dashboard on a snapshot of your real `~/.seen` | http://127.0.0.1:47821 |
| `seen docker-sync --watch 300 --restart` (host) | Keep the container near-live: snapshot every 5 minutes, then restart the dashboard | |
| `docker compose --profile dev up -d` | Plus the Vite dev server with hot reload | http://127.0.0.1:47822 |
| (host dashboard) | The container never opens the live ledger: SQLite WAL locking does not cross the Docker Desktop VM | |
| `docker compose --profile test run --rm tests` | Python lint, types and unit tests | |
| `docker compose --profile test run --rm e2e` | Playwright against a throwaway, freshly seeded test database (tmpfs) | |

The Docker dashboard needs nothing on the host except the CLI (`seen docker-sync`); the image builds the UI itself.
The copy is a snapshot: it is as old as the last `seen docker-sync`, and settings or approvals changed there are lost
on refresh. The team server has its own compose file; see [team-server.md](team-server.md).

Development data never touches your real ledger: `seen dev-seed` only writes into an explicit scratch `SEEN_HOME`,
every test gets its own temporary one, and the team test suite uses a separate `seen_team_test` database.

## Dashboard run modes

| | Command | URL | Data |
|---|---|---|---|
| **On the host** (recommended) | `SEEN_WEB_DIST=$PWD/web/dist seen serve --port 47825 --open` | http://127.0.0.1:47825 | Your real `~/.seen`, live |
| From a clone | `uv run seen serve --open` (finds `web/dist` itself; default port 47821) | http://127.0.0.1:47821 | Your real `~/.seen`, live |
| In Docker | `seen docker-sync && docker compose up -d --build` | http://127.0.0.1:47821 | A snapshot of `~/.seen` |
| UI development | `docker compose --profile dev up -d` | http://127.0.0.1:47822 | The Docker dashboard's data, with hot reload |
