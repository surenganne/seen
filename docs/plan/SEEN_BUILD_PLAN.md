# Seen: Build Plan for a Coding Agent

> **Amended 2026-10-20 (ADR 0017):** project memory (the memory service, injection, the edit gate, `seen memory`, the Memory page,
> the `change_memories` table) was removed, and a Timeline page was added. Memory text below is history, not a task list.

> **Note 2026-10-20 (provenance):** `seen blame`, `seen pr-report` and the Provenance page were added. The built design is in
> `docs/specs/provenance.md` (status: implemented) and the capture decision is in `docs/adr/0018-provenance-capture.md`.

**Naming and packaging (decided)**

| Thing | Value |
|---|---|
| Product name | Seen. Tagline: "Nothing your agents do goes unseen." |
| CLI command | `seen` |
| PyPI distribution | `seen-cli` (the bare `seen` is taken). Install with `uv tool install seen-cli` |
| Claude Code plugin name | `seen`, in a marketplace named `seen-tools` |
| Python import packages | `seen_core`, `seen_cli`, `seen_local`, `seen_team` |
| Hook binary | `seen-hook` |
| Hidden folders | `<repo>/.seen/` and `~/.seen/` |
| Repo and org | To be created. The GitHub name and domains were not checked, so check them first. Expect a modifier such as `getseen` |

"Seen" is a common word. Keep every identifier prefixed (`seen_`, `seen-`) so searches, imports and logs stay unambiguous. `seen doctor` must warn if another executable named `seen` appears earlier on the PATH.

Icon: the owner is supplying the final icon set. Until then `assets/brand/` holds placeholder animated eyes (`eyes.svg`). The dashboard uses whatever is in `assets/brand/`, so swapping the files is enough. Keep the file names, and keep an `idle` and an `alert` variant (see section 13).

Product name: **Seen** (display strings live in `packages/core/src/seen_core/brand.py`).
Target: **Claude Code only** for v1. Other CLI tools come later.
Owner: Surendra, Enterprise Architect, AI CoE.

---

## 0. How to use this document

1. Read sections 1 to 6 fully before writing code.
2. Do **Phase 0 first**. It tests the assumptions in section 3. Do not start Phase 1 until `docs/hooks-findings.md` exists and every assumption is marked confirmed, changed, or dead.
3. Work one task at a time, in order. Each task has an ID (for example `P1-3`) and an acceptance test. A task is done only when its acceptance test passes.
4. When a fact about Claude Code behaviour is not in a recorded fixture, do not guess. Record a real payload first, then code against it.
5. Phases 0 to 4B are specified in detail. Phases 5 and 6 are outlines, because the team design should change after what Phases 0 to 4 teach us.

---

## 1. What we are building

A plugin for Claude Code, plus a local dashboard, that keeps a per-project ledger of what AI agents change in a codebase.

For every agent turn ("change") it records:

- the files touched and lines added and removed
- a short summary and the original prompt (stored locally only)
- tokens used, split into input, output, cache read and cache write
- cost, as an API-equivalent figure from a versioned price table
- which memory items were loaded before the first edit
- which skills ran, in order, with the version hash of each
- whether required-skill rules were met
- whether personal data (PII) or secrets entered the model's context, where from, and where it went

It also:

- stores **project memory** and loads it into every session
- blocks file edits when memory was not loaded
- keeps an **inventory of every installed skill** and flags changed or unreviewed ones
- keeps a **tamper-evident audit trail** of every action, decision and approval (section 11A)
- detects and shows **PII exposure** during task execution, without ever storing the PII itself (section 11B)
- shows all of this in a dashboard, per project

Later (Phase 5): sync metadata to a team server so a team can see a project-level view.

### Non-goals for v1

- Other tools (Codex, Cursor and so on)
- Windows support
- Per-file cost (tokens belong to a turn, so show line counts per file, never invented dollars)
- Proving a skill influenced the output (we can only show it was loaded)
- Storing diffs or prompts on any server

---

## 2. Principles that override convenience

1. **Hooks fail open.** Any exception inside a hook exits 0 and logs to `~/.seen/log/hook.log`. The only hooks allowed to exit 2 are the memory gate, the blocked-skill check, PII `block` mode, and the optional policy enforcement at Stop.
2. **The hot path is tiny.** Hooks that run on every tool call use only the Python standard library and append one line to a spool file. No SQLite writes, no network, no heavy imports in the hot path. Target under 100 ms per hook call.
3. **Local first.** Everything works with no server. The server is an opt-in sync target.
4. **Code and prompts stay on the machine.** Only paths, line counts, tokens, cost, skill names and hashes may sync, and only if the user turns each on.
5. **Numbers must be checkable.** File lists reconcile to git. Token totals reconcile to the transcript.
6. **Memory is plain files in a hidden folder.** No index, no server, no database copy. Hooks read the files directly. Reviewed in pull requests, checked against git for staleness.
7. **The audit trail is append-only and holds no content.** Hashes, ids, counts and paths only. No prompt text, diffs, command arguments or PII values.
8. **Seen never stores a PII value.** It stores type, count, source and a keyed fingerprint. Prompts are stored redacted by default, because a stored prompt is itself a PII store.

---

## 3. Assumptions register (Phase 0 must settle these)

| ID | Assumption | Confidence | Spike |
|---|---|---|---|
| A1 | Plugin hooks are declared in `hooks/hooks.json` and run alongside user hooks. Command hooks get a JSON payload on stdin with `session_id`, `transcript_path`, `cwd`, `hook_event_name`, and for tool events `tool_name` and `tool_input`. | Confirmed in docs; record real payloads anyway | P0-1 |
| A2 | `Stop` payload includes `stop_hook_active`. A Stop hook can block stopping so Claude continues. | Confirmed in docs; test the loop guard | P0-6 |
| A3 | The transcript JSONL contains per-message `usage` (input, output, cache read, cache creation) and `model`. Streaming may repeat a message, so dedupe by message id. | Likely | P0-3 |
| A4 | Skill invocations appear as tool calls named `Skill` in PreToolUse/PostToolUse and in the transcript. Slash-command skills appear in `UserPromptSubmit` prompt text. | Likely, **unverified** | P0-4 |
| A5 | SessionStart and UserPromptSubmit hook output can add context for the model. Need the exact output format (plain stdout versus a JSON field). | Likely | P0-2 |
| A6 | PreToolUse exit code 2 blocks an edit tool call and shows stderr to the model. | Confirmed in docs; test on `Edit`, `Write`, `MultiEdit` | P0-5 |
| A7 | A skill folder can be hashed reliably (content plus bundled scripts, ignoring VCS and build junk). | Likely | P0-7 |
| A8 | Token totals computed from the transcript match Claude Code's native OpenTelemetry output within 2%. | Unknown | P0-8 |
| A9 | Plugin install via a git marketplace works, and a repo's `.claude/settings.json` can enable it for contributors after the trust dialog. | Confirmed in docs | P0-9 |
| A10 | The transcript JSONL contains the full content of tool results (file reads, Bash output, MCP results), so a Stop-time scan sees what the model saw. | Likely, **unverified** | P0-12 |
| A11 | `UserPromptSubmit` exit code 2 blocks the prompt. A JSON `systemMessage` field shows a warning to the user without reaching the model. | Likely, **unverified** | P0-13 |
| A12 | `PreToolUse` on `Read` can deny a file read before its content enters the context. | Likely, **unverified** | P0-13 |

