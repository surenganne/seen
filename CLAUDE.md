# Seen: working rules

- Read docs/plan/SEEN_BUILD_PLAN.md (the plan; kept locally, not in the public repo). Work one task at a time, in order. Name the task ID in each commit.
- Do not guess Claude Code behaviour. Use recorded fixtures in tests/fixtures (see docs/hooks-findings.md). If a fact is missing, write a spike first (spikes/).
- Hooks must fail open. Only the blocked-skill check, PII block mode and the optional policy enforcement may exit non-zero.
- The hook hot path uses the Python standard library only. No network, no SQLite writes, no heavy imports (tests/pii/test_ner.py enforces the import list).
- Never store or sync prompts or diffs on any server. Redact home directory paths.
- Never write a PII value, secret, prompt text or command argument to the audit trail, the ledger findings, logs or any sync payload. Use type, count, hash or fingerprint.
- Never UPDATE or DELETE audit rows. Corrections are new events.
- Never show a bare "no PII" or "clean" label. Say what was checked.
- Never hardcode prices. Read pricing/prices.json.
- Write the test first for parsers and algorithms. Keep PRs small.
- When something in the plan is wrong or unclear, stop, write a short note in docs/adr/, and ask the owner.

## This repo

- `SEEN_HOME` overrides `~/.seen` everywhere. Tests get a tmp one automatically (tests/conftest.py); dev uses a scratch dir. `seen dev-seed` refuses `~/.seen`.
- Ports avoid common defaults: 47821 dashboard/API, 47822 Vite dev, 47823 team Postgres, 47824 team server, 47825 real-data dashboard on the host, 47831/47832 local e2e servers.
- Repo files (.seen/*, .claude/*, git config) are untrusted input: write through `seen_core.safeio`, run git through `seen_core.gitutil`, never follow symlinks out of the repo.
- The installed `seen-hook` must be at least as new as the ledger schema. An older one fails open and records nothing (hook.log: Can't locate revision), so reinstall the CLI after adding a migration.
- Gates: `uv run ruff check . && uv run mypy packages/core/src && uv run pytest` (real-Claude e2e is opt-in: `uv run pytest -m e2e tests/e2e`), `uv run python scripts/pii_benchmark.py --check`, `uv run python scripts/gen_openapi.py --check`; web: `npm run lint && npm run typecheck && npm test && npm run check:api && npx playwright test`.
- After changing an API route or schema: `uv run python scripts/gen_openapi.py && (cd web && npm run gen:api)`, and `uv run python scripts/capture_web_fixtures.py` if a page's response shape changed (the page unit tests read `web/src/test/fixtures.json`).
- Repo: https://github.com/surenganne/seen (CI: .github/workflows/ci.yml). Install hints point at `uv tool install git+https://github.com/surenganne/seen#subdirectory=packages/cli` until seen-cli is on PyPI.
- UI follows DESIGN.md and PRODUCT.md: tokens only from web/src/styles/tokens.css (OKLCH, WCAG 2.2 AA in light and dark), IBM Plex Sans/Mono, lucide icons, no side stripes or eyebrows. Keep test ids and accessible names stable; the manual check list is docs/TESTING.md.
- Settings edits `[sync]` (server, on/off, what is sent) through `PUT /api/settings`; a dashboard in remote mode (`--allow-remote` or a non-loopback bind) refuses sync changes with 403, because `sync.server` decides where the key goes. SSO is configured on the team server by environment variables and is only displayed in the UI (`GET /api/team/sso`, ADR 0018).
- Team server tests: `tests/team/conftest.py` disposes every engine a test creates; the Postgres suite runs with `SEEN_TEAM_TEST_URL` (docs/TESTING.md Part 14). The team Postgres host port is `SEEN_TEAM_PG_PORT` (default 47823).
- The dashboard calls the team server only when `sync.server` is set; `seen team login` stores a key at `~/.seen/team_key` (0600, never synced, never in the Docker snapshot). The key never reaches the browser: the local API proxies team calls (ADR 0019).
