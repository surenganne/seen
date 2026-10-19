---
id: non-repo-sessions-untracked
type: decision
file_ref: packages/core/src/seen_core/spool.py
source_change:
verified_at:
---
Sessions that start outside a git repo record nothing (spool.append skips them), but PII block mode still blocks there (ADR 0009).
