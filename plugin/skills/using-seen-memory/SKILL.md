---
name: using-seen-memory
description: Use when you learn a durable project decision, convention or gotcha that future sessions should know, or when Seen says project memory did not load. Saves it as a file in .seen/memory/.
---

# Saving project memory with Seen

Seen loads every file in `.seen/memory/` into new sessions. Save something there when it will still matter next week:

- **decision**: a choice the team made, and why ("Refunds carry an idempotency key; retries reuse it").
- **convention**: how things are done here ("Tests freeze time with the clock fixture, never sleep").
- **gotcha**: a trap that cost time ("KYC sync must finish before 06:00 IST or the partner API rate limits").
- **context**: background a newcomer needs ("LLM calls go through Bedrock in ap-south-1 for data residency").

Do not save: task progress, things obvious from the code, guesses, or anything temporary.

## Never save

Secrets, credentials, tokens, personal data (names, emails, phone, Aadhaar, PAN, addresses) or client confidential details. This folder is committed and visible to everyone with repo access.

## How

Write one file per memory: `.seen/memory/<id>.md`, where `<id>` is short, lowercase and hyphenated.

```markdown
---
id: refund-idempotency
type: decision
file_ref: src/payments/refund.py
source_change:
verified_at:
---
Refunds must carry an idempotency key; retries reuse the same key.
```

- `type` is one of `decision`, `convention`, `gotcha`, `context`.
- `file_ref` is optional: the repo-relative file the memory is about. Seen marks the memory stale when that file changes.
- Leave `verified_at` empty. A human verifies it later (`seen memory verify <id>`); until then it shows as unverified.
- Keep the body to one or two sentences. Edit an existing file instead of adding a near-duplicate.

## If Seen paused your edits

Seen blocks file edits when project memory did not load. Read the files in `.seen/memory/`, then retry the edit.
