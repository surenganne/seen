# 0013: One upgrade command for the CLI and the plugin

Status: accepted, 2026-10-19 (owner: "build 1 to 6 now, tests first").

Problem: Seen is two installs, the CLI and `seen-hook` (uv tool) and the plugin shim (Claude Code). A hook older than
the ledger schema fails open and records nothing (ADR 0007), and nothing kept the versions equal.

Decision:
- One version: `brand.VERSION` is the reference; `tests/test_versions.py` fails if any `pyproject.toml` or
  `plugin.json` differs; `scripts/bump_version.py` changes them together.
- `seen version` and the `seen doctor` skew checks compare plugin, `seen-hook` (read through its own interpreter) and
  ledger schema against the CLI. A ledger revision this CLI does not know is reported as "newer".
- `seen upgrade` reports by default; `--yes` reinstalls from the place `uv tool` recorded (a folder or a git URL),
  then runs `claude plugin marketplace update` and `claude plugin update`. It refuses when the ledger or audit
  chain is unhealthy, runs argv lists (no shell), stops at the first failed step, and rejects a source starting
  with `-`.
- `/seen:upgrade` may only run `seen version` and `seen upgrade --check` unprompted; the real upgrade goes through
  the normal permission prompt.
- Update notice: `seen doctor` and `seen upgrade` read the highest `vX.Y.Z` tag from the GitHub tags API (one
  anonymous GET, 3 s timeout, silent on failure). `SEEN_NO_UPDATE_CHECK=1` turns it off; tests set it. It never
  runs in a hook.

Consequences: no release exists until a `vX.Y.Z` tag is pushed (docs/RELEASING.md). Plugin changes need a restart of
Claude Code. The Docker image is rebuilt separately.
