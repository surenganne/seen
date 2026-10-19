---
id: hooks-fail-open
type: convention
file_ref: packages/core/src/seen_core/hook.py
source_change:
verified_at: 2026-10-19T05:32:45.170Z
---
Hooks must fail open: only the memory gate, blocked-skill check, PII block mode and policy enforce may exit non-zero.
