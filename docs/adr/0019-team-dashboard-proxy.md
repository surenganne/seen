# 19: The Team page reads the team server through the local API

Status: accepted, 2026-11-05.

**Why a proxy.** The browser never holds the team key. The local API reads it (environment variable or
`~/.seen/team_key`), calls the team server and returns aggregates. The page receives no key, token or
credential at any point.

**Rules.** Outbound calls happen only when `sync.server` is set. Every failure is HTTP 200 with a `state`
(`not_configured`, `login_required`, `unreachable`, `unauthorized`, `forbidden`, `bad_response`) and a fixed
reason, so no server text or exception detail reaches the page. Redirects are disabled, responses are capped at
2 MB, and the project id is validated before it is put in a URL. A network failure (down or unreachable team server) is not logged; unexpected failures log the exception type name
only.

**Privacy.** Aggregates only: no per-person change detail. The members list ("Last synced") is for leads and
admins; it shows the email when the member signed in through SSO and the user id otherwise. A project's members
for SSO are those with activity in that project, so an SSO user with no changes there is not listed. The Docker
snapshot dashboard is not team-configured: `seen docker-sync` strips the `[sync]` table from the copied
`config.toml`, so it shows `not_configured`. Independently, a dashboard started with `--allow-remote` or a
non-loopback bind is "remote": its session, projects, overview and members routes answer `not_configured` without any
outbound call (it never reads team data on the owner's key), login returns no URL, the callback only redirects, and
logout does nothing. The compose file should also mount the snapshot read-only (`:ro`); it does not yet.
"Remote" is decided at startup from the flag and the bind host, so a dashboard bound to loopback but exposed through a
reverse proxy, an SSH tunnel or a Docker port publish is not detected. The local API has no login by design: do not
expose a loopback dashboard through a proxy, because the team routes would serve data on the owner's key.

**Known limit.** A server that drip-feeds a response is not cut off by a total timeout (only per-read timeouts).

See ADR 0018 for sign-in and the open decisions (scoping, plaintext email at rest).
