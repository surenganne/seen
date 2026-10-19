<p align="center"><img src="assets/brand/eyes.svg" width="112" alt="Seen"></p>

# Seen

[![ci](https://github.com/surenganne/seen/actions/workflows/ci.yml/badge.svg)](https://github.com/surenganne/seen/actions/workflows/ci.yml)

**Nothing your agents do goes unseen.** A Claude Code plugin and local dashboard that keeps a per-project
ledger of what AI agents change: files and lines, tokens and API-equivalent cost, memory loaded, skills run
(with versions and approvals), required-skill rules, PII exposure, and a tamper-evident audit trail.

Local first: everything works with no server. Prompts and diffs never leave the machine.

## What it records, per agent turn

| | |
|---|---|
| Changes | Files touched and lines added/removed, reconciled to git |
| Cost | Input, output, cache read and write tokens (exact, from the transcript) and API-equivalent cost from `pricing/prices.json` |
| Memory | Which `.seen/memory` items were in context; edits are paused if memory failed to load |
| Skills | Every skill that ran, its version hash, trigger, and approval status at that moment |
| Rules | `.seen/policies.yaml`: "changes to `llm/**` must run `phi-redaction-check`" (report or enforce) |
| PII | Types and counts of personal data and secrets that reached the model, the network or the repo, and from where. Never the values |
| Audit | Append-only, hash-chained events. `seen audit verify` finds the first edited, deleted or reordered row |

## Architecture

![Seen architecture: hooks write to a local ledger; the host dashboard reads it live, the Docker dashboard reads a snapshot, the team server is opt-in](docs/architecture.svg)

Hooks never touch the network or write SQLite: they append to a spool file and ingest folds it into the ledger
and the hash-chained audit database when the turn stops. The host dashboard reads `~/.seen` live. A container
cannot safely share SQLite WAL files with the host, so the Docker dashboard serves a snapshot made by
`seen docker-sync` ([ADR 0011](docs/adr/0011-real-data-snapshot-in-docker.md)). The team server only ever
receives metadata, and only when you switch sync on. Source: [docs/architecture.html](docs/architecture.html).

## Install

Seen is not on PyPI yet; install the CLI and the plugin straight from GitHub.

```bash
# 1. CLI and the seen-hook binary (Python 3.11+, uv)
uv tool install "git+https://github.com/surenganne/seen#subdirectory=packages/cli"

# 2. Claude Code plugin (marketplace "seen-tools" lives in this repo)
claude plugin marketplace add surenganne/seen
claude plugin install seen@seen-tools

# 3. Per repo
cd your-repo && seen init          # .seen/ folder + memory write permissions
seen doctor                        # checks Python, hooks, plugin, databases, PATH
```

Upgrade the CLI and the plugin together:

```bash
seen upgrade --check          # versions, skew warnings, and the commands it would run
seen upgrade --yes            # reinstall the CLI from where it came from, then update the plugin
seen version                  # every piece's version and the ledger schema
```

Then restart Claude Code. `seen doctor` also warns when the plugin, the `seen-hook` binary or the ledger schema
disagree with the CLI, and when a newer release tag exists on GitHub (one anonymous GET; opt out with
`SEEN_NO_UPDATE_CHECK=1`). Inside Claude Code, `/seen:upgrade` does the check and asks before upgrading
([ADR 0013](docs/adr/0013-upgrade-flow.md)).

Teams can enable it for everyone from the repo's `.claude/settings.json`; Claude Code installs it after a
contributor accepts the workspace trust dialog:

```json
{
  "extraKnownMarketplaces": { "seen-tools": { "source": { "source": "github", "repo": "surenganne/seen" } } },
  "enabledPlugins": { "seen@seen-tools": true }
}
```

## Use

```bash
seen report --days 7          # what changed, what it cost, which skills ran
seen serve --open             # dashboard on http://127.0.0.1:47821 (from a clone; see below)
seen memory add --id refund-idempotency --type decision --file-ref src/payments/refund.py \
  --text "Refunds carry an idempotency key; retries reuse it."
seen memory list | verify <id> | archive <id>
seen skills scan | list
seen import --dry-run         # past sessions from Claude Code transcripts (before the plugin was installed)
seen audit verify
seen purge --before 2026-01-01      # report what would be erased; add --yes to erase (DPDP)
seen docker-sync --watch 300 --restart   # keep the Docker dashboard's copy of ~/.seen fresh
seen audit export --format csv --from 2026-10-01 --to 2026-10-31
```

## Docker

Hooks and the CLI run on the host (that is where Claude Code and your repos are). Docker runs the dashboard,
the test suites and the team server. Ports avoid the common defaults.

| Command | What | URL |
|---|---|---|
| `seen docker-sync && docker compose up -d --build` | Dashboard on a snapshot of your real `~/.seen` ([ADR 0011](docs/adr/0011-real-data-snapshot-in-docker.md)) | http://127.0.0.1:47821 |
| `seen docker-sync --watch 300 --restart` (host) | Keep the container near-live: snapshot every 5 minutes, then restart the dashboard | |
| `docker compose --profile dev up -d` | Plus the Vite dev server with hot reload | http://127.0.0.1:47822 |
| `SEEN_WEB_DIST=$PWD/web/dist seen serve --port 47825 --open` (on the host, not Docker) | Live (not snapshot) dashboard on your real `~/.seen`. The container never opens the live ledger: SQLite WAL locking does not cross the Docker Desktop VM ([ADR 0008](docs/adr/0008-real-data-dashboard-on-host.md)) | http://127.0.0.1:47825 |
| `docker compose --profile test run --rm tests` | Python lint, types and unit tests | |
| `docker compose --profile test run --rm e2e` | Playwright against a throwaway, freshly seeded test database (tmpfs) | |
| `sh deploy/init-env.sh` then `docker compose -f deploy/docker-compose.team.yml --env-file deploy/.env up -d` | Team server (Phase 5 skeleton) and Postgres | http://127.0.0.1:47824, Postgres on 47823 |

Development data never touches your real ledger: `seen dev-seed` only writes into an explicit scratch
`SEEN_HOME`, every test gets its own temporary one, and the team test suite uses a separate
`seen_team_test` database.

The dashboard UI ships as a built bundle. From a `uv tool` install, point Seen at one:
`git clone https://github.com/surenganne/seen && (cd seen/web && npm ci && npm run build)`, then
`SEEN_WEB_DIST=$PWD/seen/web/dist seen serve --open`. Or use the Docker dashboard below, which needs nothing on the host.

## Develop

```bash
git clone https://github.com/surenganne/seen && cd seen
uv sync && (cd web && npm ci)
uv run pytest                                  # unit + integration (fast, no network)
uv run pytest -m e2e tests/e2e                 # real headless Claude Code sessions (costs a few cents)
(cd web && npx playwright test)                # browser e2e, desktop and phone, CSP-violation guard
uv run python scripts/pii_benchmark.py         # regenerates docs/pii-benchmark.md
```

Phase 0 findings about Claude Code hooks are in [docs/hooks-findings.md](docs/hooks-findings.md); every parser
is tested against payloads and transcripts recorded from real sessions (`tests/fixtures`). CI runs Python
lint/types/tests, the web checks, Playwright and the Docker suites on every push.

## Docs

| | |
|---|---|
| [docs/TESTING.md](docs/TESTING.md) | Step-by-step guide to check every feature by hand |
| [DESIGN.md](DESIGN.md) / [PRODUCT.md](PRODUCT.md) | Dashboard design system and who it is for |
| [docs/schema.md](docs/schema.md) | Where every piece of data lives |
| [docs/architecture.html](docs/architecture.html) | Architecture diagram (also `.svg` and `.png`) |
| [docs/adr/](docs/adr) | Architecture decisions |
| [docs/RELEASING.md](docs/RELEASING.md) | How to cut a release and what `seen upgrade` relies on |
| [docs/pii-benchmark.md](docs/pii-benchmark.md) | Detector precision and recall on the labelled corpus |
| [docs/plan/SEEN_BUILD_PLAN.md](docs/plan/SEEN_BUILD_PLAN.md) | The build plan; progress in [docs/build-ledger.md](docs/build-ledger.md) |

Issues and pull requests: <https://github.com/surenganne/seen>.

## Limits, stated plainly

- **Tamper-evident, not tamper-proof.** Someone with write access to this machine can rebuild the audit chain.
  It catches bugs, partial edits and clumsy tampering. Anchoring chain heads on a team server (`seen sync`)
  makes rewriting local history detectable.
- **Coverage.** Only sessions where the plugin ran are recorded; gaps are recorded as `capture.gap` and
  `session.incomplete`. Enable the plugin through managed settings for whole teams.
- **PII detection** finds structured identifiers (Aadhaar, PAN, cards, IBAN, email, phone, UPI, DOB, GSTIN,
  secrets…). It misses names, addresses and free-text health details unless the optional Presidio tier is on.
  Seen shows exposure; it cannot un-send what already reached the model provider. It is evidence for a
  privacy review, not a compliance control, and makes no claim about DPDP, GDPR or HIPAA compliance.
- **Cost** is an API-equivalent estimate from a price table marked unverified until the owner confirms it.
- **Memory** is text the model treats as guidance. Review `.seen/memory/` like code (a CODEOWNERS rule helps)
  and never store secrets or client data there.
