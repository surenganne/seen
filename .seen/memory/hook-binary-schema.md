---
id: hook-binary-schema
type: gotcha
file_ref:
source_change:
verified_at:
---
The installed seen-hook must be at least as new as the ledger schema. An older one fails open and records nothing (hook.log: Can't locate revision), so reinstall the CLI after adding a migration (ADR 0007).
