---
id: hook-hot-path-stdlib
type: convention
file_ref: packages/core/src/seen_core/hook.py
source_change:
verified_at:
---
The hook hot path is stdlib only: no network, no SQLite writes, no heavy imports. tests/pii/test_ner.py enforces the import list; heavy work goes in ingest at Stop.
