# Spec: Provenance ("git blame for AI")

Status: implemented, 2026-10-20. This text describes what was built (tasks PV-0 to PV-10). ADR 0018 records the
capture method and the tool set; ADR 0019 (blame argument order) is still `proposed` for the owner.

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
  `not observed`, never guessed. The PV-0 spike showed a tree-diff fallback loses precision when a person edits during a
  turn (ADR 0018), so there is none.
- No line attribution for notebooks. A notebook cell is stored as one JSON line, so `.ipynb` lines never match a
  fingerprint. `seen blame` and the page say so. This is a stated v1 limit.
- No identification of *which person* wrote a human line. Provenance says "not an agent", nothing more.
- No dashboard "agent share of the codebase" tile. Planned for v1.1 once survival is measured (section 10).

## 3. How it works (summary)

```
capture   PostToolUse(Edit|Write|NotebookEdit)  ->  keyed fingerprints of the lines the agent *added*
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

Where: the existing `PostToolUse` hook, for `Edit`, `Write` and `NotebookEdit`. Claude Code 2.1.304 has no `MultiEdit`
tool (ADR 0018). It already appends a `tool` spool line; it additionally appends one `prints` line, and only when the call
has at least one non-trivial added line (`capture` records nothing otherwise):

```json
{"ev": "prints", "tool_use_id": "...", "path": "src/a.py", "fps": ["a1b2...16 hex", "..."], "n": 42}
```

What is fingerprinted (the lines the agent *added*):

| Tool | Added text |
|---|---|
| `Write` | every line of `content` |
| `Edit` | lines of `new_string` that are not lines of `old_string` (multiset difference by normalised line) |
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
transaction as `change_files`.

Baseline subtraction (PV-4b): a `Write` over an existing file would fingerprint every line of
`content`, including lines a person already had. At ingest, the fingerprints of the file as committed at the turn's
`head_before` are subtracted, so only lines NEW relative to that baseline are stored. The residual limit is in section 9.

Unknown or malformed `prints` lines are ignored (an older ingest ignores the whole event type, so mixed versions are safe).

## 6. Attribution (read side)

### 6.1 Blame

`git blame --porcelain --no-textconv -w -M -C --end-of-options -- <path> <rev>`, run through `seen_core.gitutil` (repo files
and git config are untrusted input). The argument order is the form that works on git 2.54; the order first written in
this spec failed (ADR 0019, still `proposed` for the owner). `-w` ignores whitespace-only changes, `-M -C` follow moved and
copied lines. The porcelain output gives, per line: the blamed commit, that commit's committer time, the file name *at that
commit*, and the text. Output is read through `gitutil.run_raw`, with no newline translation, because a lone CR in a file
would otherwise forge a porcelain header. `gitutil` neutralises git output encodings, textconv and diff drivers, and
`blame.ignoreRevsFile`.

The parser is strict and fails closed: output it cannot parse gives the reason `unparseable blame output` and every line is
`not observed`. It also checks that the number of parsed lines equals the number of lines in the blob. It is written
test-first against recorded porcelain output (including renames, boundary commits, CRLF and non-UTF-8 lines).

### 6.2 Per-line rule

For each line with text `t` blamed to commit `c` at path `p` (the path at `c`):

1. If `t` is trivial, defer to 6.3.
2. Look up `fp(t)` in `line_prints` for `(project, p)`. No row: the line is **human**, unless 6.4 says otherwise.
3. Several rows (the same line written by several requests): pick the change with the greatest `ended_at` that is not
   later than `c`'s commit time (the line existed when committed). If none, pick the earliest change after it (written,
   then committed later by a person). This is the tie-break and it is deterministic.
4. The result is `agent` with that change id.

### 6.3 Trivial lines

A trivial line is attributed only by adjacency, read conservatively: it is `agent` (change X) when the nearest non-trivial
line above and the nearest non-trivial line below, overall, are both in the same blamed commit as the trivial line and both
`agent` for the same change X. If the nearest non-trivial line is in another commit or is not `agent`, the line is `human`.

Blank lines are reported as `neutral` and left out of every percentage. This avoids window fingerprints that break at the
edge of every edit.

### 6.4 "Not observed"

A line is `not observed` rather than `human` when Seen could not have seen it:

- its blamed commit is older than the project's first recorded change (the code predates Seen), or
- its blamed commit time falls inside a gap window, or
- the file is binary, over 1 MB or over 20,000 lines, or untracked.

A gap window is `[session.started_at, session.ended_at or the last audit event time of that session, other than the `session.incomplete` marker itself]` for every session that
has a `capture.gap` or `session.incomplete` event. A gap window turns only a line that would otherwise be `human` into
`not observed`; it never changes an `agent` line. A blamed commit older than the first recorded change (floored to whole
seconds) is `not observed` even when a fingerprint matches.

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
               [--fail-on rule-missed|pii-high|unapproved-skill]... [--post [--yes]]
seen provenance prune --dry-run | --yes        # drop prints for deleted files (v1.1, not built)
```

