# 0009: Record nothing for sessions outside a git repo

Status: accepted, 2026-10-19 (owner asked for the best call)

The plugin is installed user-wide, so its hooks fire in every folder. On 2026-10-19, 21 of 22 live changes came from
short background sessions that other plugins start outside any repo (`~/.meridian`, and folders with no transcript).
They have no project, so no memory, lockfile or policy, and they don't appear on any project's dashboard. Even so,
their redacted prompts were stored in `~/.seen`.

Decision: at SessionStart, a session whose cwd is not inside a git work tree is marked untracked
(`snap/<sid>.untracked`). `spool.append`, the only path for writing spool lines, does nothing for a marked session,
so no prompt, tool, PII finding or change reaches the spool, ledger or audit trail. Spool cleanup removes the marker
and its snapshot files after the usual 7 days.

Still applies: PII block mode, for prompts and reads. It is a protection, not a record, so it keeps blocking in
untracked sessions; the block is just not logged.

Limits: a session that starts outside a repo and later `cd`s into one stays untracked. A session already running at
install time never fires SessionStart, so it is still recorded as before. Data already recorded for non-repo sessions
is left alone (audit rows are never deleted).
