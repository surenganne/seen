# 0010: Tell plugin-started background sessions apart from the person's own

Status: accepted, 2026-10-19 (owner: "sessions data is completely wrong ... haiku is not used on this repo")

Observed: of 131 Claude Code transcripts for this repo, 2 were the owner's (`entrypoint: cli`). The other 129 were
short sessions that installed plugins start through the Agent SDK in the repo's folder (118 `sdk-py`, 11 `sdk-cli`),
for example a reflector running on Haiku. They are real sessions that cost real tokens, so they are recorded, but
listing them as the owner's work made the Sessions page look wrong.

Decision: store how each session was started in `sessions.entrypoint` (migration 0003), from `CLAUDE_CODE_ENTRYPOINT`
at SessionStart (spikes/entrypoint) or from the transcript's `entrypoint` field on import. `seen import` also fills it
in for sessions already recorded, without re-importing them. A session is *background* when its entrypoint starts with
`sdk`. The API takes `kind=yours|background|all` and always returns all three counts; the Sessions page opens on
Yours and shows the Background count next to it, so nothing is hidden without saying so.

Not changed: Overview, Changes and cost totals still include background sessions, because that spend is real.
Sessions recorded before this change with no transcript left keep a null entrypoint and count as Yours.
