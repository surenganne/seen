# Spec: Provenance ("git blame for AI")

Status: draft for owner review, 2026-10-20. Nothing here is built. Accepting it means writing ADR 0018 (see
"Decisions needed") and starting at task PV-0.

## 1. Problem

Seen records what an agent did per turn (files, lines, cost, skills, rules, PII) and the Timeline shows which commit
a turn ended on. It cannot answer the questions a reviewer asks about code that already landed:

- Who or what wrote this line: an agent request, or a person?
- For this pull request, how much was agent-written, which requests produced it, which skills ran, did a required rule
  get missed, and what was checked for PII?

Today the answer needs someone to read Changes and Timeline and match commits by hand. It breaks as soon as the work is
committed later by a person, squashed, rebased or renamed.

## 2. Goals and non-goals

Goals (v1, local):

1. `seen blame <path>`: per line, `agent`, `human` or `not observed`, with the request that produced it.
2. A file provenance view in the dashboard with the same answer, one click from a Change.
3. `seen pr-report`: one Markdown or JSON report for a branch or PR range, with an optional gate (`--fail-on`) and an
   optional, explicit `--post` to a GitHub PR.
4. Works after commits, amends, rebases, squash merges and renames, because attribution follows line content, not SHAs.
5. Keeps every existing rule: no prompt text or diff content is stored or synced, hooks fail open, the hot path stays
   stdlib-only, nothing leaves the machine unless the user runs `--post`.

Non-goals (v1):

- No CI integration. The ledger is local, so a hosted runner cannot read it. Sharing provenance with CI is v2 (section 11).
- Not Cursor, Codex or other agents. Claude Code only, like the rest of Seen.
- No attribution of edits made through Bash (`sed -i`, formatters, code generators). These are reported as `human` or
  `not observed`, never guessed. See the spike (PV-0) for whether a tree-diff fallback is worth adding.
- No identification of *which person* wrote a human line. Provenance says "not an agent", nothing more.
- No dashboard "agent share of the codebase" tile. Planned for v1.1 once survival is measured (section 10).

## 3. How it works (summary)

```
capture   PostToolUse(Edit|Write|MultiEdit|NotebookEdit)  ->  keyed fingerprints of the lines the agent *added*
          (stdlib, no content stored)                         spool event "prints"
store     ingest at Stop                                   ->  table line_prints(project, path, fp, change)
read      git blame --porcelain  +  fingerprint each current line  ->  lookup  ->  per-line attribution
```

Why tool inputs and not a diff of the working tree: the Edit/Write input is exactly the text the agent wrote. A tree
diff also counts a person's edits made during the turn and earlier uncommitted work (a known limit already noted in
`gitdelta.py`). Using the input gives high precision: a line is only ever called `agent` if the agent typed it.
The cost is recall for Bash-generated changes, which is stated, not hidden.

## 4. Data model

Migration `0006_line_prints` (never edit an applied migration):

| Table | Columns | Notes |
|---|---|---|
| `line_prints` | `project_id` text, `path` text, `fp` blob(8), `change_id` text; primary key `(project_id, path, fp, change_id)` | `path` is repo-relative. Index `(change_id)` for purge and survival. |

`changes` gains no columns. Whether a change was fingerprinted is `EXISTS (SELECT 1 FROM line_prints WHERE change_id = ?)`
plus the session source: imported sessions (`seen import`) carry no tool inputs here, so they have none (v1.2 can fingerprint
the Edit/Write inputs that transcripts contain).

Fingerprint:

```
normalize(line) = line.strip() with runs of whitespace collapsed to one space
fp(line)        = HMAC_SHA256(secret.key(), "seen-line-v1\0" + normalize(line))[:8]
```

- Keyed with the per-install `secret.key`, so a fingerprint cannot be matched to guessed code without that key. The key
  is never synced (existing rule, ADR 0012).
- 8 bytes: about 2^-24 chance of any collision among a million lines in one project, and a collision only mislabels one
  line. A prefix tag (`seen-line-v1`) lets a later version change the scheme.
- A line is a *candidate* only if it has at least 10 alphanumeric characters after normalisation. Shorter lines (`}`,
  `else:`, `return`, blank) are *trivial* and are never fingerprinted. See "Trivial lines" in section 6.

Storage estimate: about 30 bytes per row; 100,000 agent-written lines is about 3 MB.

## 5. Capture (hook side)

Where: the existing `PostToolUse` hook, for `Edit`, `Write`, `MultiEdit` and `NotebookEdit`. It already appends a `tool`
spool line; it additionally appends one `prints` line:

```json
{"ev": "prints", "tool_use_id": "...", "path": "src/a.py", "fps": ["a1b2...16 hex", "..."], "n": 42}
```

