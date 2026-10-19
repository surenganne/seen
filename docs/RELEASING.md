# Releasing Seen

`seen upgrade` and `seen doctor` rely on three things staying true: one version everywhere, `vX.Y.Z` git tags, and
migrations that are called out. Skipping any of them leaves users with a hook older than their ledger, which fails
open and records nothing.

1. **Pick the version** (`X.Y.Z`, no suffix). A new Alembic migration needs at least a minor bump.
2. **Bump everywhere**: `uv run python scripts/bump_version.py X.Y.Z`. It sets `brand.py`, every `pyproject.toml`
   and `plugin/.claude-plugin/plugin.json`, then runs `uv lock`. `tests/test_versions.py` fails CI if any of them
   disagree.
3. **Write the changelog** entry in `CHANGELOG.md`. Say when a migration is included and that users must run
   `seen upgrade`.
4. **Run the gates** from `CLAUDE.md` (ruff, mypy, pytest, `pii_benchmark.py --check`, `gen_openapi.py --check`, web
   checks, Playwright).
5. **Commit, then tag**: `git tag vX.Y.Z && git push origin main vX.Y.Z`. `seen doctor` and `seen upgrade` compare
   against the highest `vX.Y.Z` tag on GitHub, so a release without a tag is invisible to them.
6. **Check an upgrade by hand** on a machine with the previous version: `seen upgrade --check`, then `--yes`, restart
   Claude Code, `seen doctor` all ok (see TESTING.md Part 15).
7. **Docker users** rebuild the dashboard image: `seen docker-sync && docker compose up -d --build`.

The plugin directory is installed by Claude Code from this repo's marketplace (`seen-tools`); a changed plugin
version is what makes `claude plugin update seen@seen-tools` pick up new commands and hooks.
