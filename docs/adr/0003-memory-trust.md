# 3. Committed memory is trusted the way repo CLAUDE.md is

Status: superseded by ADR 0017 (memory removed, 2026-10-20)

Team memory in `.seen/memory/` is injected automatically and its `verified_at` is the trust signal,
as the plan intends (PR review is the control). Mitigations: injected as delimited data with an
instruction not to follow it for permissions or data; control characters stripped; front matter
validated; CODEOWNERS on `.seen/memory/` recommended. Open owner decision: per-repo opt-in before
injecting memory from newly cloned repos.
