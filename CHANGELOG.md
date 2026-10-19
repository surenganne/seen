# Changelog

## Unreleased

- **Docker dashboard serves your real data** through a consistent snapshot (`seen docker-sync`, ADR 0011). Mock data
  is for the test stacks only.
- **Privacy and recall:** a blocked prompt is no longer stored; custom PII rules have a cap and a deadline against
  ReDoS; `hook.log` keeps only frames and exception types. New detectors: quoted and URL-embedded secrets, Bearer,
  Google, Stripe and GitLab tokens, public IPv4, `91`-prefixed phones, Aadhaar VIDs (with a keyword).
  `ip` and `gstin` join the default PII types.
- **Erasure (DPDP, ADR 0012):** `seen purge`; team server key list, revoke and expiry, and user and project delete.
- **Upgrade flow (ADR 0013):** `seen version`, `seen upgrade`, `/seen:upgrade`, skew checks and an update notice in
  `seen doctor`, `scripts/bump_version.py`, and a test that keeps every version in step.
- Architecture diagram: `docs/architecture.html`.