`seen blame` prints, per block: line range, who, the headline, time (IST), model. `--json` is the same data plus the blocks'
skills and PII state, and never any line text. For a `.ipynb` file it prints a note that notebooks are not line-attributed.
A path that is unsafe, untracked or fails blame exits 2 with a one-line reason.

`seen pr-report` (all local, read-only unless `--post`):

1. Diff `BASE...HEAD` (merge-base) with `git diff --unified=0`, fixed prefixes and no colour; collect the added lines per
   file. The result is cross-checked against `git diff --numstat`; a mismatch fails closed (exit 2).
2. Attribute each added line by content (6.2), so squashed and rebased history works. Lines are looked up at the path
   in `HEAD`; renames use `git diff -M`. Range mode has no per-line commit time, so when several changes match a line the
   one with the greatest `ended_at` wins. An added line with no match is `human`, which is an UPPER BOUND (it includes code
   Seen did not see), except when the head commit predates the first recorded change, where it is `not observed`.
3. Aggregate: added lines by `agent` / `human` / `not observed`, share of `agent`, files, the requests that produced
   them (headline, time, model), sessions, skills run with their approval status *at the time they ran*, rule results,
   and the PII state of those changes with the sentence of what was checked (the existing `PII_CHECKED` text). Changes
   whose PII check did not run are counted ("n requests not checked"), and the state is never shown as "none" while any
   request is unchecked. A request's headline comes only from the assistant summary, never from the prompt-derived request
   line; with no summary the headline is "Changed N files in <areas>".
4. Cost (API-equivalent) is included unless `--no-cost`.
5. `--fail-on` makes the exit code non-zero when any listed condition holds (rule missed, high-confidence PII in a
   contributing change, a skill that was not approved). Without it the exit code is 0.
6. `--post`: shows the rendered comment, asks for confirmation (unless `--yes`), then calls `gh pr comment` for the
   branch's PR. It is the only network action. It writes an audit event `provenance.reported` with counts only (lines,
   requests), never headlines or text. It refuses unless `--head` is the checked-out branch's HEAD, refuses without a TTY
   unless `--yes`, and `--post` with `--format json` is a usage error.
7. Range mode excludes trivial lines from the percentages (and counts them as neutral), because adjacency (6.3) needs blame times, which range mode does not have.
8. Every model-derived string (headline, model, skill name) is placed in an inline code span in the Markdown, and control
   characters are stripped from it.

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
| `GET /api/projects/{pid}/provenance/file?path=&rev=` | `{path, rev, counts {agent, human, not_observed, neutral}, truncated, reason, blocks}`; each block is `{start, end, who, change_id, headline, started_at, model, skills, pii_state}` as in 6.5 |
| `GET /api/projects/{pid}/provenance/range?base=&head=` | the `pr-report` data as JSON |

Both are reads (no audit event, like other reads) and return no line text. Failure mapping:

| Case | Response |
|---|---|
| Unsafe path or revision (absolute, `..`, symlink out of the repo, a ref that does not match the safe pattern) | 422 with a fixed detail (`unsafe path`, `unsafe revision`); the input is never echoed |
| Not tracked, no HEAD, blame failed, unknown ref, unreadable diff, project has no repo on this machine | 404 with the reason |
| Binary file, or over 1 MB or 20,000 lines | 200 with `reason` set and no blocks |
| Budget timeout (default 5 s) | 200 with `truncated: true` and the blocks found so far |

Headline text is run through `clean()` (control characters stripped) everywhere it is shown. Git runs through `gitutil`
with `--end-of-options`.

### 7.3 Dashboard

- New page **Provenance** (`/p/:pid/provenance?path=`): a path field with a datalist of files that appear in Changes, then
  the file as blocks. Each block is marked with who (an icon and a word, never colour alone: agent / human / not observed),
  the headline, time and a link to the Change. A summary line gives the counts for the file.
- States: nothing chosen (empty state), loading, an error box, a 404 reason shown as a note, `reason` shown as "No lines
  attributed: <reason>", `truncated` shown as a "result is partial" warning, and a notebook note ("Notebook files are not
  line-attributed").
- **Change detail** file rows get a "Provenance" link to that file.
- Tokens only from `tokens.css`; IBM Plex; no side stripes; WCAG 2.2 AA in both themes; stable test ids. The block list is
  one scroll region, a focusable labelled region. A text-only table view of the blocks exists (as for charts).
- Copy states what was checked and the limits, next to the numbers: "Not observed means Seen could not have seen who wrote
  the line; it is not a claim that a person wrote it."

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
| A `Write` over a file that held a person's UNCOMMITTED lines at turn start | those lines are credited to the agent: they are not in `head_before`, so baseline subtraction cannot drop them |
| An `Edit` that re-adds or moves a line that was in the baseline | not credited to the agent (the line is subtracted as already present) |
| A file the agent wrote and a person then renamed inside the reviewed range | `human` in `pr-report`: fingerprints are keyed by the path at write time, and range mode uses the final path |
| A notebook (`.ipynb`) | not line-attributed: a cell is one JSON line, so no line matches |
| A `Write` or `Edit` whose added lines are all trivial | nothing is recorded; such lines are only ever attributed by adjacency (6.3) |

