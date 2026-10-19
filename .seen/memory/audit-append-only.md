---
id: audit-append-only
type: convention
file_ref: packages/core/src/seen_core/audit.py
source_change:
verified_at:
---
Never UPDATE or DELETE audit rows; a correction is a new event.