If A4 fails, cut the skills audit to the inventory screen only and tell the owner.
If A10 fails, PII detection covers prompts, `Read` pre-scans and diffs only. Tell the owner, because the "what did the model see" claim is then weaker.

---

## 4. Architecture

```
Claude Code session
   |  hooks (stdin JSON)
   v
plugin/bin/seen-hook   (stdlib only, hot path)
   |  append line
   v
~/.seen/spool/<session_id>.jsonl      ~/.seen/snap/<session_id>.json
   |
   |  at Stop: process spool + transcript + git diff
   v
seen_core.ingest  --->  ~/.seen/ledger.db  (SQLite)   <--- seen CLI
                                  ^                     ^
                                  |                     |
                  local_server (FastAPI) --- web (React) |
                                                        |
                       hooks read memory files directly <--+
                                  |
              <repo>/.seen/memory/*.md, policies.yaml, skills.lock.json

Alongside the ledger:
  ingest --> ~/.seen/audit.db   (append-only, hash-chained; section 11A)
  ingest --> pii_findings in ledger.db (types and counts only; section 11B)

Phase 5:  outbox --> team_server (FastAPI + Postgres) --> same web app
          audit chain heads --> team_server (off-machine anchor)
```

Key point: the **web app and the API contract are shared** between the local server and the team server. The local server is the team server's read API on top of SQLite.

---

## 5. Tech stack

| Layer | Choice | Why |
|---|---|---|
| Language (backend, plugin) | Python 3.11+ | Matches owner's stack. Hot-path hook uses stdlib only. |
| Package and env management | `uv`, workspace layout | Fast, one lockfile for all Python packages |
| API | FastAPI, Pydantic v2 | Typed contract, OpenAPI for the web client |
| ORM and migrations | SQLAlchemy 2.0, Alembic | One model layer for SQLite (local) and Postgres (team) |
| CLI | Typer | Simple, typed |
| Audit hashing | `hashlib` SHA-256, canonical JSON (sorted keys) | Stdlib, verifiable by anyone with a script |
| PII detection | Stdlib regex plus validators (Luhn, Verhoeff, IBAN mod 97) in hooks; optional Presidio + spaCy as an `pii-ner` extra at ingest only | Hot path stays fast. NER is heavy and off by default |
| Glob matching | `pathspec` (gitwildmatch) | Same semantics as `.gitignore`, for policy rules |
| Local DB | SQLite with WAL | Zero setup |
| Team DB (Phase 5) | PostgreSQL 16 | Multi-user, retention |
| Web | React 18, Vite, TypeScript (strict) | Owner's stack |
| Web data | TanStack Query, React Router | Cache, routing |
| Web styling | Tailwind CSS with CSS variables for tokens | Fast, themeable |
| Charts | Recharts | Enough for bars, lines, sparklines |
| API client | `openapi-typescript` generated from FastAPI schema | No hand-written types |
| Tests (Python) | pytest, pytest-asyncio, hypothesis for parsers | Fixtures from real payloads |
| Tests (web) | Vitest, Testing Library, Playwright | Unit and click-through |
| Lint and types | ruff, mypy (strict on core), eslint, tsc | CI gates |
| Packaging | Plugin as a git marketplace; `seen` Python package via `uv tool install` | Matches how Claude Code installs plugins |
| Team deploy (Phase 5) | Docker Compose first, AWS later (ECS or EC2) | Self-hostable for clients |
| CI | GitHub Actions | Lint, type, test, build |

Pin exact versions when installing. Do not copy version numbers from this document.

---

## 6. Repository structure

```
seen/
├── README.md
├── CLAUDE.md                      # short rules for agents (see section 16)
├── PLAN.md                        # this file
├── assets/brand/                  # eyes.svg (animated), eyes-static.svg, eyes-mono.svg, icon-512.png, icon-192.png, favicon-32.png, social-preview.png
├── pyproject.toml                 # uv workspace root
├── uv.lock
├── .github/workflows/ci.yml
├── .claude-plugin/
│   └── marketplace.json           # lists the plugin below
├── plugin/                        # what users install
│   ├── .claude-plugin/plugin.json
│   ├── hooks/hooks.json
│   ├── bin/seen-hook           # executable, stdlib only
│   ├── commands/
│   │   └── status.md              # /seen:status
│   └── skills/
│       └── using-seen-memory/SKILL.md
├── packages/
│   ├── core/
│   │   └── src/seen_core/
│   │       ├── brand.py
│   │       ├── paths.py           # ~/.seen layout
│   │       ├── project.py         # project identity from git
│   │       ├── gitdelta.py        # snapshots and deltas
│   │       ├── transcript.py      # usage parsing
│   │       ├── pricing.py
│   │       ├── ingest.py          # spool -> ledger
│   │       ├── db/                # models, session, alembic/
│   │       ├── memory/            # read files, select, staleness, inject (no index)
│   │       ├── skills/            # scan, hash, versions, lockfile
│   │       ├── policy.py
│   │       ├── audit/             # chain, append, verify, export, events catalogue
│   │       ├── pii/               # detectors, validators, scan, allowlist, fingerprint
│   │       └── redact.py          # span redaction, home-dir redaction
│   ├── cli/src/seen_cli/       # `seen` command, distributed as `seen-cli`
│   ├── local_server/src/seen_local/   # FastAPI + serves web build
│   └── team_server/src/seen_team/     # Phase 5
├── web/
│   ├── package.json
│   ├── src/
│   │   ├── api/                   # generated client
│   │   ├── components/
│   │   ├── pages/                 # Projects, Overview, Changes, Change, Memory, Skills, Audit, Settings
│   │   ├── styles/tokens.css
│   │   └── main.tsx
│   └── e2e/                       # Playwright
├── spikes/                        # Phase 0 scripts, throwaway
├── tests/
│   ├── fixtures/
│   │   ├── hook_payloads/         # recorded real payloads, one file per event
│   │   ├── transcripts/           # real transcript samples (scrubbed)
│   │   ├── repos/                 # tiny git repos built by scripts
│   │   └── pii_corpus/            # labelled synthetic PII and non-PII samples, incl. Indian formats
│   └── e2e/                       # headless Claude Code runs (manual or nightly)
├── pricing/prices.json            # versioned; "verified": false until checked
├── deploy/
│   ├── docker-compose.team.yml    # Phase 5
│   └── Dockerfile.team
└── docs/
    ├── hooks-findings.md          # output of Phase 0
    ├── schema.md
    ├── pii-benchmark.md           # precision and recall per type, regenerated by CI
    └── adr/                       # one short file per decision
```

User data (not in the repo):

```
~/.seen/
├── ledger.db
├── audit.db                   # append-only audit chain (separate file on purpose)
├── audit-heads.log            # chain head per session end
├── secret.key                 # 0600, keys PII fingerprints, never synced
├── spool/<session_id>.jsonl
├── snap/<session_id>.json
├── log/hook.log
├── memory/<project_id>/*.md   # private, personal memory (never committed)
└── config.toml
```

