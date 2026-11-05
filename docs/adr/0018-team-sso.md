# 18: Team server sign-in with OIDC (SSO)

Status: accepted for v1, 2026-11-05. Items under "Open decisions" carry a v1 ruling (defaults, reversible). Items 3 and 8 still need the owner (legal, real tenant).

**Flow.** OIDC authorization code with PKCE (S256) as a public client. The redirect is loopback, there is no client
secret, and the implicit flow is not used (tokens never travel in a URL fragment, and a stolen code is useless
without the verifier). The CLI (`seen team login`) and the dashboard each run their own redirect.

**Validation (team server).** RS256 only (PyJWT); exact, pinned tenant issuer; audience; nonce; `tid`; `email_verified`
strictly when present; email domain allowlist, exact match; JWKS cached 1 h and refreshed at most every 60 s. It fails
closed when stale: an IdP or JWKS outage longer than 1 h blocks new logins (existing keys keep working).

**Server-minted keys, not session JWTs.** After validation the server issues its own 30-day API key, hashed at rest and
shown once. Revocation is therefore immediate: deactivate the user, or `DELETE /auth/me` on logout. An erase leaves a
tombstone that keeps the pseudonymous `sub` with the email blanked and the user inactive, so coming back needs an explicit
re-activation.

**Roles.** `SEEN_TEAM_ADMINS` bootstraps admins; after that `PUT /api/users/{sub}` sets roles. The last-admin guard (409) is not
atomic across concurrent requests (known limit). The bootstrap key can be disabled with `SEEN_TEAM_BOOTSTRAP_DISABLE=1|true|yes`.
With `APP_ENV=production` the server refuses to start in three cases: the bootstrap key is disabled and no OIDC is
configured (no way to sign in); the bootstrap key is not disabled and `SEEN_TEAM_BOOTSTRAP_KEY` is shorter than 32
characters (so an OIDC-only install must set `SEEN_TEAM_BOOTSTRAP_DISABLE`); or the OIDC issuer is not https. A
bootstrap-only production install still starts (see open decision 6). Setting only one of `SEEN_OIDC_ISSUER` and
`SEEN_OIDC_CLIENT_ID` stops startup in every environment.

