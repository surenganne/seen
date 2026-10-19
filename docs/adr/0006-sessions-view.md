# 0006: Sessions view (owner request, outside the plan)

Status: accepted, 2026-10-19

The owner asked to see active sessions and all session activity. The plan has no sessions page, but the data already
exists: `sessions` rows in the ledger and per-session audit events (`session.*`, `turn.*`, `tool.call` from the
`PostToolUse *` hook, `file.changed`, `skill.invoked`, `memory.injected`, `gate.decision`, `pii.finding`).

Decision: add `GET /api/projects/{pid}/sessions` and a Sessions page. Status is derived at read time, nothing new is
stored: `ended` when a session end was recorded, `active` when not ended and an event arrived in the last 30 minutes,
otherwise `incomplete`. The page polls every 10 seconds; a session's activity is its audit events (newest 50, full
history on the Audit page). Tool calls stay name + path only: command arguments, prompts and file contents are never
logged (CLAUDE.md rule).

Limit: a session already running when the plugin was installed is not recorded; hooks load at session start.
