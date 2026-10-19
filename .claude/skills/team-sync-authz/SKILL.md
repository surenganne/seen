---
name: team-sync-authz
description: Use when changing team-server roles or /api/sync authz.
category: security
---

# Team sync authorization

Only user-bound member keys may write sync batches, and only as their own user. Lead, admin, and unbound keys get 403 on `/api/sync`.

- Gate both checks for every caller: `if k.role != "member" or not k.user_id` raises 403, and `if c.user_id != k.user_id` raises 403. The older form `k.role == "member" and c.user_id != k.user_id` let lead and admin keys forge any `user_id`.
- Write the failing test first. It must parametrize over lead and admin keys and assert 403 on both the forged-user batch and the admin-header batch (tests/team/test_team.py). Confirm red, then fix, then green.
- Automated security-review findings on team_server are real until shown otherwise. Do not dismiss them because the service is internal-only. Fix them or state in one line why the pattern is not exploitable.
- Widening writes later (leads sending for others) is a design decision. Add an explicit writer role and store the writer key on the record. Do not loosen the gate silently.

Verify after any change: `uv run pytest tests/team`, then the team-server gates in CLAUDE.md.
