# Contributing

Issues and pull requests are welcome at <https://github.com/surenganne/seen>. Read [CLAUDE.md](CLAUDE.md) for the
working rules (hooks fail open, never store prompts or PII values, tests first for parsers).

```bash
git clone https://github.com/surenganne/seen && cd seen
uv sync && (cd web && npm ci)
uv run pytest                                  # unit + integration (fast, no network)
uv run pytest -m e2e tests/e2e                 # real headless Claude Code sessions (costs a few cents)
(cd web && npx playwright test)                # browser e2e, desktop and phone, CSP-violation guard
uv run python scripts/pii_benchmark.py         # regenerates docs/pii-benchmark.md
```

Findings about Claude Code hook behaviour are in [docs/hooks-findings.md](docs/hooks-findings.md); every parser is
tested against payloads and transcripts recorded from real sessions (`tests/fixtures`). CI runs Python lint/types/tests,
the web checks, Playwright and the Docker suites on every push. A manual check list is in
[docs/TESTING.md](docs/TESTING.md).

Releases: [docs/RELEASING.md](docs/RELEASING.md). Build progress is in [docs/build-ledger.md](docs/build-ledger.md).