What is fingerprinted (the lines the agent *added*):

| Tool | Added text |
|---|---|
| `Write` | every line of `content` |
| `Edit` | lines of `new_string` that are not lines of `old_string` (multiset difference by normalised line) |
| `MultiEdit` | the same rule for each edit in `edits`, in order |
| `NotebookEdit` | lines of `new_source` (cell source only; `edit_mode: delete` adds nothing) |

Rules:

- Stdlib only (`hashlib`, `hmac`), no new imports on the hot path; `tests/pii/test_ner.py` still enforces the import list.
- The spool never receives line text, only fingerprints. Paths are made repo-relative with the same
  `realpath`/`relpath` logic ingest uses; a path outside the repo is skipped.
- Caps: at most 5,000 candidate lines per tool call and 1 MB of added text; beyond that, record `n` and a `capped: true`
  flag and attribute nothing from that call. Binary content (a NUL in the first 8 KB) is skipped.
- Fails open: any exception is swallowed and logged like every other hook (`capture.gap` event, as today).
- Config: `[provenance] enabled = true` (default on, shown read-only in Settings). Off means no `prints` lines at all.
- Hot-path budget: at most +5 ms p50 for a 200-line edit on top of today's PostToolUse cost (measured in the `perf` suite).

Ingest (`finish_turn`, not the hot path): turn `prints` lines into `line_prints` rows for that turn's change id, in the same
transaction as `change_files`. Unknown or malformed `prints` lines are ignored (an older ingest ignores the whole event
type, so mixed versions are safe).

## 6. Attribution (read side)

### 6.1 Blame

`git blame --porcelain -w -M -C --end-of-options <rev> -- <path>`, run through `seen_core.gitutil` (repo files and git
config are untrusted input). `-w` ignores whitespace-only changes, `-M -C` follow moved and copied lines. The porcelain
output gives, per line: the blamed commit, that commit's committer time, the file name *at that commit*, and the text.
The parser is written test-first against recorded porcelain output (including renames, boundary commits and
non-UTF-8 lines).

### 6.2 Per-line rule

For each line with text `t` blamed to commit `c` at path `p` (the path at `c`):

1. If `t` is trivial, defer to 6.3.
2. Look up `fp(t)` in `line_prints` for `(project, p)`. No row: the line is **human**, unless 6.4 says otherwise.
3. Several rows (the same line written by several requests): pick the change with the greatest `ended_at` that is not
   later than `c`'s commit time (the line existed when committed). If none, pick the earliest change after it (written,
   then committed later by a person). This is the tie-break and it is deterministic.
4. The result is `agent` with that change id.

### 6.3 Trivial lines

A trivial line is attributed only by adjacency: it is `agent` (change X) when the nearest non-trivial line above and the
nearest non-trivial line below, both within the same blamed commit, are both `agent` with the same change X. Otherwise it
is `human`. Blank lines are reported as `neutral` and left out of every percentage. This avoids window fingerprints that
break at the edge of every edit.

### 6.4 "Not observed"

A line is `not observed` rather than `human` when Seen could not have seen it:

- its blamed commit is older than the project's first recorded change (the code predates Seen), or
- its blamed commit time falls inside a recorded `capture.gap` or `session.incomplete` window, or
- the file is binary, over 1 MB or untracked.

The report always shows the three counts separately. It never folds `not observed` into `human` (principle: say what
was checked).

### 6.5 Blocks

Consecutive lines with the same attribution and the same change id are merged into blocks for display:
`{start, end, who, change_id | null}`. A block carries the change's headline (the Timeline's one-liner), time, model,
skills and PII state, read from the ledger at query time. Nothing about the block is stored.

## 7. Interfaces

### 7.1 CLI

```
seen blame <path> [--rev REV] [--json]
seen pr-report --base BASE [--head HEAD] [--format md|json] [--no-cost]
               [--fail-on rule-missed|pii-high|unapproved-skill]... [--post]
seen provenance prune --dry-run | --yes        # drop prints for deleted files (v1.1)
```

`seen blame` prints, per block: line range, who, the headline, time (IST), model, skills. `--json` is the same data.

`seen pr-report` (all local, read-only unless `--post`):

1. Diff `BASE...HEAD` (merge-base) with `git diff --unified=0`; collect the added lines per file.
2. Attribute each added line by content (6.2), so squashed and rebased history works. Lines are looked up at the path
   in `HEAD`; renames use `git diff -M`.
3. Aggregate: added lines by `agent` / `human` / `not observed`, share of `agent`, files, the requests that produced
   them (headline, time, model), sessions, skills run with their approval status *at the time they ran*, rule results,
   and the PII state of those changes with the sentence of what was checked (the existing `PII_CHECKED` text).
