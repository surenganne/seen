# 0014: Sync dead letters, ingest validation and throttling

Status: accepted, 2026-10-19 (audit findings on the team server and outbox).

Client: a batch the server rejects for good (any 4xx except 408, 425, 429) is parked, not retried forever: the outbox
gets `dead_at` and `last_status` (migration 0004), a `sync.batch` audit event records `ack: rejected` with the status,
and the changes stay unsynced, so nothing is lost. It is not re-queued on every push. `seen sync --retry-failed`
revives parked batches after the key or server is fixed, and `seen doctor` shows how many are parked. The audit
allowlist no longer sends `capture.gap.error` (error text can echo values).

Server: ingest fields are non-negative and capped (500 files, 100 skills, 200 policies, 100 heads, 1000 events, 50 PII
types); `audit` events are validated against a typed model instead of accepted and dropped; request bodies over 2 MB
get 413 and a missing Content-Length gets 411. The throttle counts every request per client (600 per minute) as well
as failures (8 per minute). Behind a reverse proxy set `SEEN_TEAM_PROXY_HOPS=N`: the client address is then the
entry the Nth proxy appended to X-Forwarded-For; the header is ignored otherwise, so it cannot be used to dodge the limit.

Local API: `PUT /api/settings` accepts `sync.server` only as https (http for localhost) with no credentials or
whitespace, so a page or process that can edit settings cannot aim the API key at plain http on the internet.

Not done: a re-confirmation step in the dashboard for turning on sync or `send_paths` (needs a UI change), and
per-key rate limits on `/api/sync`.
