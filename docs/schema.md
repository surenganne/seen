# Data layout

| Store | File | Written by | Notes |
|---|---|---|---|
| Spool | `~/.seen/spool/<session>.jsonl` | hooks (append) | One JSON line per hook event. Prompt stored only redacted (or not at all). |
| Snapshots | `~/.seen/snap/<session>.json`, `.state.json` | hooks | Git before-snapshot of the current turn; repo root and project id of the session. |
| Ledger | `~/.seen/ledger.db` (SQLite, WAL, 0600) | ingest at Stop, local API writes | Tables in plan section 8; migrations in `packages/core/src/seen_core/db/alembic`. |
| Audit | `~/.seen/audit.db` (SQLite, 0600) | ingest, CLI and API writes | Append-only hash chain; triggers abort UPDATE/DELETE. Separate file so ledger rebuilds can't touch it. |
| Heads | `~/.seen/audit-heads.log` | session end | Catches tail truncation; sent to the team server as anchors. |
| Key | `~/.seen/secret.key` (0600) | first use | Keys PII fingerprints, prompt HMACs and actor ids. Never synced. |
| Inventory | `~/.seen/cache/inventory-<project>.json` | background scan at session start | Skill ids, kinds, hashes. |
| Config | `~/.seen/config.toml` | user, Settings page | Defaults in `seen_core/config.py`. |
| Rules | `<repo>/.seen/policies.yaml`, `pii.yaml`, `skills.lock.json` | people, dashboard | Committed. |

## Ledger additions beyond plan section 8

- `skill_invocations.status`: approval status at the moment the skill ran (P4-3).
- `policies.id` is `<project_id>:<policy id>` so two repos can both use `pol-auth`.

## Audit event catalogue

Plan section 11A, plus `pii.allowlisted` (counts of values or paths a repo allowlist suppressed). `turn.start` carries `prompt_hmac` (keyed), not a plain SHA-256.
