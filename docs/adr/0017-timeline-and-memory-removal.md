# 17: Timeline of changes; memory removed in stages (owner request, outside the plan)

Status: accepted, 2026-10-20

The owner asked for a timeline of what changed in a repo and who made each change, and for the project-memory
feature to be removed completely. The plan lists memory as one of its pillars (sections 6, 10, 11), so this
changes the plan. It supersedes ADR 0003 and the memory parts of ADRs 0006 to 0011.

**Timeline (done first, additive).** `GET /api/projects/{pid}/timeline` and a Timeline page. Entries reuse the
change rows, grouped by IST day, newest first, with the user and the short commit the change ended on. Nothing
new is stored. The user is the pseudonymous `actor_id` from the audit trail (identity.py), never a login or email.
A local ledger only holds the local user; a view across users needs the team server and is not built yet.

**Memory removal (stages, each one merged with the gates green):**
1. Hook: drop injection, the memory gate (`memory_loaded` marker, exit 2) and `memory.injected` events.
2. API and UI: drop the memory routes, the Memory page, the `mem` filters and memory fields in overview, change
   detail, sync and snapshot.
3. Ledger: a new migration drops `change_memories` and `changes.mem_*`. Migration `0001` is not edited, and
   audit rows are never changed: old `memory.injected` and memory gate events stay readable as history.
4. Plugin, CLI, docs, tests, fixtures: the `using-seen-memory` skill, `seen memory` commands, config keys,
   docs, ADR statuses.

Upgrade note: an installed `seen-hook` older than the migration fails open and records nothing, so reinstall
the CLI after stage 3 (as in the hook-binary-schema gotcha). Existing `.seen/memory/*.md` files in repos are left
alone; Seen stops reading them.
