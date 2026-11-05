# 18: Team server sign-in with OIDC (SSO)

Status: accepted for v1, 2026-11-05. Items under "Open decisions for the owner" are not decided.

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

**Roles.** `SEEN_TEAM_ADMINS` bootstraps admins; after that `PUT /api/users` sets roles. The last-admin guard (409) is not
atomic across concurrent requests (known limit). The bootstrap key can be disabled with `SEEN_TEAM_BOOTSTRAP_DISABLE=1|true|yes`.
The production guard refuses to start only when `APP_ENV=production` AND the bootstrap key is disabled AND no OIDC is
configured; a bootstrap-only production install still starts (see open decision 6).

**One-time id_token.** An id_token mints at most one key. `/auth/exchange` records `sha256(id_token)` in
`team_used_tokens` (kept until the token's `exp` plus the 60 s leeway, pruned on later exchanges) and answers a
replay with the same fixed 401, counted as a failure by the limiter. Without an `exp` the row is kept 2 hours.

**Revoke on deactivate.** Deactivating a user (`PUT /api/users`, `active=false`) and erasing one both revoke every
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

**Known limits.** The discovery document's `jwks_uri` host is not pinned beyond the configured issuer. `/auth/config`
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

## Open decisions for the owner

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
   `--allow-remote` or a non-loopback bind answers `not_configured` and never signs in.
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