**One-time id_token.** An id_token mints at most one key. `/auth/exchange` records `sha256(id_token)` in
`team_used_tokens` (kept until the token's `exp` plus the 60 s leeway, pruned on later exchanges) and answers a
replay with the same fixed 401, counted as a failure by the limiter. Without an `exp` the row is kept 2 hours.

**Revoke on deactivate.** Deactivating a user (`PUT /api/users/{sub}`, `active=false`) and erasing one both revoke every
live key whose `user_id` is that person's `sub`, whatever its origin, so a manual key bound to the same id stops at
once. Reactivating does not bring keys back: the person signs in again.

**Environment.** `SEEN_OIDC_ISSUER`, `SEEN_OIDC_CLIENT_ID`, `SEEN_OIDC_ALLOWED_DOMAINS`, `SEEN_TEAM_ADMINS`,
`SEEN_TEAM_BOOTSTRAP_DISABLE`, `SEEN_TEAM_PROXY_HOPS`, `APP_ENV`.

`SEEN_TEAM_PROXY_HOPS` is the number of trusted reverse proxies in front of the server (default 0). The per-IP
limiter then uses the address the Nth proxy appended to `X-Forwarded-For`. Without it, behind a proxy, every client
shares the proxy's address and one person's 8 wrong attempts a minute lock sign-in and sync for the whole team, so set
it for any proxied install. It is parsed once at startup: a non-integer or negative value stops the server with a
fixed error, never a 500 per request. The limiter tables drop idle addresses and are capped at 10,000 entries
(oldest first).

**Production guard.** With `APP_ENV=production` the server also refuses to start when `SEEN_OIDC_ISSUER` is not
https (a loopback http issuer is for development and tests only).

**Entra app registration (Entra assumed).** Single tenant; platform "Mobile and desktop" (public client); redirect URIs
`http://127.0.0.1/callback` (CLI) and `http://127.0.0.1:47821/api/team/callback` (dashboard); add the `email` optional claim
to the ID token. Use placeholders such as YOUR_TENANT_ID and YOUR_CLIENT_ID in config; never commit real ones.

**Known limits.** The members route builds `IN` lists from the project's user ids without a bound (fine at team scale). A lost
`/auth/exchange` reply leaves one orphaned 30-day key (hash only); the next `seen team login` works. Installs that synced
with a manual key get a 403 on the same install id after SSO login, and the reverse (env key set after an SSO sync)
also 403s. The discovery document's `jwks_uri` host is not pinned beyond the configured issuer. `/auth/config`
failures are not negatively cached. `seen serve` disables the uvicorn access log so callback codes are not logged.
`/auth/config` serves only https IdP endpoints, so a plain-http loopback IdP can validate tokens but cannot drive
`seen team login` or the dashboard sign-in; local testing uses a TLS fake IdP with `SSL_CERT_FILE` pointing at its
certificate. `seen sync` exits 0 when a batch is parked on a 401 or 403 (the message goes to stderr), so scripts
cannot detect it from the exit code. The team server does not validate the project id format itself (the dashboard
proxy does): an id such as `abc%0A` returns an empty overview at the server, with no leak. IPv6 clients can rotate
source addresses to refresh the per-IP failure budget; API keys carry 256 bits, so this weakens the limiter, not the
keys. For a non-Entra issuer there is no tenant pin and an absent `email_verified` is still accepted.
Dependency audit (2026-11-05): `pip-audit` on the production export (`uv export --no-dev --frozen --all-packages`)
finds nothing and `npm audit --omit=dev` finds 0. The one advisory in `uv.lock`, certifi 2026.7.22 (PYSEC-2026-4320,
fix 2026.10.18), is in the dev/test dependencies only and is not in the production export; keep bumping it.

## Open decisions

**v1 rulings (2026-11-05, controller, reversible; owner may overturn).**
- 1 Scoping: keep org-wide leads/admins. Reason: small team, no project-to-group mapping from the IdP yet. Revisit with Entra group claims.
- 2 Key storage: keep the 0600 file. Reason: works on every OS, same trust level as `~/.seen` ledger. Keychain is a later option.
- 4 Manual-key installs: documented limit; fix is admin re-bind or a fresh install id. No auto-bind, because the manual `user_id` is client-chosen.
- 5 Resolved in code (see below).
- 6 Production guard: a bootstrap-only production install still starts, with the 32-character key minimum. OIDC is not forced, so existing deployments keep working.
- 7 Members `last_synced_at`: account-wide in v1.
- Compose `/snap` mount stays read-write: the container dashboard writes settings and approvals there by design.
- Still owner-only: 3 (plaintext email at rest, DPDP) and 8 (admin by `email` claim; check against a real Entra tenant first).

1. **Project scoping.** In v1 leads and admins are org-wide, SSO members can push any project, and SSO members see no
   project aggregates in the dashboard. Cost if wrong: over-broad access inside the tenant.
2. **Client key storage.** A 0600 file (`~/.seen/team_key`) or the OS keychain. The file is simple and works on every OS;
   the keychain resists other processes of the same user.
3. **Plaintext email at rest** on the team server is a DPDP decision item: encrypt at rest or at field level, and
   encrypt backups. The pseudonymous `sub` is kept after an erase for access control; confirm that retention purpose.
4. **Installs that synced with a manual key** get a permanent 403 on the same install id after `seen team login`
   (`owns()` accepts only earlier SSO keys). Needs an admin re-bind or a fresh install id.
5. **Docker or `--allow-remote` dashboards** used to be able to complete a sign-in and write `team_key` inside the
   container. Resolved: `seen docker-sync` strips `[sync]` from the copied config, and a dashboard started with
   `--allow-remote` or a non-loopback bind is "remote": `/api/team/session`, `/projects`, `/overview` and `/members`
   answer `not_configured` without any outbound call, `/api/team/login` returns no URL, `/api/team/callback` only
   redirects, and `/api/team/logout` does nothing (a network peer cannot revoke the owner's key).
6. **Production guard.** Is a bootstrap-only production install acceptable, or must OIDC be required?
7. **Members `last_synced_at` and `key_expired`** are account-wide, not per project.
8. **Bootstrap admin by `email` claim.** `SEEN_TEAM_ADMINS` matches the `email` claim, which Entra treats as a
   changeable directory attribute: a tenant user administrator, or a B2B guest whose `mail` is set to an admin's address
   before that admin's first login, could become admin (audit U1, confidence 6). Recommendation: after the first login,
   match admins by the IdP object id (`sub`/`oid`), or reject guests and unverified domains (`acct`, `xms_edov`). Check
   against a real tenant first; it was not tested against one.

**Restated from the security audit (still open or accepted).** SSO leads see every project's member emails. The
bootstrap admin key never expires and coexists with SSO in production unless `SEEN_TEAM_BOOTSTRAP_DISABLE` is set
(open decision 6). IPv6 clients can rotate source addresses to refresh the throttle budget. Non-Entra issuers accept a
missing `email_verified` without a tenant pin.

## Pre-deploy checklist (required before the team server faces users)

- Run `cso --owasp` (daily mode) on the branch and keep its PDF report under `docs/security/`. The baseline report there
  was written by hand; the tool run is outstanding.
- Reproduce on the Postgres and Docker stack: security headers via `curl`, the container user (`id`), and the throttle
  status codes. Not done so far.
- Decide the open items above (plaintext email at rest, scoping, bootstrap key, admin matching by email claim).

## Maintainability follow-ups (not done)

- Three copies of `_NoRedirect` (`oidc.py`, `teamauth.py`, `team.py`), a second opener in `team.py`, and the key lookup
  duplicated between `teamauth._current_key` and `sync.server_and_key`; key minting is repeated in `exchange` and the
  manual key route.
- `packages/team_server/src/seen_team/app.py` is large with one `create_app` closure; move SSO and user routes to their
  own module with a `register(app, ...)`, like `seen_local/team_login.py`.