Per-project data (committed to the user's repo, reviewed in PRs):

```
<repo>/.seen/
├── .gitignore                     # ignores local state (markers, cache)
├── memory/*.md
├── policies.yaml
├── pii.yaml                       # allowlist and custom PII rules
└── skills.lock.json
```

---

## 7. The plugin

### 7.1 Files

`plugin/.claude-plugin/plugin.json`

```json
{
  "name": "seen",
  "version": "0.1.0",
  "description": "Change ledger, project memory and skill audit for Claude Code."
}
```

`.claude-plugin/marketplace.json` (repo root): a marketplace named `seen-tools` with one plugin whose `source` is `./plugin`. Check the current marketplace schema in the Claude Code docs before writing it.

`plugin/hooks/hooks.json` (plugin hooks use the `{"hooks": {...}}` wrapper):

```json
{
  "description": "Seen capture, audit, PII scan and memory gate",
  "hooks": {
    "SessionStart":     [{"hooks":[{"type":"command","command":"${CLAUDE_PLUGIN_ROOT}/bin/seen-hook session-start"}]}],
    "UserPromptSubmit": [{"hooks":[{"type":"command","command":"${CLAUDE_PLUGIN_ROOT}/bin/seen-hook prompt-submit"}]}],
    "PreToolUse": [
      {"matcher":"Edit|Write|MultiEdit|NotebookEdit","hooks":[{"type":"command","command":"${CLAUDE_PLUGIN_ROOT}/bin/seen-hook pre-edit"}]},
      {"matcher":"Skill","hooks":[{"type":"command","command":"${CLAUDE_PLUGIN_ROOT}/bin/seen-hook pre-skill"}]},
      {"matcher":"Read","hooks":[{"type":"command","command":"${CLAUDE_PLUGIN_ROOT}/bin/seen-hook pre-read"}]}
    ],
    "PostToolUse": [
      {"matcher":"Edit|Write|MultiEdit|NotebookEdit|Skill","hooks":[{"type":"command","command":"${CLAUDE_PLUGIN_ROOT}/bin/seen-hook post-tool"}]}
    ],
    "Stop":       [{"hooks":[{"type":"command","command":"${CLAUDE_PLUGIN_ROOT}/bin/seen-hook stop"}]}],
    "SessionEnd": [{"hooks":[{"type":"command","command":"${CLAUDE_PLUGIN_ROOT}/bin/seen-hook session-end"}]}]
  }
}
```

Adjust matchers and the `Skill` entries after Phase 0 (A4).

### 7.2 What each hook does

| Event | Hot path (stdlib, fast) | Heavy work |
|---|---|---|
| `session-start` | Resolve project. Write `session_start` spool line. Run inventory scan (cached by folder mtime). Emit memory context for the model (format per A5). Write `memory_loaded` marker. | None |
| `prompt-submit` | Start a new turn: write `turn_start` spool line with prompt text, transcript line offset, and a git snapshot (`git diff --numstat HEAD`, untracked files, HEAD sha). Detect slash-command skills. Emit memory refresh if needed. Scan the prompt for PII (section 11B): record findings, and in `warn` or `block` mode show a warning or exit 2. Store the prompt redacted per `pii.store_prompt_text`. | None |
| `pre-edit` | Always allow edits under `.seen/memory/`. Otherwise check the `memory_loaded` marker for this turn, which the injection hook writes. If missing (injection failed or was skipped): print a message to stderr saying memory did not load and to read `.seen/memory/`, exit 2. Honour `gate=false` in config. | None |
| `pre-read` | Only in PII `block` mode: scan the first 256 KB of the target file with a 100 ms budget. If high-confidence PII is found and the path is not allowlisted, exit 2 with the reason. On timeout or size cap, allow and defer to the Stop-time scan. | None |
| `pre-skill` | Write `skill_start` spool line. If the skill is blocked in the lockfile: exit 2 with a reason. | None |
| `post-tool` | Append a tool event line (tool name, file path, skill name). | None |
| `stop` | Check `stop_hook_active`. | Run `ingest.finish_turn(session_id)`: compute file delta, parse transcript for tokens, price it, match skills, evaluate policies, write the change row, scan the turn's transcript slice and the added diff lines for PII and secrets, write `pii_findings`, convert spool lines into audit events. In enforce mode, if a required skill is missing, return a block decision with a reason (once per turn). |
| `session-end` | Close the session row. Append chain head to `audit-heads.log`. | Reconcile commit status for recent changes. Write `session.end`, or `session.incomplete` for sessions that never reached Stop. |

Every hook entry point is wrapped like this:

```python
try:
    main()
except Exception:
    log_exception()
    sys.exit(0)   # fail open (the gate returns 2 explicitly, never via exception)
```

---

## 8. Data model (SQLite via SQLAlchemy; same models in Postgres later)

```sql
projects(id TEXT PK, name TEXT, remote TEXT, root_path TEXT, created_at TEXT)
sessions(id TEXT PK, project_id TEXT, started_at TEXT, ended_at TEXT,
         tool TEXT DEFAULT 'claude-code', tool_version TEXT, user_id TEXT)
changes(id TEXT PK, project_id TEXT, session_id TEXT, seq INT,
        started_at TEXT, ended_at TEXT, duration_s INT,
        prompt_text TEXT, summary TEXT, model TEXT,
        tok_in INT, tok_out INT, tok_cache_read INT, tok_cache_write INT,
        cost_usd REAL, price_version TEXT,
        git_head_before TEXT, git_head_after TEXT,
        git_status TEXT,                 -- committed | uncommitted | reverted
        mem_state TEXT,                  -- loaded | missed | none
        mem_injected_tokens INT,
        pii_state TEXT,                  -- none | found | blocked
        pii_count INT, synced_at TEXT)
change_files(change_id TEXT, path TEXT, added INT, removed INT, PRIMARY KEY(change_id, path))
change_memories(change_id TEXT, memory_id TEXT, content_hash TEXT, PRIMARY KEY(change_id, memory_id))  -- memory_id = file id; no memories table, files are the only source
skills(id TEXT PK, kind TEXT, origin TEXT, path TEXT, scope_project_id TEXT,
       description TEXT, allowed_tools TEXT, first_seen TEXT, last_seen TEXT)
skill_versions(skill_id TEXT, hash TEXT, first_seen TEXT, approved_by TEXT,
               approved_at TEXT, PRIMARY KEY(skill_id, hash))
skill_invocations(change_id TEXT, ordinal INT, skill_id TEXT, hash TEXT,
                  trigger TEXT, PRIMARY KEY(change_id, ordinal))   -- model | user | subagent
policies(id TEXT PK, project_id TEXT NULL, title TEXT, paths_json TEXT,
         require_skill TEXT, mode TEXT)                             -- report | enforce
policy_results(change_id TEXT, policy_id TEXT, met INT, PRIMARY KEY(change_id, policy_id))
pii_findings(id TEXT PK, change_id TEXT, type TEXT, confidence TEXT,   -- high | medium | low
             count INT, distinct_count INT,
             source_kind TEXT,           -- prompt | file_read | tool_output | mcp | injected_memory | diff_added
             source_ref TEXT,            -- tool name and path only, home redacted, never command args
             destination TEXT,           -- model | network | repo | memory
             detector TEXT, status TEXT, -- open | test_data | allowlisted
             fingerprints_json TEXT)     -- keyed HMAC, local only, never synced, never the value
outbox(id INTEGER PK, kind TEXT, payload_json TEXT, created_at TEXT, attempts INT, sent_at TEXT)
```

`kind` for skills: `plugin | user | project | org | builtin | sideload`.

The audit trail has its own file and schema (section 11A), so ledger migrations and rebuilds cannot touch it.

---

## 9. Core algorithms

### 9.1 Project identity
1. `git config --get remote.origin.url` → lowercase, strip scheme, credentials, trailing `.git`.
2. `project.id = sha1(normalised_remote)[:12]`. No remote → `sha1(realpath of git toplevel)[:12]`.
3. For worktrees, use `git rev-parse --git-common-dir` so all worktrees map to one project.

### 9.2 Files touched (the source of truth)
- At `prompt-submit`: record `git diff --numstat HEAD`, `git ls-files --others --exclude-standard`, and line counts of untracked files.
- At `stop`: record the same again. Per path, `added = after.added - before.added` (clamp at 0, handle new files), same for removed.
- Use `post-tool` events only as a hint to catch changes the diff cannot see (for example a file edited and then reverted within the turn).
- Known limit: if the human edits files during the turn, those lines are counted. Document it.

### 9.3 Tokens and cost
- Record the transcript line offset at `prompt-submit`. At `stop`, read lines from that offset.
- Sum `usage` fields over assistant messages, deduped by message id. Use `message.model` for pricing.
- `cost = Σ tokens/1e6 × price` per type, using `pricing/prices.json`. Store `price_version` on the row.
- `prices.json` ships with `"verified": false`. Fill values from the provider's pricing pages when the owner confirms. Never invent prices.
- Cross-check against Claude Code's native OpenTelemetry output in a test (A8).

### 9.4 Summary
Use the first sentence of the assistant's final message, trimmed to 120 characters. Do not call a model from a hook.

### 9.5 Skill folder hash
SHA-256 over a sorted list of `(relative_path, file_sha256)` for all files in the skill folder, excluding `.git`, `node_modules`, `__pycache__`, `.DS_Store`. Do not follow symlinks outside the folder. Store the short hash (7 chars) for display and the full hash in the DB.

### 9.6 Policy evaluation
At `stop`: for each policy whose `paths` globs match any touched file, `met = required skill ran this turn`. Write `policy_results`. In `enforce` mode and only once per turn (check `stop_hook_active`), return a Stop block decision with the reason `Run <skill> before finishing, because this change touches <paths>.`

### 9.7 Memory staleness
A memory is **stale** if any change touched its `file_ref` after the later of `verified_at` and its source change time. `seen memory verify <id>` sets `verified_at = now`.

---

## 10. Memory spec (plain files, no server, no index)

**Where it lives**

| Scope | Path | In git? |
|---|---|---|
| Team memory | `<repo>/.seen/memory/*.md` | Yes by default, reviewed in PRs |
| Personal memory | `~/.seen/memory/<project_id>/*.md` | Never |
| Local state | `<repo>/.seen/.cache/` | No (ignored by `.seen/.gitignore`) |

Not the plugin root. Plugin updates replace that folder and it is shared across projects.

**File format** (one memory per file):

```markdown
---
id: vero-stt-primary
type: decision          # decision | convention | gotcha | context
file_ref: agent/stt.py  # optional
source_change: VR-02    # optional
verified_at: 2026-10-10T09:12:00Z
---
STT primary is Sarvam streaming. Batch STT is only a fallback when the websocket drops twice within 10 seconds.
```

**Injection** (`session-start` and `prompt-submit`, stdlib only):
1. Read all `*.md` from both folders. Parse front matter with a small stdlib parser. Skip and log invalid files.
2. Rank without an index: (a) `file_ref` matches a path in the prompt or in the current `git status`, (b) keyword overlap between the prompt and the text, (c) newest `verified_at`. Stale items are included but marked `[STALE]`.
3. Fill to the token budget (default 1,500, estimated as characters / 4). Emit in the format confirmed by A5.
4. Write the `memory_loaded` marker for this turn and the list of injected ids to the spool. Ingest writes `change_memories` from it.
5. Past about 200 files, add a one-file cache of parsed front matter in `.cache/`. Do not add it earlier.

**Writing memory (no MCP):**
- The bundled skill `using-seen-memory` tells the agent to save durable decisions, conventions and gotchas by writing a file into `.seen/memory/` with the front matter above and `verified_at` left empty.
- `pre-edit` always allows writes under `.seen/memory/`.
- `seen memory add|list|verify|archive` does the same from the CLI, and validates the format.
- Files without `verified_at` show as `unverified` in the dashboard until a human runs verify.
- Ingest flags invalid files (bad front matter, duplicate id) in the dashboard instead of failing.

**Staleness:** per 9.7, computed at read time from the `changes` and `change_files` tables. Nothing is stored.

**Gate:** the injection hook writes the marker itself, so the gate only fires when injection failed. It is a safety net, not a control. Do not spend time on it beyond P3-4.

**Dashboard:** the local server reads the files on request. The team server (Phase 5) receives memory metadata only (id, type, status, counts), never the text.

**Known risks:**
- Memory is text the model treats as instructions. A poisoned or careless memory file merged in a PR steers every developer's agent. Treat `.seen/memory/` as code under review. Codeowners rule recommended.
- Agent-written memory can be wrong. The `unverified` flag is the control, so make it visible.
- A committed memory folder is visible to anyone with repo access. Do not store secrets or client confidential data in it.

---

## 11. Skills audit spec

**Inventory scan** at `session-start`, cached by folder mtime. Look in:
- `~/.claude/skills/*/SKILL.md` (kind `user`)
- `<repo>/.claude/skills/*/SKILL.md` (kind `project`)
- the plugin cache under `~/.claude/plugins` (kind `plugin`, origin = plugin name and version)
- managed policy folders (kind `org`; find the real paths in the docs during Phase 0)
- anything loaded by `--plugin-dir` (kind `sideload`, detected from the session's plugin list; verify how in Phase 0)
- built-ins (kind `builtin`)

Parse `SKILL.md` front matter for `name`, `description`, `allowed-tools`.

**Invocation capture** from three sources, reconciled at `stop`:
1. `Skill` tool events from hooks (A4).
2. Slash-command match at `prompt-submit` (`^/([\w:-]+)` matched against the inventory).
3. `tool_use` blocks named `Skill` in the transcript.

Record `trigger` as `user`, `model` or `subagent`.

**Version status** (per skill): `approved` if its current hash is in `skills.lock.json`; `changed` if an earlier hash was approved but the current one is not; `unreviewed` if never approved; `blocked` if listed as blocked.

**Lockfile** `<repo>/.seen/skills.lock.json`:

```json
{ "approved": { "everything-claude-code:security-review": ["c09d1e7"] },
  "blocked":  ["quick-sql-helper"] }
```

**Policies** `<repo>/.seen/policies.yaml`:

```yaml
- id: pol-phi
  title: PHI redaction check on LLM code
  paths: ["llm/**"]
  require_skill: phi-redaction-check
  mode: report
```

Never sync skill content. Sync only name, source kind, and hash. Replace the user's home directory in paths with `~` before storing.

---

## 11A. Audit trail spec

Purpose: answer "who or what did what, in which project, when, under which rules, and can I show the record was not edited". The ledger is a working view that can be migrated and rebuilt. The audit trail is append-only.

**Storage:** `~/.seen/audit.db`, a separate SQLite file. One chain per install, all projects in it, filtered by `project_id` on read. SQLite triggers abort `UPDATE` and `DELETE` on the table. That stops bugs and accidents, not a determined person (see limits).

```sql
audit_events(seq INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT UNIQUE,
             occurred_at TEXT, recorded_at TEXT,
             actor_kind TEXT,     -- user | agent | hook | system
             actor_id TEXT,       -- configured user id; default is a hash of OS user + host, never the raw login
             project_id TEXT, session_id TEXT, change_id TEXT,
             type TEXT, subject TEXT, outcome TEXT,   -- ok | blocked | failed
             detail_json TEXT, prev_hash TEXT, hash TEXT)
```

`hash = sha256(prev_hash + canonical_json(all fields except hash))`. Canonical JSON means sorted keys, no whitespace, UTF-8. The first event uses 64 zeros as `prev_hash`.

**Event catalogue** (`detail_json` never holds content):

| Type | Written when | Detail holds |
|---|---|---|
| `session.start`, `session.end` | Session boundaries | Claude Code version, plugin version, hash of `config.toml`, hash of `skills.lock.json`, hash of `policies.yaml` |
| `session.incomplete` | A session has no Stop or SessionEnd | Last event `seq` |
| `capture.gap` | A hook errored or timed out | Hook name, error class. No message text |
| `turn.start`, `turn.end` | Each turn | Prompt SHA-256 and length, tokens, cost, git heads, file count |
| `memory.injected` | Injection ran | Memory ids, content hashes, token count |
| `gate.decision` | `pre-edit`, `pre-skill`, `pre-read` | allow or block, reason code |
| `file.changed` | Each turn | Path, lines added, lines removed |
| `tool.call` | Each hooked tool call | Tool name, target path (home redacted). For Bash: first token only |
| `skill.invoked` | Skill ran | Skill id, hash, trigger, approval status at that moment |
| `policy.result` | Stop | Policy id, met or missed |
| `pii.finding` | Stop-time or prompt scan | Finding id, type, count, confidence, destination |
| `approval.*` | Human action | Skill approved or blocked, memory verified or archived, PII marked as test data. Actor, subject, old and new state |
| `config.changed` | Settings edited | Key, old value, new value |
| `lockfile.changed`, `policies.changed` | Detected at session start | Old and new hash (catches edits made outside Seen, for example a git pull) |
| `export.created` | Audit export | Format, range, head hash |
| `sync.batch` | Phase 5 | Kind, count, server, acknowledgement |
| `audit.checkpoint` | Retention prune | Pruned range, last pruned hash |

**Rules:**
1. Never in an event: prompt text, diff content, command arguments, file content, PII values, secrets.
2. Hooks never write the database. They append to the spool with timestamps. `ingest` converts spool lines into events in order and assigns `seq`. Each batch runs under `BEGIN IMMEDIATE`, because several sessions can finish at the same time.
3. Every state-changing action in the CLI and local server calls `core.audit.append` in the same transaction as the change (lockfile write, memory verify, settings update). A CI test walks every POST, PUT and DELETE route and asserts at least one audit event was written.
4. The trail records its own gaps (`capture.gap`, `session.incomplete`). No events does not prove no activity.
5. `seen audit verify` recomputes the chain and prints the first break (`seq`, expected hash, found hash). The dashboard shows a "Chain verified" badge with the time and event count. Verification runs when the dashboard starts and before every export.
6. `seen audit export --project X --from D --to D --format csv|ndjson` writes the events plus a manifest: range, count, head hash, verification result, tool and schema version.
7. Retention defaults to 365 days. A prune writes `audit.checkpoint` holding the last pruned hash, so what remains still verifies.
8. At every session end the head hash is appended to `~/.seen/audit-heads.log`. In Phase 5 heads are sent to the team server as an off-machine anchor.

**Limits to state in the docs and the UI:**
- A developer with write access to their own machine can rebuild the whole chain. The chain catches bugs, partial edits and clumsy tampering. It is **not tamper-proof until heads are anchored off the machine** (team server, or S3 Object Lock for a Minfy-hosted server). [Certain]
- It covers sessions where the plugin ran. If a developer disables the plugin there are no events. Mitigation: enable the plugin through managed settings, and compare session counts with Claude Code's own telemetry. [Likely, verify managed-settings behaviour in Phase 0]
- It records what happened, not why a person approved it.

---

## 11B. PII exposure spec

**What "shared" means.** A finding is personal data or a secret that:
- entered the model's context during a turn (typed prompt, file read, Bash or MCP output, injected memory), destination `model`
- was sent out by a tool call (a network command, WebFetch, an MCP tool argument), destination `network`
- was written by the agent into the repo (added diff lines), destination `repo`
- is inside a memory file, destination `memory`

Seen can show that data was exposed. It cannot un-send it. Once text is in the context it has gone to the model provider (Bedrock if that is the client's route). Say this in the UI.

**Detection, tier 1 (stdlib, runs in hooks and at ingest):**

| Type | Method | Confidence |
|---|---|---|
| `email` | Pattern, minus allowlisted domains such as `example.com` | medium |
| `phone` | E.164, and Indian 10-digit mobile starting 6 to 9 | medium with context words, else low |
| `aadhaar` | 12 digits, first digit 2 to 9, Verhoeff checksum valid | high |
| `pan` | `[A-Z]{5}[0-9]{4}[A-Z]` with a valid fourth letter | medium |
| `card` | 13 to 19 digits, Luhn valid, known issuer prefix | high |
| `iban` | Pattern plus mod 97 check | high |
| `ssn` | US structure rules | medium |
| `upi` | `name@handle` where the handle is in a known UPI handle list | medium |
| `dob` | Date near a keyword such as "dob" or "date of birth" | medium |
| `passport`, `gstin`, `voter_id`, `driving_licence` | Pattern, with checksum where one exists | low to medium |
| `custom` | Rules from `.seen/pii.yaml`, for example MRN or UHID patterns with context words, for healthcare projects | per rule |
| `secret` (reported separately, not PII) | AWS access key `AKIA[0-9A-Z]{16}`, private key blocks, JWTs, high-entropy strings next to words like key, secret, token, password | high or medium |

**Tier 2, optional (`engine = "presidio"`):** names, locations and organisations through Microsoft Presidio with spaCy. Runs at ingest only, never in a hook. Off by default: it is heavy, and person-name detection in code and logs has many false positives. Calling a cloud PII service (for example AWS Comprehend) would send the data to another service, so it is opt-in per client and not built in v1.

**Scan points:**

| Where | What is scanned | Can it prevent? |
|---|---|---|
| `prompt-submit` | The typed prompt | Yes. `block` mode exits 2. `warn` mode shows a `systemMessage` to the user (A11) |
| `pre-read` | First 256 KB of the file about to be read, 100 ms budget | Yes, in `block` mode (A12). Falls back to detect-only on timeout |
| `stop` | The turn's slice of the transcript: user text, tool results, tool inputs, injected context (A10) | No. Detect and report |
| `stop` | Added lines of the git diff | No. Detect and report |

Be clear about this: only the prompt and `Read` can be prevented. Bash output, MCP results and web content are detect-only. The practical prevention is the deny-list snippet (below).

**What is stored per finding:** type, confidence, count, distinct count, source kind, source reference (tool name and file path, home redacted, never command arguments), destination, detector. Never the value. Plus a fingerprint, `HMAC-SHA256(secret.key, normalised value)` truncated to 16 hex characters, kept in the local ledger only and never synced. It lets the dashboard say "the same Aadhaar number was exposed in 4 changes" without storing it. [Likely fine for low-entropy values only because the key stays local]

**Prompts are a PII store too.** `changes.prompt_text` can hold what the developer typed. Setting `pii.store_prompt_text` is `redacted` by default (detected spans replaced with `[AADHAAR]`, `[EMAIL]` and so on before storing), with `full` and `off` as options. Claude Code's own transcript files under `~/.claude` also hold the raw text, and Seen does not control those.

**Settings** (`~/.seen/config.toml`):

```toml
[audit]
retention_days = 365

[pii]
mode = "report"                 # off | report | warn | block
min_confidence = "medium"       # findings below this are stored but not shown by default
types = ["email","phone","aadhaar","pan","card","iban","ssn","upi","dob","secret"]
scan_tool_results = true
scan_diff = true
store_prompt_text = "redacted"  # full | redacted | off
engine = "regex"                # regex | presidio
```

Project file `<repo>/.seen/pii.yaml` (committed, reviewed in PRs):

```yaml
allow_paths: ["tests/fixtures/**", "docs/sample-data/**"]
allow_values: ["*@example.com", "*@test.local"]
custom_rules:
  - id: mrn
    type: custom
    pattern: "\\bMRN[:# ]*\\d{6,10}\\b"
    confidence: medium
```

Marking a finding as test data in the dashboard sets `status = test_data`, and writes an `approval.pii_test_data` audit event with the actor.

**Dashboard behaviour:**
- Change detail: a "PII exposure" panel with type, count, confidence, source ("Prompt", "Read data/patients.csv", "Bash output", "MCP tool") and destination ("Model", "Network", "Repo"). A banner when anything is `high`.
- Changes: a PII column with a chip, and a "PII exposed" filter chip.
- Overview: a "Changes with PII exposure" tile, a by-type bar, and **top sources**, meaning the files and tools that repeatedly put PII into context. This is the actionable part.
- Settings: mode, types, allowlist, prompt storage.
- Deny-list helper: for each top source file, a button that shows the `permissions.deny` entry (for example `Read(./data/patients.csv)`) to add to the repo's `.claude/settings.json`. Seen shows the snippet and does not write it. [Likely; confirm the current deny-rule syntax in the docs during Phase 0]

**Team sync:** only `pii_state` and counts by type per change. No `source_ref`, no fingerprints, no values. Off by default.

**Limits to state in the docs and the UI:**
- Regex finds structured identifiers. It misses names, addresses and free-text health details. Without tier 2, "no PII found" means "no structured identifiers found". Never show a bare "clean" badge. [Certain]
- False positives will come from test fixtures and synthetic data. The allowlist and "mark as test data" handle this, and every use of them is audited.
- This is evidence for a privacy review. It is not a compliance control, and it makes no claim about DPDP, GDPR or HIPAA compliance.

---

## 12. Local API (FastAPI; the team server later exposes the same shapes)

```
GET  /api/projects
GET  /api/projects/{pid}/overview?range=7|14|28
GET  /api/projects/{pid}/changes?tool=&status=&q=&file=&skill=&policy_missed=&sort=&dir=
GET  /api/changes/{id}
GET  /api/projects/{pid}/memory?type=&status=&q=
POST /api/memory/{id}/verify
POST /api/memory/{id}/archive
GET  /api/skills?kind=&status=&q=&unused=
GET  /api/skills/{id}
POST /api/skills/{id}/approve        # updates skills.lock.json
POST /api/skills/{id}/block
GET  /api/projects/{pid}/policies
GET  /api/projects/{pid}/audit?type=&actor=&session=&from=&to=&q=&page=
GET  /api/audit/verify
POST /api/audit/export
GET  /api/changes/{id}/pii
GET  /api/projects/{pid}/pii?range=&type=&source=&status=
POST /api/pii/{finding_id}/mark-test-data
GET  /api/projects/{pid}/pii/deny-snippet
GET  /api/settings
PUT  /api/settings
```

All responses are Pydantic models. Generate the TypeScript client from `/openapi.json` in CI and fail the build if it is out of date.

---

## 13. Web app

Pages (match the approved mockup): **Projects, Overview, Changes, Change detail, Memory, Skills (Installed and Required skills tabs), Audit, Settings.**

Behaviour that must carry over from the mockup:
- Project switcher and 7/14/28-day range in the top bar.
- Overview: four to five summary tiles, cost-per-day stacked bars by tool with hover, recent changes, most edited files (click filters Changes), top skills (click filters Changes), by-model table.
- Changes: search, tool chips, git-status select, "memory not loaded" chip, skill select, "skill policy missed" chip, sortable columns, row click opens detail.
- Change detail: files with line counts, prompt, token and cost breakdown with share of cost, memory read, skills used with version and trigger, required-skill checks, "memory saved from this change".
- Memory: type chips, freshness filter, expand a card for source change, staleness reason, Re-verify, Archive.
- Skills: inventory table, detail panel with Approve and Block, required-skill rules with compliance bars.
- Audit: filterable timeline (type, actor, session, date), event detail, "Chain verified" badge with time and count, Export button, a visible note on the off-machine anchor status.
- PII: panel in Change detail, chip and filter in Changes, tile and top sources in Overview, deny-list snippet, never a bare "clean" badge.
- Settings: connected tools, memory behaviour, skill auditing, PII mode and allowlist, audit retention, team sync switches, price table, local data.
- Brand: the animated eyes are the app icon, favicon and sidebar logo. Build a small `<Eyes state="idle|alert" />` React component from `eyes.svg`: idle looks around and blinks; alert (shown when the open project has a high-confidence PII finding, a missed required skill, or a failed audit verify) stops looking around, stares straight ahead and tints the iris. Respect `prefers-reduced-motion`.
- Light and dark themes through CSS variables.
- Works at phone width; tables scroll inside their own container.

README and repo: use `assets/brand/eyes.svg` as the repo avatar source and at the top of the README through an `<img>` tag (CSS animation inside an SVG runs there; scripts do not). Upload `social-preview.png` as the GitHub social preview, which cannot be animated.

Design tokens (`web/src/styles/tokens.css`):
- Primary `#1C55BB`, accent `#F4A027`
- Headings: Playfair Display. Body: DM Sans. Paths and hashes: DM Mono.
- Use tabular numbers for all figures.
- Semantic colours for good, warning, critical are separate from the accent.

No sample data in production builds. For development, ship a `seen dev-seed` command that fills a scratch DB with generated data.

---

## 14. Implementation plan

### Phase 0: Spikes (week 1). Output: `docs/hooks-findings.md`

| ID | Task | Acceptance |
|---|---|---|
| P0-1 | Build a throwaway plugin whose hooks dump every payload to `tests/fixtures/hook_payloads/<event>.json`. Install it from a local marketplace. Run a real session that edits files, runs bash, uses a skill and a slash command. | One recorded payload per event, scrubbed of secrets, committed. |
| P0-2 | Test how SessionStart and UserPromptSubmit add context (stdout versus JSON field). | Findings doc states the working format, with a proof that the model saw the text. |
| P0-3 | Parse a real transcript: usage fields, duplicate messages, model names. | A script prints per-turn totals. Duplicates handled. |
| P0-4 | Find how skill runs appear: hooks, transcript, slash commands, subagents. | Findings doc lists exactly which signals exist. Recall measured on a scripted run of 20 skill invocations. |
| P0-5 | Test the PreToolUse gate on `Edit`, `Write`, `MultiEdit`, `NotebookEdit`. | Gate blocks and the model recovers by calling a tool. |
| P0-6 | Test a Stop-hook block and the `stop_hook_active` guard. | No infinite loop. Model runs the required skill. |
| P0-7 | Write the skill-folder hasher. Test on user, project and plugin skills. | Stable hash across runs. Changes when a bundled script changes. |
| P0-8 | Compare transcript token totals to native OpenTelemetry for 5 turns. | Within 2%, or findings explain the gap. |
| P0-9 | Install through a git marketplace and through a repo `.claude/settings.json`. | Both routes work. Steps documented. |
| P0-10 | Measure hook latency (cold Python start, stdlib only). | p95 under 100 ms, or note the cost and the fallback (for example a single-file zipapp). |
| P0-11 | Check that the agent can create files in `.seen/memory/` without extra permission prompts, and that a memory file read by a hook is visible to the model. | Findings doc states the permission behaviour. |
| P0-12 | Record what the transcript and `PostToolUse` payload hold for tool results: file reads, Bash output, MCP results, web fetches. Check truncation. | A coverage table: for each source, whether the full content is present. Settles A10. |
| P0-13 | Test `UserPromptSubmit` exit 2 and `systemMessage`, and `PreToolUse` deny on `Read`. Also confirm the current `permissions.deny` syntax for file reads. | Findings doc states what the user sees and what the model sees in each case. Settles A11, A12. |

**Gate:** if A4 fails or P0-8 is off by more than 5%, stop and report to the owner before Phase 1.

### Phase 1: Ledger, inventory and audit chain (weeks 2 to 6)

| ID | Task | Acceptance |
|---|---|---|
| P1-1 | Scaffold the uv workspace, ruff, mypy, pytest, CI. | `uv run pytest` and CI green on an empty suite. |
| P1-2 | `paths.py`, `project.py` with identity rules from 9.1. | Unit tests for HTTPS, SSH, no remote, worktree. |
| P1-3 | SQLAlchemy models and Alembic initial migration for section 8. | `alembic upgrade head` creates all tables. |
| P1-4 | `plugin/bin/seen-hook` with the fail-open wrapper and the spool writer. | Replay of recorded payloads writes expected spool lines. Latency test passes. |
| P1-5 | `gitdelta.py` snapshots and deltas. | Built-repo tests: edits via tool, edits via bash, new files, deletes, revert in-turn. |
| P1-6 | `transcript.py` and `pricing.py`. | Fixture transcripts produce expected totals. Prices carry `price_version`. |
| P1-7 | `ingest.finish_turn` writes `changes`, `change_files`. | Replaying a recorded session yields the expected rows. |
| P1-8 | Skill inventory scan and hasher, `skill_versions`. | Matches the folders on the dev machine. Hash drift detected. |
| P1-9 | Skill invocation capture and reconciliation (per Phase 0 findings). | Recall meets the Phase 0 target on the scripted run. |
| P1-10 | CLI: `seen init`, `status`, `report`, `skills scan`, `skills list`, `doctor`. | `seen report --project X` prints the last week. `doctor` checks hooks, Python version and DB. |
| P1-11 | Marketplace and plugin packaging. | Install from the marketplace on a clean machine, run a session, see a row. |

| P1-12 | `audit/` library: `append`, canonical JSON, hash chain, insert-only triggers, `verify`. | Tamper tests: edit a row, delete a row, reorder two rows, truncate the tail. Each is detected with the right `seq`. Verifies 100,000 events in under 10 seconds. |
| P1-13 | Wire events from spool into the audit chain in `ingest`: sessions, turns, memory, gate, tools, files, skills, capture gaps, `session.incomplete`. Lockfile and policy hash checks at session start. | Replaying a recorded session yields the expected event sequence. A killed session produces `session.incomplete`. A broken hook produces `capture.gap`. |

**Phase exit:** for one week of real use on the owner's repos, file lists match git on 95% or more of changes, hook overhead stays under 150 ms, token totals are within 2% of the native figures, and `seen audit verify` passes after the week.

### Phase 2: Local dashboard (weeks 7 and 8)

| ID | Task | Acceptance |
|---|---|---|
| P2-1 | `local_server` with the read endpoints from section 12 and static serving of the web build. | OpenAPI schema generated. Endpoint tests with a seeded DB. |
| P2-2 | `seen dev-seed` and `seen serve`. | Dashboard opens on localhost with generated data. |
| P2-3 | Web scaffold: tokens, layout shell, router, generated client, themes. | Light and dark verified. |
| P2-4 | Overview, Changes, Change detail. | Playwright: switch project, filter, open a change, go back. |
| P2-5 | Skills page, read-only (inventory, detail, usage). | Playwright: open a skill, see its recent changes. |
| P2-6 | Projects page and Settings (read-only). | Renders from real data. |
| P2-7 | Audit page, `seen audit verify` and `seen audit export` (csv and ndjson with manifest). Every POST, PUT and DELETE route writes an audit event. | Playwright: filter the timeline, see the verified badge, export. Route-walk test passes. |

**Phase exit:** the owner can answer "what did the agent change in project X last week, what did it cost, and which skills ran" without opening git or a transcript.

### Phase 3: Memory (weeks 9 and 10)

| ID | Task | Acceptance |
|---|---|---|
| P3-1 | Memory file parser and validator (stdlib), with `seen memory add|list|verify|archive`. | Round-trip and malformed-file tests. |
| P3-2 | Ranking and token-budget logic from section 10. | Deterministic tests for ranking and cut-off. |
| P3-3 | Injection in `session-start` and `prompt-submit` (format from A5). | Real session: the model quotes a memory item. `change_memories` rows written. |
| P3-4 | Gate in `pre-edit`, with the `.seen/memory/` exemption. | Real session: with injection disabled, an edit is blocked and the model reads the folder. |
| P3-5 | `using-seen-memory` skill and agent-written memory. | Real session: the agent saves a decision as a file, it shows as `unverified`. |
| P3-6 | Staleness per 9.7. | Edit a referenced file, memory flips to stale. |
| P3-7 | Memory page, writable (verify, archive), and memory shown in Change detail. | Playwright: re-verify clears stale. Verify and archive write audit events. |

**Phase exit:** 95% or more of edits in a week ran with memory loaded, and injection stays under 100 ms with 100 memory files.

### Phase 4: Skill audit (weeks 11 to 13)

| ID | Task | Acceptance |
|---|---|---|
| P4-1 | Lockfile read/write and status computation. | Unit tests for approved, changed, unreviewed, blocked. |
| P4-2 | Skills page actions: Approve version and Block. | Lockfile updated. UI reflects it. An `approval.skill` audit event is written. |
| P4-3 | Sideload detection and "ran on an unapproved version" flag. | Edit a skill script, run it, the change shows the flag. |
| P4-4 | Policies file, evaluation at Stop, `policy_results`. | Test repo: a change that skips the required skill shows Missed. |
| P4-5 | Required-skills tab and Changes filters. | Playwright test. |
| P4-6 | Enforcement mode (Stop-hook block, once per turn). | No loop. The model runs the skill, then stops. Default mode stays `report`. |
| P4-7 | Extend the audit export with skill versions and policy results, joined by change. | The export answers: which skill versions ran on which changes, who approved them, and which policies were missed. |

**Phase exit:** a skill edited mid-week is flagged within one session. False positives on policies stay under 5% across a week of use.

### Phase 4B: PII exposure (weeks 14 to 16)

| ID | Task | Acceptance |
|---|---|---|
| P4B-1 | `pii/` detectors and validators (tier 1) with the labelled corpus in `tests/fixtures/pii_corpus/` (synthetic data only, Indian and international formats, plus hard negatives such as order numbers and test cards). CI writes `docs/pii-benchmark.md`. | Targets, adjustable by the owner: high-confidence types at 95% precision and 90% recall on the corpus; every type's numbers published. |
| P4B-2 | Span redaction in `redact.py`, used for `prompt_text`. | Stored prompts contain `[TYPE]` markers, never the value. Test with a sentinel Aadhaar. |
| P4B-3 | Prompt scan in `prompt-submit` for `report`, `warn` and `block`. | 10,000-character prompt scans in under 30 ms. Block mode stops the prompt in a real session. Warn mode shows the user a message the model does not see. |
| P4B-4 | Stop-time scan of the transcript slice, tool inputs, injected memory, and `pii_findings` writes with fingerprints. | A scripted session that reads a file with known fake PII yields the expected findings with the right source and destination. |
| P4B-5 | Scan of added diff lines (`repo` destination). | Agent writes a fake Aadhaar into a file: finding appears with destination `repo`. |
| P4B-6 | `pre-read` scan and block, with the size and time cap. | Block mode denies a read of a file with a valid fake card number. Oversized file falls back to detect-only and says so. |
| P4B-7 | `pii.yaml` allowlist, custom rules, "mark as test data" action. | Allowlisted path produces no finding. Marking writes an audit event with the actor. |
| P4B-8 | API and dashboard: Change detail panel, Changes chip and filter, Overview tile and top sources, Settings. | Playwright: open a change with findings, filter Changes by PII, see top sources. No bare "clean" badge anywhere. |
| P4B-9 | Deny-list snippet generator. | Snippet for a top source file matches the syntax recorded in P0-13. |
| P4B-10 | Sync serializer sends only `pii_state` and counts by type. Extend the privacy sentinel test. | A sentinel email and a checksum-valid fake Aadhaar placed in a prompt, a file read and a diff never appear in: any outbound sync payload, any audit event, any `pii_findings` column, any stored `prompt_text`. |
| P4B-11 | Stretch: Presidio tier 2 behind `engine = "presidio"`. | Installs as an extra. Never imported by hooks. Finds person names in a test corpus. |

**Phase exit:** one week on a real project with PII in `report` mode. The owner reviews 50 random findings and at least 80% are real. Top sources point to files the owner recognises. Hot-path latency still passes. If precision is below 80%, tune before any team sees the dashboard, because a noisy PII panel gets ignored.

### Phase 5: Team (weeks 17 to 20), outline only

- Outbox worker with retry and idempotency keys. Sync only the fields the user switched on.
- `team_server`: FastAPI, Postgres, Alembic. Project-scoped API keys first, SSO later. Same read API as section 12.
- Roles: member sees own detail and project aggregates, project lead sees project aggregates, org admin sees all aggregates. Per-person detail is private by default.
- Retention and delete-by-project controls.
- Rollout through a repo `.claude/settings.json` (`extraKnownMarketplaces`, `enabledPlugins`) and through managed settings for whole organisations.
- Anchor audit chain heads on the server, so rewriting local history is detectable. Show "anchored through <date>" in the Audit page. For Minfy-hosted, consider S3 Object Lock.
- Sync PII counts by type only. Audit events sync only if the owner turns that on.
- Docker Compose for self-hosting. Detailed design after Phase 4B findings.

### Phase 6: Pilot (weeks 21 to 23), outline only

One delivery team, weekly review of dashboard against reality, fix what they stop trusting.

---

## 15. Quality gates

- Every parser (hook payload, transcript, git numstat, SKILL.md front matter) has tests built from **recorded real fixtures**, plus hypothesis tests for malformed input.
- CI fails on: ruff, mypy (strict on `core`), eslint, tsc, pytest, Vitest, a stale generated API client.
- Hook latency benchmark runs in CI and fails if p95 exceeds 150 ms.
- Privacy test: a test inserts a sentinel string into a prompt and a diff, runs the sync serializer, and asserts the sentinel never appears in the outbound payload.
- Audit tamper test runs in CI: edit, delete, reorder, truncate. All four must be detected.
- Every state-changing route writes an audit event (route-walk test).
- PII benchmark runs in CI. A drop in precision or recall for any type fails the build.
- Sentinel PII test (P4B-10) runs in CI.
- Headless end-to-end run (`tests/e2e`, nightly or manual): run Claude Code non-interactively in a scratch repo with the plugin loaded, make a known edit, assert the ledger row.

---

## 16. Rules for the agent (put this in `CLAUDE.md`)

```markdown
# Seen: working rules
- Read PLAN.md. Work one task at a time, in order. Name the task ID in each commit.
- Do not guess Claude Code behaviour. Use recorded fixtures in tests/fixtures. If a fact is missing, write a spike first.
- Hooks must fail open. Only the memory gate, the blocked-skill check, PII block mode and the optional policy enforcement may exit non-zero.
- The hook hot path uses the Python standard library only. No network, no SQLite writes, no heavy imports.
- Never store or sync prompts or diffs on any server. Redact home directory paths.
- Never write a PII value, secret, prompt text or command argument to the audit trail, the ledger findings, logs or any sync payload. Use type, count, hash or fingerprint.
- Never UPDATE or DELETE audit rows. Corrections are new events.
- Never show a bare "no PII" or "clean" label. Say what was checked.
- Never hardcode prices. Read pricing/prices.json.
- Write the test first for parsers and algorithms. Keep PRs small.
- When something in PLAN.md is wrong or unclear, stop, write a short note in docs/adr/, and ask the owner.
```

---

## 17. Open decisions for the owner

1. Is the skills audit a core selling point or a later add-on pack? (Sets Phase 4 priority.)
2. Approvals: repo lockfile only, or also a central server from day one?
3. Pilot mode for required-skill rules: report-only or enforce?
4. Memory in the repo: acceptable for every target client? Default is committed. Clients that refuse can set `.seen/memory/` to gitignored and lose team sharing.
5. Hosting for the team server: Minfy-run first, or client-hosted from day one?
6. PII mode for the pilot: `report` only, or `warn` / `block` for prompts? (Recommendation: `report`, until precision is measured.)
7. Which PII types matter for your first clients beyond the tier 1 list (for example hospital MRN formats for Patient360 or NephroSense)? Needed for the corpus in P4B-1.
8. Is regex-only detection acceptable for the pilot, or must names be detected (tier 2)? Tier 2 adds weight and false positives.
9. Audit anchoring: is a team-server anchor enough, or do clients need write-once storage such as S3 Object Lock from the start?
10. Audit retention: 365 days by default. Do any clients need longer?