4. Cost (API-equivalent) is included unless `--no-cost`.
5. `--fail-on` makes the exit code non-zero when any listed condition holds (rule missed, high-confidence PII in a
   contributing change, a skill that was not approved). Without it the exit code is 0.
6. `--post`: shows the rendered comment, asks for confirmation (unless `--yes`), then calls `gh pr comment` for the
   branch's PR. It is the only network action. It writes an audit event `provenance.reported` with counts only (lines,
   requests), never headlines or text.

Example (md):

```
AI provenance for feature/refund-retry (6 commits)
Added lines: 412  ·  agent 318 (77%)  ·  human 61 (15%)  ·  not observed 33 (8%)
Requests: 5 in 2 sessions · claude-sonnet-5-5, claude-opus-5-5 · $6.10 API-equivalent
Skills: tdd (approved), security-review (approved)
Rules: llm/** requires phi-redaction-check: missed in 1 request
PII: checked prompts, file reads, tool output, network inputs and added diff lines for structured identifiers; none found.
      Names and free text are not detected.
Unattributed lines are human edits or code Seen did not see (Bash-generated, before the plugin, other machines).
```

### 7.2 API (local server)

| Route | Returns |
|---|---|
| `GET /api/projects/{pid}/provenance/file?path=&rev=` | blocks as in 6.5, plus counts `{agent, human, not_observed, neutral}` |
| `GET /api/projects/{pid}/provenance/range?base=&head=` | the `pr-report` data as JSON |

Both are reads (no audit event, like other reads). `path` and revs are validated: repo-relative, no `..`, no symlink out
of the repo (`seen_core.safeio`), revs must match a safe ref pattern, and git runs through `gitutil` with
`--end-of-options`. Caps: files over 1 MB or 20,000 lines return `not_observed` with a reason; each request has a time
budget (default 5 s) and returns a partial result with `truncated: true` rather than hanging.

### 7.3 Dashboard

- New page **Provenance** (`/p/:pid/provenance?path=`): a path picker (files that appear in Changes), then the file with a
  gutter. Blocks are marked with who (an icon and a word, never colour alone: agent / human / not observed), the headline,
  time and a link to the Change. A summary line gives the three counts for the file.
- **Change detail** file rows get a "Provenance" link to that file.
- Tokens only from `tokens.css`; IBM Plex; no side stripes; WCAG 2.2 AA in both themes; stable test ids. The file view is
  scrollable, so it is a focusable labelled region. A text-only table view of the blocks exists (as for charts).
- Copy states what was checked and the limits, next to the numbers.

## 8. Security, privacy and rules check

| Rule (CLAUDE.md) | How this spec meets it |
|---|---|
| Never store or sync prompts or diffs | Only keyed 8-byte fingerprints are stored, locally. No line text in the spool, ledger, audit trail, logs or API. Fingerprints are not in the sync allowlist and not sent anywhere. |
| No PII value, secret, prompt text or command argument in records | A secret in a line is fingerprinted, not stored; a keyed hash does not reveal it. Headlines come from the existing redacted summary. |
| Hot path stdlib only, no network, no SQLite writes | Capture is `hashlib`/`hmac` plus a spool append. Ingest does the DB work. |
| Hooks fail open | A failure in capture is swallowed and logged. Nothing in this feature can exit non-zero from a hook. |
| Never UPDATE/DELETE audit rows | `provenance.reported` is a new event. Purge removes `line_prints` rows (ledger data), and the audit trail records the purge as counts. |
| Repo files are untrusted | Blame and diff run through `gitutil`; paths and refs validated; no symlink traversal; caps and time budgets. |
| Say what was checked | Reports always list `agent`, `human` and `not observed` separately and state the limits. |
| Never hardcode prices | Cost comes from the existing ledger figures. |

Erasure (DPDP): `seen purge` adds `LinePrint` to its child tables so erasing a change or a project removes its
fingerprints. The Docker snapshot copies the ledger as it does today (same machine, same protections).

## 9. Failure modes and honest limits

| Situation | What the report shows |
|---|---|
| Agent wrote the line through Bash (`sed`, formatter, generator) | `human` or `not observed`, not `agent` |
| A person edited an agent line | `human` (the fingerprint no longer matches) |
| A person retyped an agent line exactly | `agent` (content is identical; unavoidable) |
| Agent line moved or file renamed | still `agent` (blame `-M -C` and the path at the blamed commit) |
| Squash or rebase | still `agent` (content-based) |
| Code from a teammate's machine | `not observed` unless the same ledger saw it (v2 addresses this) |
| Two lines identical in one file written by different requests | the tie-break in 6.2 |
| Reformatting that changes a line's text (quotes, wrapping) | the line becomes `human`; whitespace-only changes survive |

