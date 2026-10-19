# 0008: Serve the real ledger from the host, not from Docker

Status: accepted, 2026-10-19. Supersedes the `local` profile in ADR 0004.

Observed: the `dashboard-local` container (bind-mounting `~/.seen`) returned HTTP 500
`database disk image is malformed` on `/api/changes/{cid}` while host hooks were writing, although
`PRAGMA integrity_check` on the host said `ok`. The ledger and audit databases run in WAL mode; WAL readers and
writers coordinate through a memory-mapped `-shm` file and POSIX locks, and neither is coherent across the Docker
Desktop VM file share. A reader in the VM sees torn pages, and a writer in the VM (the dashboard's write routes) can
corrupt the file for real.

Decision: the dashboard on real data runs on the host, next to the hooks:
`SEEN_WEB_DIST=$PWD/web/dist seen serve --port 47825 --open`. Docker keeps everything that owns its own database:
the mock-data dashboard (named volume), the test suites, and the tmpfs e2e database. This is the stated reason for
deviating from the Docker-first default for this one service.

Rejected: opening the bind-mounted file read-only or with `nolock` (still incoherent and stale); switching the
ledger to rollback journaling (slower hook hot path and still unsafe across the VM); copying snapshots into the
container (stale by design, more moving parts).
