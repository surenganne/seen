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

**Environment.** `SEEN_OIDC_ISSUER`, `SEEN_OIDC_CLIENT_ID`, `SEEN_OIDC_ALLOWED_DOMAINS`, `SEEN_TEAM_ADMINS`,
`SEEN_TEAM_BOOTSTRAP_DISABLE`, `APP_ENV`.

**Entra app registration (Entra assumed).** Single tenant; platform "Mobile and desktop" (public client); redirect URIs
`http://127.0.0.1/callback` (CLI) and `http://127.0.0.1:47821/api/team/callback` (dashboard); add the `email` optional claim
to the ID token. Use placeholders such as YOUR_TENANT_ID and YOUR_CLIENT_ID in config; never commit real ones.

**Known limits.** The discovery document's `jwks_uri` host is not pinned beyond the configured issuer. `/auth/config`
failures are not negatively cached. `seen serve` disables the uvicorn access log so callback codes are not logged.
pip-audit (run 2026-11-05 on the exported lockfile, `uvx pip-audit --no-deps -r <export>`): 1 package affected,
certifi 2026.7.22 PYSEC-2026-4320 (fix 2026.10.18). It is transitive and was present before SSO.

## Open decisions for the owner

1. **Project scoping.** In v1 leads and admins are org-wide, SSO members can push any project, and SSO members see no
   project aggregates in the dashboard. Cost if wrong: over-broad access inside the tenant.
2. **Client key storage.** A 0600 file (`~/.seen/team_key`) or the OS keychain. The file is simple and works on every OS;
   the keychain resists other processes of the same user.
3. **Plaintext email at rest** on the team server is a DPDP decision item: encrypt at rest or at field level, and
   encrypt backups. The pseudonymous `sub` is kept after an erase for access control; confirm that retention purpose.
4. **Installs that synced with a manual key** get a permanent 403 on the same install id after `seen team login`
   (`owns()` accepts only earlier SSO keys). Needs an admin re-bind or a fresh install id.
5. **Docker or `--allow-remote` dashboards** can complete a sign-in and write `team_key` inside the container. The
   recommendation is to refuse `POST /api/team/login` from a snapshot or with `--allow-remote`. Not implemented in v1.
6. **Production guard.** Is a bootstrap-only production install acceptable, or must OIDC be required?
7. **Members `last_synced_at` and `key_expired`** are account-wide, not per project.