## 10. Acceptance criteria

Measured on a scenario suite built from scratch git repos driven through the real hook (`tests/provenance/test_scenarios.py`,
11 scenarios). Results on 2026-10-20 (tp/fp/fn counted over non-Bash lines):

| Criterion | Target | Measured |
|---|---|---|
| 1. Precision | 0 `agent` lines on human-only repos; at least 99% of `agent` lines typed by the agent | 70 true positives, 0 false positives: 100%. The human-only repo has 0 `agent` lines |
| 2. Recall | at least 90% of surviving Edit/Write-authored lines are `agent`, across in-turn commit, later human commit, squash, rebase, rename, a person's edits and a Write over a person's file | 70 of 71: 98.6%. The one miss is a 9-alphanumeric line at the edge of an agent block (threshold scenario) |
| 3. Honesty | Bash-generated files never `agent`; pre-Seen code `not observed` | 0 Bash-generated lines `agent`; 0 pre-Seen lines wrong, asserted in every scenario |
| 4. Hot path | at most +5 ms p50 for a 200-line edit | `perf` marker test in `tests/provenance/test_capture_hook.py` (skipped in containers). No number from the perf suite is recorded beyond that test's 5 ms assertion on `capture()` alone |
| 5. Read path | `seen blame` on 2,000 lines under 1 s; `pr-report` on 50 files under 3 s | `pr-report` on 50 files: `perf` marker test (`test_fifty_file_range_under_3s`). The 1 s blame figure has no dedicated timing test; the 5 s API budget bounds it. The final reviewer measured the `seen blame` read path on a 2,000-line committed file with a scratch script: median about 46 ms, of which about 13 ms is `git blame` |
| 6. Gates | every CLAUDE.md gate | pass, including `gen_openapi --check`, axe, 320 px reflow and the CSP listener |
| 7. Safety | `../x`, symlink, ref starting `-`, 50 MB file, binary file refused or capped | each has a test |

Excluded from the numbers: Bash-authored lines (never `agent` by design, so not counted as misses), notebooks (the v1
limit above), and the uncommitted-lines residual scenario (section 9). The opt-in real-Claude test
(`uv run pytest -m e2e tests/e2e -k pv10`) has a session create a file with the Write tool and checks that `seen blame`
reports `agent` for every non-trivial line and cites a change id.

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
| PV-0 | **Spike** `spikes/provenance/`: check the tool set (no MultiEdit in 2.1.304); compare Method A (tool inputs) with Method B (tree diff) on scripted scenarios; report precision and recall. Output a note in `docs/adr/` | decision recorded |
| PV-1 | Fingerprint, normaliser, trivial-line rule, and the Edit/Write/Notebook extractors (pure functions, unit tests first, incl. multiset difference for Edit) | pytest, ruff, mypy |
| PV-2 | Hook capture (`prints` spool event), caps, config flag, fail-open, perf test; `test_ner` import list unchanged | + perf marker |
| PV-3 | Migration `0006`, ingest into `line_prints`, purge child table, `LinePrint` model, migration test with data | + migration test |
| PV-4 | Porcelain parser and attribution (6.1 to 6.5) against recorded fixtures; scenario suite for acceptance 1 to 3 | pytest |
| PV-4b | Baseline subtraction at ingest: a Write stores only lines new relative to `head_before` | pytest |
| PV-4c | Hardening of blame and the diff reader: strict parser, `run_raw`, git config neutralised, count cross-checks | pytest |
| PV-5 | `seen blame` (text and JSON) | CLI tests |
| PV-6 | `seen pr-report` (diff parser, aggregation, `--fail-on`, md/json); then `--post` with confirmation and the audit event | CLI tests |
| PV-7 | API routes, schemas, safety tests, OpenAPI regeneration, fixtures | `gen_openapi --check`, pytest |
| PV-8 | Provenance page and Change-detail link, unit tests, Playwright, axe, 320 px reflow | web gates |
| PV-9 | Docs: README, TESTING.md part, CHANGELOG, `schema.md`, PRODUCT/DESIGN notes, ADR 0018, plan note | review |
| PV-10 | Opt-in real-Claude e2e: create a file, `seen blame` shows it as `agent` | `-m e2e` |

Order of work was PV-4, PV-4b, PV-4c, then PV-5. Reinstall note: a newer `seen-hook` writes `prints`; an older ingest ignores it, and an older hook writes none. After
the migration, reinstall the CLI so hook and ledger agree (existing gotcha).

## 13. Decisions

Taken with the recommended defaults (2026-10-20):

1. **Capture method.** Tool inputs only; no tree-diff fallback for Bash (ADR 0018).
2. **`--post` in v1.** Included, behind confirmation, with counts only in the audit event.
3. **Retention.** Fingerprints are kept as long as the ledger rows they belong to.
4. **Trivial-line threshold.** Stays at 10 alphanumerics (ADR 0018).

Open for the owner: v2 sharing is still undecided (cost and any text, such as headlines, are proposed as excluded). ADR 0019 stays `proposed` (blame argument order). The closed-stdin refusal and a few minor findings
are tracked in the review ledger, not here.
