# Limits, stated plainly

- **Tamper-evident, not tamper-proof.** Someone with write access to this machine can rebuild the audit chain.
  It catches bugs, partial edits and clumsy tampering. Anchoring chain heads on a team server (`seen sync`)
  makes rewriting local history detectable. Retention pruning is recorded as a checkpoint that can only vouch
  for rows that are really gone.
- **Coverage.** Only sessions where the plugin ran are recorded; gaps are recorded as `capture.gap` and
  `session.incomplete`. Sessions that start outside a git repository record nothing (PII block mode still
  applies there). Sessions that installed plugins start in the background are recorded but shown apart from
  your own. Enable the plugin through managed settings for whole teams.
- **Overlapping agents in one repo.** A turn's file changes are measured as the difference between two snapshots of the
  whole working tree. If two sessions (or you) edit the same repo at the same time, each turn can be credited with the
  other's edits, which inflates line totals and can wrongly satisfy or miss a required-skill rule. Use one agent per
  working tree, or separate git worktrees. Cost, tokens, skills and PII findings stay per session. See
  [ADR 0020](adr/0020-concurrent-sessions-attribution.md).
- **PII detection** finds structured identifiers (Aadhaar, PAN, cards, IBAN, email, phone, UPI, DOB, GSTIN, public
  IP addresses, secrets and tokens…). It misses names, addresses and free-text health details unless the optional
  Presidio tier is on. Seen shows exposure; it cannot un-send what already reached the model provider. It is
  evidence for a privacy review, not a compliance control, and makes no claim about DPDP, GDPR or HIPAA compliance.
  In block mode a file over 256 KB, or one that takes longer than the 100 ms scan budget, is read first and scanned
  after the turn (detect only). A custom rule that cannot finish in time blocks the prompt rather than being skipped.
  Precision and recall: [pii-benchmark.md](pii-benchmark.md).
- **Data at rest.** The local ledger (SQLite) and the team database (Postgres) are not encrypted by Seen: use disk
  encryption, and decide whether you also want database encryption. `seen purge` and the team server's delete routes
  erase data (bytes, not just rows); the audit trail keeps a record of each erasure, counts only.
- **Cost** is an API-equivalent estimate from a price table that is not verified against current provider pricing:
  check `pricing/prices.json` before relying on the numbers.
- **The dashboard** has no login: it binds to 127.0.0.1 only, rejects other `Host` headers and requires a custom
  header on every write, and `seen serve` refuses a non-loopback address unless you pass `--allow-remote`
  (containers only). Do not publish its port beyond localhost. The Docker copy is a snapshot (see
  [docker.md](docker.md)). It targets WCAG 2.2 AA: axe checks every page in both themes on desktop and phone sizes in
  CI, and Playwright covers the skip link, keyboard access to table rows, per-page titles and reflow at 320px.
  Automated checks catch only part of what matters, so screen-reader use and 200% zoom are manual checks
  ([TESTING.md](TESTING.md) Part 16).
- **The team server** is an early skeleton; see [team-server.md](team-server.md).
- **Network.** Hooks never touch it. `seen doctor` and `seen upgrade` make one anonymous request to GitHub to look
  for a newer release; set `SEEN_NO_UPDATE_CHECK=1` to stop it.
