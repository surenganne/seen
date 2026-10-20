# Product

## Register

product

## Users

Three groups, designed for equally:

- **Engineering leads and the platform team**, reviewing what agents did across a team's repos: cost, skills that ran, policy compliance, PII exposure. Weekly reviews plus spot checks when something looks off.
- **Individual developers**, checking their own agent sessions during the day: what changed and when, what a turn cost, which skills ran.
- **Compliance and security reviewers**, auditing evidence for a privacy review: the hash-chained audit trail, PII findings and their sources, approvals, exports.

All of them run Seen locally (or self-hosted) and open it next to their editor or in a review meeting.

## Product Purpose

Seen keeps a per-project ledger of what AI coding agents change: files and lines, tokens and API-equivalent cost, skills run with their versions and approvals, required-skill rules, PII and secrets that reached the model, and a tamper-evident audit trail. Success is a reviewer answering "what did the agent change in project X last week, what did it cost, which skills ran, and did anything sensitive leak" in under a minute, and trusting the answer.

## Brand Personality

Precise, calm, trustworthy. An instrument people rely on: quiet when nothing is wrong, unmistakable when something needs attention (the eyes stop wandering and stare). Plain, specific language; numbers first; never alarmist and never falsely reassuring.

## Anti-references

- Paper, cream or beige editorial styling and serif-heavy magazine layouts (the previous look).
- Generic SaaS dashboards: hero metrics with gradient accents, identical card grids.
- Purple gradients of any kind.
- Any "all clear" or "clean" badge that claims more than was checked.

## Design Principles

1. **Evidence over decoration.** Every element shows something checkable (a path, a hash, a count) or helps reach it.
2. **Calm by default, loud only when earned.** Colour and motion are reserved for state that needs a human: missed policy, high-confidence PII, a broken chain.
3. **Say what was checked.** Limits are stated next to results, never hidden in docs.
4. **One click from summary to proof.** Every number links to the changes or events behind it.
5. **Say "not observed" instead of guessing.** Provenance marks a line agent, human or not observed; where Seen could not have seen the edit it says so and never claims a person wrote it.
6. **The same truth for all three readers.** Leads, developers and reviewers see one data model; views differ by emphasis, not by facts.

## Accessibility & Inclusion

WCAG 2.2 AA: text contrast 4.5:1 (3:1 for large text and UI marks), full keyboard access with visible focus, status never conveyed by colour alone (icon plus label), `prefers-reduced-motion` honoured everywhere including the animated mark, usable at 320px width and 200% zoom.
