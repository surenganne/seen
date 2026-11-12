# Team server and SSO

Optional, and an early skeleton. Seen works fully without it. Sync is off by default and sends only the metadata you
switch on; per-person detail stays private to that person. Prompts and diffs are never sent.

Start it with `sh deploy/init-env.sh` then
`docker compose -f deploy/docker-compose.team.yml --env-file deploy/.env up -d`. The server listens on
http://127.0.0.1:47824 and Postgres on 47823 (set `SEEN_TEAM_PG_PORT` in `deploy/.env` if that port is taken).

## SSO

People sign in with Microsoft Entra ID (OIDC, authorization code with PKCE, public client, no secret); the server then
issues its own 30-day API key. Set this in `deploy/.env` and restart the server:

| Variable | Meaning |
|---|---|
| `SEEN_OIDC_ISSUER` | `https://login.microsoftonline.com/<tenant id>/v2.0`; https only in production |
| `SEEN_OIDC_CLIENT_ID` | the app registration's client id; set it together with the issuer or startup stops |
| `SEEN_OIDC_ALLOWED_DOMAINS` | comma-separated email domains allowed to sign in |
| `SEEN_TEAM_ADMINS` | comma-separated emails that become admin on first sign-in |
| `SEEN_TEAM_BOOTSTRAP_DISABLE` | `1` turns the bootstrap admin key off once SSO works |
| `SEEN_TEAM_PROXY_HOPS` | number of trusted reverse proxies in front of the server |

Register these redirect URIs in Entra: `http://127.0.0.1/callback` (command line) and
`http://127.0.0.1:47821/api/team/callback` (dashboard). On the host, set `[sync] server` in `~/.seen/config.toml` or in
Settings, then use **Sign in with SSO** on the Team page or `seen team login`. The dashboard in Docker never signs in
(its snapshot has no `[sync]` section). Settings shows the SSO status, and an admin also sees the server's settings; SSO
itself is changed on the server, not from a dashboard. Details and open decisions: [ADR 0018](adr/0018-team-sso.md),
[ADR 0019](adr/0019-team-dashboard-proxy.md).

```bash
seen team login | logout | whoami   # sign in to the team server with your identity provider
```

## Limits

The server is a skeleton: optional OIDC sign-in (ADR 0018), schema changes outside Alembic, and no scheduled retention.
The Postgres database is not encrypted by Seen; see [limits](limits.md).
