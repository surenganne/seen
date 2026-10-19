# 0012: Erasure and key lifecycle (DPDP)

Status: accepted, 2026-10-19 (audit findings: no retention/erasure, team keys could never be revoked).

Local: `seen purge --before DATE | --project ID | --all` (reports only; `--yes` erases). Rows go from changes and
their child tables, then sessions, the project row (when the whole project goes) and queued outbox payloads (by age
or wholesale: they are not project-tagged). `secure_delete` plus `VACUUM` and a WAL checkpoint remove the bytes, not
only the rows. The audit trail stays append-only: a `ledger.purge` event records actor and counts, never content.
Skill inventory and policies are not personal data and stay. Sessions still being recorded keep their spool file.

Team server: `GET /api/keys`, `DELETE /api/keys/{id}` (revoke), `expires_in_days` on create, `DELETE /api/users/{id}`
(their changes go and their keys are revoked), `DELETE /api/projects/{id}`; all admin-only. A revoked or expired key
answers 401 like a wrong one. The two new key columns are added in place at startup (`create_all` cannot alter);
Alembic is still due before the next schema change (ADR 0005). Audit-head anchors hold only hashes and are kept.

Not decided here (owner): encryption at rest for the team Postgres and the local SQLite, and whether erasure
requests need a server-side log. Docker snapshots (ADR 0011) keep erased data until pruned.
