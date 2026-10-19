# 0007: Import past sessions from Claude Code transcripts

Status: accepted, 2026-10-19 (owner request)

Hooks load when a session starts, so work done before the plugin was installed (or in a session already running at
install time) never reaches the ledger. Claude Code keeps every session's transcript under
`<claude config>/projects/<cwd with non-alphanumerics as '-'>/<session_id>.jsonl`.

Decision: `seen import [--dry-run]` reads this repo's transcripts and records each session through the live code
paths: `parse_turn` (now with an end offset) for tokens, models, skills and tool output; `pricing.cost`; prompt
redaction per `pii.store_prompt_text`; the prompt and stop-scan PII detectors; skill reconciliation against the
lockfile; required-skill policies. Every write gets an audit event with a deterministic `imp:` id.

- Sessions recorded live are never touched. Imported sessions are marked `sessions.source = imported`
  (migration 0002) and the UI labels them.
- Not observable from a transcript, so left empty rather than guessed: git status and HEADs, memory state.
  Line counts come from Edit/Write/MultiEdit inputs.
- A transcript written to in the last 30 minutes stays open (no `session.end`); re-running adds new turns and closes
  it once quiet. Re-running is idempotent.

Consequence: the `seen-hook` binary must be at least as new as the ledger schema. An older hook that meets
revision 0002 fails open and records nothing, so upgrade the CLI whenever the plugin updates.
