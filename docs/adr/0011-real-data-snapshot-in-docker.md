# 0011: The Docker dashboard serves a snapshot of the real data, not mock data

Status: accepted, 2026-10-19 (owner: "I don't want the mock data ... I want that data as part of the docker container";
chose snapshot plus auto-refresh, mock data kept for tests only). Supersedes the "copying snapshots" rejection in 0008.

Decision: `seen docker-sync` makes a consistent copy of `~/.seen` (sqlite online backup of `ledger.db` and `audit.db`,
then `journal_mode=DELETE` so each is one file; `audit-heads.log`, `config.toml`, personal `memory/`) into
`~/.seen-docker/<utc stamp>/` and points `current` at it. The `dashboard` service mounts that folder and runs with
`SEEN_HOME=/snap/current`. The host never touches a copy once published and the container never touches the live
ledger, so the WAL problem in 0008 cannot occur. Two snapshots are kept. `--watch N --restart` repeats and restarts
the dashboard, because pooled connections keep the old file open across a `current` flip.

Mock data: `SEEN_DEV_SEED=1` is now set only on `dashboard-test` (tmpfs e2e). `docker compose up` on an empty
snapshot folder exits with an instruction instead of showing mock data.

Consequences: data is as old as the last snapshot. `secret.key` is not copied. Writes in the container dashboard
(settings, skill approvals) land in the snapshot and vanish on refresh. Repo-side memory (`.seen/memory` in the repo)
is not in the container, so the Memory page shows only personal notes there. Prompt text is in `~/.seen-docker`
(0700), the same sensitivity as `~/.seen`. Home paths are not redacted in the copy (they are in the ledger as
recorded). Ownership of the bind mount works on Docker Desktop for Mac; on Linux the container uid 10001 needs write access.
