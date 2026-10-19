---
description: Check for a Seen update and, once you confirm, upgrade the CLI and plugin together
allowed-tools: Bash(seen version:*), Bash(seen upgrade --check:*)
---
Run `seen version` and `seen upgrade --check` and summarise: current versions, whether a newer release exists, and any `!!` skew lines (for example a hook older than the ledger schema, which records nothing).

If an upgrade is needed, show the commands under "Would run" and ask the user whether to go ahead. Only after they say yes, run `seen upgrade --yes` (the permission prompt is the second confirmation). Afterwards tell them to restart Claude Code and run `seen doctor`. If `seen` is not installed, say: install it with `uv tool install git+https://github.com/surenganne/seen#subdirectory=packages/cli`.
