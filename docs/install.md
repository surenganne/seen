# Install and upgrade

The short version is in the [README](../README.md#install). Seen is not on PyPI yet; the CLI and the plugin install
straight from GitHub.

## Upgrade

Upgrade the CLI and the plugin together:

```bash
seen upgrade --check          # versions, skew warnings, and the commands it would run
seen upgrade --yes            # reinstall the CLI from where it came from, then update the plugin
seen version                  # every piece's version and the ledger schema
```

Then restart Claude Code. `seen doctor` also warns when the plugin, the `seen-hook` binary or the ledger schema
disagree with the CLI, and when a newer release tag exists on GitHub (one anonymous GET; opt out with
`SEEN_NO_UPDATE_CHECK=1`). Inside Claude Code, `/seen:upgrade` does the check and asks before upgrading.

## Enable it for a whole team

Put this in the repo's `.claude/settings.json`; Claude Code installs the plugin after a contributor accepts the
workspace trust dialog:

```json
{
  "extraKnownMarketplaces": { "seen-tools": { "source": { "source": "github", "repo": "surenganne/seen" } } },
  "enabledPlugins": { "seen@seen-tools": true }
}
```

## More commands

```bash
seen skills scan | list
seen import --dry-run                    # past sessions from Claude Code transcripts (before the plugin was installed)
seen purge --before 2026-01-01           # report what would be erased; add --yes to erase (DPDP)
seen audit export --format csv --from 2026-10-01 --to 2026-10-31
```
