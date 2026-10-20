# Build ledger — docs/plan/SEEN_BUILD_PLAN.md (tasks, rulings, deferred items)
Spec: SEEN_BUILD_PLAN.md is both spec and plan (no separate spec).
Ruling: ledger keyed by plan IDs (P0-1..) — task-brief can't parse table tasks — cost if wrong: none.
Ruling: SEEN_HOME env overrides ~/.seen everywhere; dev uses ./.dev-data (mock seed), tests use tmp dirs — user asked for isolated test DB — cost: one env lookup.
Ruling: Docker runs dashboard (local_server+web) and Phase 5 team stack; hooks/CLI run on host because Claude Code + git repos live on host — cost if wrong: none, container can't see ~/.claude anyway.
Ruling: ports 47821 api/dashboard, 47822 vite dev, 47823 postgres, 47824 team server — user's defaults taken.
Ruling: brand colours = ExampleOrg palette (#E85D26 accent, #0A2540 navy) over plan's #1C55BB/#F4A027 — org instructions override — cost: token swap in tokens.css.
Ruling: §17 defaults per user; phase-exit "one week of real use" criteria can't be met in-session — recorded as pending owner validation.
P0-1..P0-13: complete (commit 7c7d39c); A1-A12 settled in docs/hooks-findings.md
P0-7: Ruling: hasher spike folded into P1-8 implementation+tests — avoids writing it twice — cost: none.
P0-8: Ruling: native reference = transcript cost-state (OTel console exporter silent in -p) — same counters — cost if wrong: re-run with OTLP collector.
P0-4: Ruling: 13 invocations measured (11 tool, 1 slash, 1 subagent), not 20 — 100% recall, more runs add cost not signal — cost: low.
P1-1: complete (uv workspace, CI) tests: pytest smoke 1/1
P1-2: complete tests: test_project 11/11
P1-3: complete tests: test_db
P1-4: complete (90129ea) tests: pytest tests → 26 passed; hook p95 33ms
P1-4: Ruling: hook code ships as seen-cli entry point seen-hook; plugin/bin/seen-hook is a fail-open shim — single source, no vendored copy — cost if wrong: plugin needs seen-cli installed (shim warns via systemMessage).
P1-4: Ruling: transcript offset is a byte offset plus prompt_id filter (not a line count) — O(1) in hot path — cost: none.
P1-4: Ruling: PostToolUse matcher '*' (not edit/skill only) so audit tool.call covers Bash/MCP/WebFetch per 11A — cost: one ~35ms hook per tool call.
Security: ~/.seen 0700, ledger.db 0600 (background review finding) — fixed with RED→GREEN tests.
P1-5: complete (de6adc6) tests: 35 passed
P1-6: complete (d942147) tests: 53 passed; token totals == native cost-state on 7 fixtures
P1-6: Ruling: prices.json = published list prices + standard cache multipliers, verified=false; native costUSD differs +3.5..+35% and no multiplier set reconciles — cost if wrong: dollar figures off; tokens exact. Owner open item.
P1-6: Ruling: dedupe usage by message id but read every content block (Claude Code writes one line per block) — found by recall fixture.
Security: hardened git runner + lstat line counts (background review) — RED→GREEN tests.
P1-7: complete (15011dd) tests: 59 passed
P1-7: Ruling: prompt_text stays NULL until P4B-2 redaction exists — never store raw by default — cost: no prompt text in early ledger rows.
Security: filter drivers neutralised (clean/smudge/process) — RED→GREEN test.
P1-8: complete (596a458) tests: 70 passed; real machine 626 skills (522 plugin, 104 user)
P1-8: Ruling: inventory scan runs detached from session-start (1117ms cold, 245ms warm > 100ms budget) — ingest reads latest inventory file — cost if wrong: first turn of a brand-new install may miss inventory until scan finishes.
P1-8: Ruling: commands/*.md counted as skills (Claude Code lists them in skill_listing) — cost: none.
MUST-DO P4B-2: route changes.summary through redact.py (security review #3).
Security: identity HMAC with secret.key; attr-source empty tree; submodules ignored — RED→GREEN tests.
P1-9: complete (e63e44b) tests: 76 passed; recall 11/11 + slash + subagent on recorded fixtures
Ruling: P1-12/13 (audit) done before P1-10 (CLI) — CLI writes must call audit.append in-transaction (11A rule 3) — cost: none, order only.
Security: scan -I + cwd; no namespace spoof; trust-preserving sync; bounded md reads — RED→GREEN tests (1c89fa1)
P1-12: complete (71e13bb) tests: test_audit 10/10 (edit/delete/reorder/truncate detected at right seq; 100k verify <10s)
P1-13: complete (629a6ec) tests: 97 passed; ruff+mypy strict clean
P1-13: Ruling: spool stores prompt sha256/len/slash, not raw text (unless store_prompt_text=full) — spool is a PII store otherwise — cost: none.
P1-10: complete (aa750b3) tests: 107 passed (CLI 7/7)
P4-1: lockfile module + status tests done early (needed by skills list); NOTE tests written alongside impl, not watched red.
P1-11: complete (7cd9804) tests: 113 unit + e2e headless 1/1 (real claude -p, --plugin-dir, SEEN_HOOK_BIN, scratch SEEN_HOME) → change row + audit events
P1-11: Ruling: clean-machine marketplace install proven in isolated CLAUDE_CONFIG_DIR (Phase 0); full-session e2e uses --plugin-dir so nothing is installed globally — cost: owner to run marketplace install + session once on a clean machine.
Ruling: turn.start carries prompt_hmac (HMAC-SHA256, per-install key) not plain SHA-256 — brute-forceable — cost: none.
PHASE 1 EXIT: pending owner — needs a week of real use.
P2-2a: devseed generator (7d1cac7) 3 projects/98 sessions/254 changes/2033 events, refuses ~/.seen
Ruling: devseed built before P2-1 — endpoint tests need a seeded DB — cost: none.
Security: safeio (symlink-safe atomic writes, locks in SEEN_HOME) for lockfile + init — RED→GREEN.
P2-1: complete (c7def1d) tests: 123 passed (API 9/9 on seeded DB); openapi.json generated
P2-2: complete (4cc4cfc) tests: CLI 10/10 (serve answers on free port with seeded data)
Security: TrustedHost + write header gate + CSP/XFO/nosniff/referrer/permissions + loopback-only serve — RED→GREEN (f8f0c87)
P2-3..P2-7: complete (9d965d7) tests: pytest 138, vitest 10, playwright 20/20 (desktop+phone, CSP+console guard), real-browser screenshots light/dark/phone reviewed
P2: Ruling: plan's 'approved mockup' not supplied — designed from spec text (forensic-ledger direction) — cost: owner may want layout tweaks.
P2: Ruling: self-host fonts (@fontsource) instead of Google Fonts — local-first privacy + CSP 'self' — cost: +~400KB fonts in bundle.
P2: Ruling: React 18.3.1 (plan) not 19; TypeScript 5.9.3 (typescript-eslint <6.1) — cost: none.
P2: NOTE vitest component tests written after components (regression, not TDD).
Bug: concurrent first-use of ledger engine segfaulted (alembic global ctx) — found in real browser — RED→GREEN test_concurrent_first_use_is_safe.
PHASE 2 EXIT: met on seeded data (owner can answer what/cost/skills per project); real-data confirmation pending owner.
Security: free-text config values fingerprinted in audit — RED→GREEN
DOCKER: (d509733) dashboard healthy uid 10001, headers verified via curl, rebound Host 400, write w/o header 403, port bound 127.0.0.1; container pytest 144/144; container Playwright 20/20 vs tmpfs test DB
Bug: git<2.40 rejected --attr-source => every git call None (silent) — found in container — RED→GREEN test_old_git_still_works.
P3-7: complete (8a4c4ed) tests: pytest 193, playwright 26/26
Bug: repo paths with spaces broke snapshot; --output= ref injection was real (RED wrote /tmp/pwned) — both fixed RED→GREEN.
P4-3/P4-4/P4-6: complete (dd26e5e) tests: 196 passed (policy 7/7: report never blocks, enforce once then lets go, status approved->changed after edit, blocked skill exit 2)
Fix: e2e tests were running on every plain pytest (spent tokens) — now opt-in via -m e2e.
P4-2/P4-5/P4-7: complete (c302b80) tests: pytest 207, playwright 32/32, real-session P4-6 1/1 (one Stop block, skill ran, met=1)
PHASE 4 EXIT: pending owner week (skill edit flagged within one session is covered by replay test; policy FP rate needs real use).
P4B-1: complete (554fdfe) all 12 types 100%/100% on 1120-sample synthetic corpus (caveat: corpus authored with detectors); found+fixed card-vs-aadhaar overlap and mixed-grouping FPs
P4B-1: Ruling: unseparated 12-digit Verhoeff-valid without keyword = medium (1/10 random numbers pass) — cost: an unformatted real Aadhaar shows as medium not high.
P4B-1: complete (0908623) all 12 types 100%/100% on 1120-sample synthetic corpus (caveat: corpus authored with detectors); fixed card-vs-aadhaar overlap + mixed-grouping FPs
P4B-1: Ruling: unseparated 12-digit Verhoeff-valid w/o keyword = medium (1/10 random numbers pass) — cost: unformatted real Aadhaar shows medium.
P4B-2/P4B-3: complete (7af4ae6) tests: 272 passed; sentinel Aadhaar/email never in spool, audit, findings or stored prompt
Security: ReDoS in _ASSIGN confirmed (>300s) — bounded quantifiers, adversarial perf tests RED→GREEN. MUST-DO summary redaction: DONE.
P4B: Ruling: hooks read pii.yaml with a stdlib subset parser (documented schema only) — cost: exotic YAML ignored.
P4B-2/P4B-3: complete (917ca1e) sentinel Aadhaar/email never in spool, audit, findings or stored prompt
Security: ReDoS in _ASSIGN confirmed (>300s) — bounded, adversarial tests RED→GREEN. MUST-DO summary redaction: DONE.
P4B: Ruling: hooks read pii.yaml with a stdlib subset parser — cost: exotic YAML ignored.
P4B-3 e2e: real sessions block 1/1 (prompt never reached model), warn 1/1 (user saw systemMessage, model said no) (1208ee1)
Security: allowlist power limited (HIGH finding) — RED→GREEN.
P4B-4/P4B-5: complete (5427337) tests: 294 passed (stop-scan 8/8: Read/MCP/Bash/WebFetch/allow_paths/diff/removed lines)
Security: allowlist glob tricks rejected — RED→GREEN.
P4B-6: complete (a9a8cb9) tests: 315 passed; security fixes RED (12 failing) -> GREEN
P4B-7/8/9: complete (a52080c) tests: local 28, playwright 37 passed + 1 skip (global setting once)
P4B-10/P4B-11: complete (e7c4ff6) tests: 329 passed; sentinel absent from sync/ledger/audit/prompt; hot-path import isolation test
P4B-11: Ruling: Presidio adapter + extra built, NOT installed (~500MB models) — cost: tier 2 untested against real Presidio; owner installs with uv sync --extra pii-ner.
Security: pre-read allow_paths bypass (HIGH) — shared matcher RED→GREEN.
PHASE 4B EXIT: pending owner (50 real findings ≥80% real, top sources recognisable).
P5a: team server skeleton (2c97901) tests: 340 passed (team 10/10 on SQLite)
P5: Ruling: team schema via create_all in skeleton (not Alembic) — design settles after Phase 4B real use — cost: migrate before first schema change.
P5b: sync client + anchors + team docker files (5873cb3) tests: 352 passed (team on SQLite)
Security: team access control (4 HIGH/MED) fixed RED→GREEN; per-IP lockout-even-for-valid-key kept per CLAUDE.md §5.1 (declined finding 5).
Docker re-run: tests 354/354, Playwright 37 + 1 skip (e339d0f)
Ruling: SEEN_PERF_FACTOR=2.5 only in the container test service (Docker Desktop VM process start is slower; hooks run on host) — plan's 150ms hook gate unscaled — cost: container perf regressions under 2.5x go unnoticed there; host run is the gate.
Final review: fresh reviewer (fable), 0 Critical, 9 Important, 15 Minor. Assessment: ready with fixes.
Final: fixed 1 non-ASCII file names (core.quotePath=false, utf-8 decode) — test_non_ascii_file_names_counted_and_scanned RED→GREEN
Final: fixed 2 custom-regex ReDoS (safe_pattern at load) — test_catastrophic_custom_rule_rejected RED→GREEN
Final: fixed 3 >32k spool lines broke audit (chunked IN + high-water mark) — test_audit_ingest_survives_40k_spool_lines RED→GREEN
Final: fixed 4 mark-as-test-data undone by re-ingest — test_mark_test_data_survives_reingest RED→GREEN
Final: fixed 5 worktrees read main checkout (session root = worktree toplevel) — test_worktree_uses_its_own_checkout RED→GREEN
Final: fixed 6 raw assistant reply in spool (redacted summary only) — test_last_message_redacted_in_spool RED→GREEN
Final: fixed 7 retention never applied / spools never cleaned — test_retention_* RED→GREEN
Final: fixed 8 lockfile symlink to /dev/zero hung pre-skill — test_symlinked_lockfile_is_ignored_fast RED(hang)→GREEN
Final: fixed 9 untracked counting unbounded (20 MB budget, 1 MB/file) — test_untracked_counting_has_a_total_budget RED→GREEN
Final: suite 364/364, playwright 37+1 skip, real-session e2e 7/7 (3919f3f)
Final: minor (deferred): 10 export filename from unvalidated project string (same-origin only)
Final: minor (deferred): 12 blocked prompts never reach a Change (pii_state=blocked unreachable in ledger; audit has it)
Final: minor (deferred): 13 hook.log tracebacks carry home paths
Final: minor (deferred): 14 sync audit events sent but discarded by server; no cursor
Final: minor (deferred): 15 sync backoff anchors on created_at
Final: minor (deferred): 16 key rotation locks an install out of anchoring (needs admin re-bind)
Final: minor (deferred): 17 per-IP throttle map unbounded
Final: minor (deferred): 18 team ingest files list uncapped
Final: minor (deferred): 19 turn_start lacks transcript_path/project fallback
Final: minor (deferred): 20 resumed subagents double-counted
Final: minor (deferred): 21 renames counted as delete+add
Final: minor (deferred): 22 front matter strips values containing ' #'
Final: minor (deferred): 24 '[::1]' host entry is dead in TrustedHostMiddleware
Security (post-review): ReDoS validator bypass via nested groups — sre parse-tree check RED→GREEN (5250098)
Security (post-review): regex walker deny-by-default — RED→GREEN (76ba16c)
