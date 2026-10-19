---
id: repo-files-untrusted
type: convention
file_ref: packages/core/src/seen_core/safeio.py
source_change:
verified_at:
---
Repo files (.seen/*, .claude/*, git config) are untrusted: write through seen_core.safeio, run git through seen_core.gitutil, never follow symlinks out of the repo.