## 10. Acceptance criteria

Measured on a scenario suite built from scratch git repos driven by the existing replay helper (`tests/helpers.Replay`):

1. **Precision.** On repos with only human commits, 0 lines are `agent`. Across all scenarios, at least 99% of lines
   marked `agent` were typed by the agent.
2. **Recall.** At least 90% of unmodified Edit/Write/NotebookEdit-authored lines surviving at HEAD are `agent`,
   including after an in-turn commit, a later human commit, a squash, a rebase and a rename.
3. **Honesty.** Bash-generated files never come out `agent`; pre-Seen code comes out `not observed`.
4. **Hot path.** Capture adds at most 5 ms p50 for a 200-line edit (`perf` marker; skipped in containers as today).
5. **Read path.** `seen blame` on a 2,000-line file in under 1 s; `seen pr-report` on a 50-file range in under 3 s.
6. **Gates.** Every gate in CLAUDE.md passes, including `gen_openapi --check`, axe in light and dark on desktop and phone,
   reflow at 320 px, and the CSP-violation listener on the new page.
7. **Safety.** `?path=../x`, a symlinked path, a ref starting with `-`, a 50 MB file and a binary file are each refused
   or capped, with tests.

v1.1 (after v1 is accepted): survival per change (share of its lines still at HEAD), an Overview tile "agent-written
lines at HEAD" computed from a cached per-file result keyed by blob SHA, and `provenance prune`.

## 11. Later (not v1)

- **v1.2:** fingerprint Edit/Write inputs found in transcripts so `seen import` history gets provenance.
- **v2, sharing with CI and teammates:** write aggregated, metadata-only provenance records as `git notes` under
  `refs/notes/seen`, pushed with the branch, so a GitHub Action can render and enforce the PR report. Needs owner
  decisions on which fields may travel (see below). Fingerprints and headlines would not.
- **Bash coverage:** only if the spike shows a tree-diff fallback keeps precision above 99%.

## 12. Task breakdown (test first, one PR per task, task ID in each commit)

| ID | Task | Gate |
|---|---|---|
| PV-0 | **Spike** `spikes/provenance/`: record a MultiEdit payload fixture; compare Method A (tool inputs) with Method B (tree diff) on scripted scenarios; report precision and recall. Output a note in `docs/adr/` | decision recorded |
| PV-1 | Fingerprint, normaliser, trivial-line rule, and the Edit/Write/MultiEdit/Notebook extractors (pure functions, unit tests first, incl. multiset difference for Edit) | pytest, ruff, mypy |
| PV-2 | Hook capture (`prints` spool event), caps, config flag, fail-open, perf test; `test_ner` import list unchanged | + perf marker |
| PV-3 | Migration `0006`, ingest into `line_prints`, purge child table, `LinePrint` model, migration test with data | + migration test |
| PV-4 | Porcelain parser and attribution (6.1 to 6.5) against recorded fixtures; scenario suite for acceptance 1 to 3 | pytest |
| PV-5 | `seen blame` (text and JSON) | CLI tests |
| PV-6 | `seen pr-report` (diff parser, aggregation, `--fail-on`, md/json); then `--post` with confirmation and the audit event | CLI tests |
| PV-7 | API routes, schemas, safety tests, OpenAPI regeneration, fixtures | `gen_openapi --check`, pytest |
| PV-8 | Provenance page and Change-detail link, unit tests, Playwright, axe, 320 px reflow | web gates |
| PV-9 | Docs: README, TESTING.md part, CHANGELOG, `schema.md`, PRODUCT/DESIGN notes, ADR 0018, plan note | review |
| PV-10 | Opt-in real-Claude e2e: create a file, `seen blame` shows it as `agent` | `-m e2e` |

Reinstall note: a newer `seen-hook` writes `prints`; an older ingest ignores it, and an older hook writes none. After
the migration, reinstall the CLI so hook and ledger agree (existing gotcha).

## 13. Decisions needed from the owner

1. **Capture method.** Tool inputs only (this spec), or also a tree-diff fallback for Bash? Recommendation: inputs only
   in v1, decide the fallback after PV-0.
2. **`--post` in v1?** It is the only outward-facing action. Recommendation: include it, behind confirmation, with counts
   only in the audit event.
3. **Retention.** Keep fingerprints as long as the ledger rows they belong to (recommended), or prune on a shorter schedule?
4. **v2 sharing.** Which metadata may travel in git notes: request counts, session count, model, skills with approval
   status, rule results? Cost and any text (headlines) are proposed as excluded.
5. **Trivial-line threshold.** 10 alphanumerics is a starting value; tune against PV-0 data.
