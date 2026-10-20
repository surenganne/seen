# Provenance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tell, for every line of tracked code and every PR range, whether an agent request, a person, or nothing Seen observed produced it, with the request behind it.

**Architecture:** The `PostToolUse` hook fingerprints the lines an agent *added* (keyed HMAC, no text stored) and spools them; ingest stores them in `line_prints`; `git blame` plus a content lookup attributes each current line. `seen blame`, `seen pr-report`, two read-only API routes and one dashboard page expose it. Attribution follows content, so squash, rebase and rename keep working.

**Tech Stack:** Python 3.11+ stdlib on the hook path (`hashlib`, `hmac`); SQLAlchemy and Alembic (SQLite ledger); Typer CLI; FastAPI; React, TypeScript, TanStack Query, Vitest, Playwright; git via `seen_core.gitutil`.

**Spec:** `docs/specs/provenance.md` (draft 2026-10-20). Where this plan decides something the spec left open it says "Decision" and Task 10 writes it back into the spec.

## Global Constraints

Copied from the spec and CLAUDE.md; every task includes them.

- Fingerprint: `HMAC_SHA256(secret.key(), b"seen-line-v1\0" + normalize(line).encode())[:8]`; `normalize` = strip, runs of whitespace collapsed to one space.
- A line is a candidate only with **at least 10 alphanumeric characters** after normalisation; others are trivial and never fingerprinted.
- Caps per tool call: **5,000 candidate lines and 1 MB** of added text; binary (NUL in the first 8 KB) skipped.
- Hot path: stdlib only, no network, no SQLite writes; `tests/pii/test_ner.py` import list enforced; **+5 ms p50** for a 200-line edit (`perf` marker).
- No line text, prompt or diff in the spool, ledger, audit trail, logs, sync payloads or API responses; fingerprints are never synced.
- Hooks fail open. Never UPDATE or DELETE audit rows. Repo files, refs and paths are untrusted: git only through `seen_core.gitutil` with `--end-of-options`; no `..`, no symlink out of the repo.
- Blame request time budget **5 s** (partial result with `truncated: true`); files over **1 MB or 20,000 lines** are `not_observed`.
- Acceptance: precision at least **99%**, recall at least **90%**, `seen blame` on 2,000 lines under **1 s**, `seen pr-report` on 50 files under **3 s**.
- Never show a bare "clean": reports say what was checked and list `agent`, `human`, `not observed` separately.
- Tests first for parsers and algorithms; one PR per task; task ID (`PV-n`) in every commit; UI uses tokens from `web/src/styles/tokens.css` only.
- Gates before each PR: `uv run ruff check . && uv run mypy packages/core/src && uv run pytest`, `uv run python scripts/pii_benchmark.py --check`, `uv run python scripts/gen_openapi.py --check`; web tasks add `npm run lint && npm run typecheck && npm test && npm run check:api && npx playwright test`.

## Review Focus

Failure inputs the spec implies and no task's main tests exercise; each has a test in the named task.

1. **CRLF, tabs and non-UTF-8 text.** A CRLF file must match LF-written fingerprints; undecodable bytes must not crash blame (Task 1, Task 4).
2. **Paths with spaces, unicode or quotes** in porcelain output and in `?path=` (Task 4, Task 8).
3. **No HEAD, shallow clone, detached HEAD, deleted or untracked file** on `seen blame`: a clear message and exit code 2, never a traceback (Task 5).
4. **A 500 KB single line, and one line repeated 10,000 times**: capped without hanging, duplicates stored once (Task 1, Task 3).
5. **A secret or PII value inside an agent-written line**: nothing but its fingerprint appears anywhere on disk (Task 2).

---

### Task 0: Spike and decision (PV-0)

**Files:**
- Create: `spikes/provenance/compare.py`, `tests/fixtures/hook_payloads/post_tool_use_multiedit.json`, `docs/adr/0018-provenance-capture.md`

**Interfaces:**
- Produces: a recorded MultiEdit payload fixture (shape of `tool_input.edits`), and the ADR that fixes the capture method and the trivial-line threshold.

- [ ] **Step 1: Record a MultiEdit payload.** If the installed Claude Code has no MultiEdit tool, say so in the ADR, drop MultiEdit from `added_lines` and Task 2's tool set, and skip the fixture. Otherwise run one real headless session that makes a MultiEdit (`claude -p` with `--plugin-dir plugin`, in a scratch repo and `SEEN_HOME`), copy the `PostToolUse` payload through `spikes/scrub_fixtures.py` into `tests/fixtures/hook_payloads/post_tool_use_multiedit.json`. Check it contains `tool_input.edits` as a list of `{old_string, new_string}`.
- [ ] **Step 2: Write `spikes/provenance/compare.py`.** It builds scratch repos for seven scenarios (in-turn commit, human commit later, human edits half the lines, squash merge, rename, Bash-generated file, human-only repo), scores Method A (tool-input fingerprints, per spec section 5) and Method B (fingerprints of `git diff <head_before>` added lines) on precision and recall, and prints a table.
- [ ] **Step 3: Run it.** `uv run python spikes/provenance/compare.py`. Expected: A precision at least 99% in every scenario; the table shows B's precision loss when a person edits during the turn.
- [ ] **Step 4: Write ADR 0018** (3 to 8 lines): the chosen method, the measured numbers, and the trivial-line threshold (keep 10 unless the data says otherwise). If A fails the 99% bar, stop and ask the owner (CLAUDE.md rule).
- [ ] **Step 5: Commit** `PV-0: provenance spike, MultiEdit fixture, ADR 0018`.

---

### Task 1: Fingerprints and tool-input extractors (PV-1)

**Files:**
- Create: `packages/core/src/seen_core/provenance/__init__.py` (empty), `packages/core/src/seen_core/provenance/prints.py`
- Modify: `tests/pii/test_ner.py` (add `"provenance/prints.py"` to `HOT`)
- Test: `tests/provenance/test_prints.py`

**Interfaces:**
- Produces (stdlib only):
  - `normalize(line: str) -> str`
  - `is_trivial(line: str) -> bool`
  - `fingerprint(line: str, key: bytes) -> bytes` (8 bytes)
  - `added_lines(tool_name: str, tool_input: dict[str, Any]) -> list[str] | None` (`None` = not a text-writing tool)
  - `capture(tool_name: str, tool_input: dict[str, Any], root: str | None, key: bytes) -> dict[str, Any] | None`, returning `{"path": str, "fps": list[str], "n": int, "capped": bool}` or `None` (nothing to record). `path` is repo-relative; `fps` are 16-char hex.

- [ ] **Step 1: Write the failing tests** in `tests/provenance/test_prints.py`:

```python
KEY = b"k" * 32

def test_normalize_collapses_whitespace_and_crlf():
    assert normalize("\t  return   x +  y \r\n") == "return x + y"

def test_fingerprint_is_8_bytes_keyed_and_stable():
    a = fingerprint("def handler(event):", KEY)
    assert len(a) == 8 and a == fingerprint("  def  handler(event):\r", KEY)
    assert a != fingerprint("def handler(event):", b"j" * 32)

def test_trivial_lines_are_never_candidates():
    assert all(is_trivial(s) for s in ["}", "else:", "return", "", "x = 1"])      # fewer than 10 alphanumerics
    assert not is_trivial("result = compute(total)")

def test_write_adds_every_line_edit_adds_only_new_lines():
    assert added_lines("Write", {"content": "a\nb\n"}) == ["a", "b"]
    ti = {"old_string": "keep this line\nold line here", "new_string": "keep this line\nnew line here"}
    assert added_lines("Edit", ti) == ["new line here"]

def test_multiedit_and_notebook_and_other_tools():
    me = {"edits": [{"old_string": "x", "new_string": "first new line\n"}, {"old_string": "y", "new_string": "second new line"}]}
    assert added_lines("MultiEdit", me) == ["first new line", "second new line"]
    assert added_lines("NotebookEdit", {"new_source": "cell line one", "edit_mode": "replace"}) == ["cell line one"]
    assert added_lines("NotebookEdit", {"new_source": "gone", "edit_mode": "delete"}) == []
    assert added_lines("Bash", {"command": "ls"}) is None

def test_capture_path_caps_and_binary(tmp_path):
    root = str(tmp_path)
    c = capture("Write", {"file_path": f"{root}/src/a.py", "content": "line number one\nline number two\n"}, root, KEY)
    assert c["path"] == "src/a.py" and c["n"] == 2 and len(c["fps"]) == 2 and not c["capped"]
    assert capture("Write", {"file_path": "/etc/passwd", "content": "x" * 50}, root, KEY) is None            # outside the repo
    assert capture("Write", {"file_path": f"{root}/b.bin", "content": "\0" + "x" * 50}, root, KEY) is None  # binary
    big = capture("Write", {"file_path": f"{root}/c.py", "content": "\n".join(f"line number {i:06d}" for i in range(6000))}, root, KEY)
    assert big["capped"] and big["fps"] == []

def test_minified_line_and_repeats(tmp_path):            # Review Focus 4
    root = str(tmp_path)
    huge = capture("Write", {"file_path": f"{root}/m.js", "content": "a" * 500_000}, root, KEY)
    assert huge is not None and huge["n"] == 1 and not huge["capped"]            # one line, under the 1 MB cap
    rep = capture("Write", {"file_path": f"{root}/r.py", "content": "same repeated line\n" * 10_000}, root, KEY)
    assert rep["capped"] is True and rep["fps"] == []                            # 10,000 candidates exceed the 5,000 cap
```

- [ ] **Step 2: Run to verify failure.** `uv run pytest tests/provenance/test_prints.py -q` fails with `ModuleNotFoundError`.
- [ ] **Step 3: Implement `prints.py`** with the signatures above. Edit's rule is a multiset difference on normalised lines (`collections.Counter`). `capture` makes the path repo-relative with `os.path.realpath`/`relpath` (outside the repo gives `None`), drops trivial lines, skips content with a NUL in its first 8,000 characters, and sets `capped` (with `fps == []`) when candidates exceed 5,000 or the text exceeds 1 MB. A single huge line counts as one line, and the 1 MB cap decides.
- [ ] **Step 4: Run to verify pass**, then `uv run pytest tests/pii/test_ner.py -q` (the hot-path import list still holds).
- [ ] **Step 5: Commit** `PV-1: line fingerprints and tool-input extractors`.

---

### Task 2: Hook capture (PV-2)

**Files:**
- Modify: `packages/core/src/seen_core/hook.py` (`_on_post_tool`), `packages/core/src/seen_core/config.py`
- Test: `tests/provenance/test_capture_hook.py`

**Interfaces:**
- Consumes: `prints.capture`, `sessionstate.read(sid)["root"]`, `secret.key()`, `spool.append`.
- Produces: spool line `{"ev": "prints", "tool_use_id", "path", "fps", "n", "capped", ...base}` after every supported tool call; config `provenance = {"enabled": True}` in `DEFAULTS`.

- [ ] **Step 1: Write the failing tests** with `Replay`:

```python
def test_write_tool_spools_prints_not_text(repo, tmp_path):
    rp = Replay(repo, tmp_path); rp.start(); rp.prompt()
    secret_line = "api_token = 'sk-live-AAAABBBBCCCCDDDD'"            # Review Focus 5
    rp.fire("post-tool", "post_tool_use_write", tool_input={"file_path": str(repo / "a.py"), "content": secret_line + "\nprint('hello world')\n"})
    lines = spool.read("sess-1")
    p = [x for x in lines if x["ev"] == "prints"][0]
    assert p["path"] == "a.py" and p["n"] == 2 and all(len(f) == 16 for f in p["fps"])
    assert "sk-live" not in json.dumps(lines) and "hello world" not in json.dumps(lines)

def test_disabled_and_bash_write_nothing(repo, tmp_path, seen_home):
    paths.config_toml().write_text("[provenance]\nenabled = false\n")
    rp = Replay(repo, tmp_path); rp.start(); rp.prompt()
    rp.fire("post-tool", "post_tool_use_write", tool_input={"file_path": str(repo / "a.py"), "content": "a long enough line\n"})
    assert not [x for x in spool.read("sess-1") if x["ev"] == "prints"]

def test_a_failing_capture_still_records_the_tool_call(repo, tmp_path, monkeypatch):
    monkeypatch.setattr("seen_core.provenance.prints.capture", lambda *a, **k: 1 / 0)
    rp = Replay(repo, tmp_path); rp.start(); rp.prompt()
    assert rp.fire("post-tool", "post_tool_use_write").code == 0
    assert [x for x in spool.read("sess-1") if x["ev"] == "tool"]

@pytest.mark.perf
def test_capture_adds_under_5ms_p50_for_a_200_line_edit():
    ti = {"file_path": "/r/a.py", "old_string": "", "new_string": "\n".join(f"value_{i} = compute({i})" for i in range(200))}
    times = [timeit_once(lambda: prints.capture("Edit", ti, "/r", KEY)) for _ in range(50)]
    assert statistics.median(times) < 0.005
```

- [ ] **Step 2: Run to verify failure** (`prints` events missing).
- [ ] **Step 3: Implement.** In `_on_post_tool`, after the existing `tool` line is appended, inside its own `try/except Exception` that logs through `_log_exception("post-tool:prints")`: if the tool is in `{"Edit","Write","MultiEdit","NotebookEdit"}` and `config.load()["provenance"]["enabled"]`, call `capture` and append the `prints` line. Add `"provenance": {"enabled": True}` to `config.DEFAULTS`.
- [ ] **Step 4: Run to verify pass**, plus `uv run pytest tests/pii/test_ner.py tests/core/test_hook.py -q`.
- [ ] **Step 5: Commit** `PV-2: capture line fingerprints in PostToolUse`.

---

### Task 3: Store, ingest and erase (PV-3)

**Files:**
- Create: `packages/core/src/seen_core/db/alembic/versions/0006_line_prints.py`
- Modify: `packages/core/src/seen_core/db/models.py`, `packages/core/src/seen_core/ingest.py`, `packages/core/src/seen_core/purge.py`
- Test: `tests/core/test_db.py`, `tests/provenance/test_ingest_prints.py`, `tests/core/test_purge.py`

**Interfaces:**
- Produces: model `LinePrint(project_id: str, path: str, fp: bytes, change_id: str)`, all four columns the primary key, index `ix_line_prints_change` on `change_id`; `ingest._write_prints(db, cid: str, project_id: str | None, turn_lines: list[dict]) -> None`.

- [ ] **Step 1: Write the failing tests:**

```python
def test_migration_0006_adds_line_prints_and_keeps_data(tmp_path):
    upgrade(url, "0005"); insert a change; upgrade(url)
    assert "line_prints" in inspect(eng).get_table_names() and the change row survives

def test_ingest_stores_each_fingerprint_once_per_change(repo, tmp_path):     # Review Focus 4
    drive: start, prompt, post_tool_use_write with 3 distinct lines plus the same line twice, model_works, stop
    rows = select(LinePrint) -> 3 rows, all with the turn's change_id, project_id == project, path == "a.py"
    re-running ingest.finish_turn leaves 3 rows (idempotent)

def test_purge_removes_prints_with_the_change(...):
    after purge of that change, no LinePrint rows reference it
```

- [ ] **Step 2: Run to verify failure.**
- [ ] **Step 3: Implement.** Migration `0006` (`revision = '0006'`, `down_revision = '0005'`) creates the table and index; downgrade drops them. `_write_prints` deletes existing rows for `cid`, then inserts distinct `(project_id, path, bytes.fromhex(fp), cid)` with SQLite `INSERT OR IGNORE` (`sqlalchemy.dialects.sqlite.insert(...).prefix_with("OR IGNORE")`), called from `finish_turn` next to `_write_prompt_pii`. Add `LinePrint` to `purge.CHILDREN`. A `prints` line with a missing or malformed `fps` is skipped.
- [ ] **Step 4: Run to verify pass**, plus the full `uv run pytest -q`.
- [ ] **Step 5: Commit** `PV-3: line_prints table, ingest and purge`.

---

### Task 4: Blame and attribution (PV-4)

**Files:**
- Create: `packages/core/src/seen_core/provenance/blame.py`, `tests/provenance/fixtures/blame_*.txt` (recorded porcelain), `tests/provenance/scenarios.py` (scratch-repo builders)
- Test: `tests/provenance/test_blame.py`, `tests/provenance/test_scenarios.py`

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) BlameLine(n: int, commit: str, commit_time: int, path: str, text: str)`
  - `parse_porcelain(out: str) -> list[BlameLine]`
  - `Index = dict[tuple[str, bytes], list[tuple[str, float]]]` mapping `(path, fp)` to `[(change_id, ended_at_epoch)]`
  - `@dataclass(frozen=True) LineAttr(n: int, who: Literal["agent","human","not_observed","neutral"], change_id: str | None)`
  - `attribute(lines: list[BlameLine], index: Index, key: bytes, *, first_change_at: float | None, gaps: list[tuple[float, float]]) -> list[LineAttr]`
  - `@dataclass(frozen=True) Block(start: int, end: int, who: str, change_id: str | None)`; `blocks(attrs: list[LineAttr]) -> list[Block]`
  - `load_index(db, project_id: str, paths: set[str]) -> Index`
  - `resolve_path(root: str, rel: str) -> str` (raises `ValueError` for `..`, absolute, or a symlink out of the repo)
  - `@dataclass FileProvenance(path: str, rev: str, counts: dict[str, int], blocks: list[Block], truncated: bool, reason: str | None)`
  - `blame_file(db, project: Project, path: str, rev: str = "HEAD", budget_s: float = 5.0) -> FileProvenance`
- **Decision (refines spec 6.4):** a "recorded gap window" is `[session.started_at, session.ended_at or last audit event time]` for every session that has a `capture.gap` or `session.incomplete` audit event. Lines whose blamed commit time falls inside one are `not_observed`.

- [ ] **Step 1: Write the failing tests.**
  - `test_parse_porcelain_*` against recorded fixtures: a rename (the per-line `filename` differs from the request path), a boundary commit, a path with spaces and quotes (Review Focus 2), CRLF text (Review Focus 1), and undecodable bytes (parsed with replacement, no exception).
  - `test_attribute_rules`: a candidate line with a matching fingerprint is `agent`; no match is `human`; two matching changes pick the greatest `ended_at` not after the commit time, else the earliest after it; a trivial line between two `agent` lines of the same change in the same commit is `agent`, otherwise `human`; a blank line is `neutral`; a commit older than `first_change_at`, or inside a gap window, is `not_observed`.
  - `test_blocks_merge_consecutive_lines`.
  - `test_resolve_path_refuses_escape` for `../x`, `/etc/passwd`, `-n`, and a symlink pointing outside.
  - `test_scenarios` (acceptance 1 to 3), each built in a scratch repo through `Replay` plus real `git`: in-turn commit; human commit later; human edits half the lines; squash merge; rename; Bash-generated file; human-only repo; CRLF file. Assertions: zero `agent` lines in the human-only repo; precision at least 0.99 and recall at least 0.90 over the rest; the Bash-generated file has no `agent`; pre-Seen code is `not_observed`.
- [ ] **Step 2: Run to verify failure.**
- [ ] **Step 3: Implement** the signatures above. `blame_file` runs `gitutil.run(root, "blame", "--porcelain", "-w", "-M", "-C", "--end-of-options", rev, "--", path, timeout=budget_s)` and returns `truncated=True` on timeout; a file over 1 MB or 20,000 lines, a binary or an untracked file returns `reason` set and all lines `not_observed`. Fingerprints use `secret.key()`.
- [ ] **Step 4: Run to verify pass.**
- [ ] **Step 5: Commit** `PV-4: blame parsing and line attribution`.

---

### Task 5: `seen blame` (PV-5)

**Files:**
- Create: `packages/core/src/seen_core/headline.py`, `packages/core/src/seen_core/pii/checked.py`
- Modify: `packages/cli/src/seen_cli/main.py`, `packages/local_server/src/seen_local/queries.py`, `tests/local/test_api_timeline.py`, `README.md`
- Test: `tests/cli/test_blame_cli.py`

**Interfaces:**
- Consumes: `blame.blame_file`, the CLI's existing `_project_or_exit()`.
- Produces: `seen blame <path> [--rev REV] [--json]`. Text: one line per block, `START-END  who  headline  time(IST)  model`. JSON: `FileProvenance` plus per-block `headline`, `started_at`, `model`, `skills`. Exit 2 with a one-line message for no HEAD, shallow or detached clones where blame fails, a deleted or untracked file, and a bad path.

- [ ] **Step 1: Write the failing tests:** the happy path after a scripted turn (text and `--json`, asserting the headline and `who == "agent"`); a repo with no commits, a path that does not exist at `--rev`, an untracked file, and `../x` each give exit 2 and no `Traceback` (Review Focus 3).
- [ ] **Step 2: Run to verify failure.**
- [ ] **Step 3: Implement** `blame_cmd` (thin; the logic lives in `blame.py`). **Decision:** move `headline_of` and `areas_of` from `seen_local/queries.py` into `seen_core/headline.py`, and `PII_CHECKED` into `seen_core/pii/checked.py`; `queries.py` imports them, so the Timeline, the CLI and the report share one definition (update the import in `tests/local/test_api_timeline.py`). The headline of a block is `headline_of(change.summary, request_line(change.prompt_text), paths)`.
- [ ] **Step 4: Run to verify pass**; add a `seen blame` line to the README "Use" block.
- [ ] **Step 5: Commit** `PV-5: seen blame`.

---

### Task 6: `seen pr-report` (PV-6)

**Files:**
- Create: `packages/core/src/seen_core/provenance/report.py`
- Modify: `packages/cli/src/seen_cli/main.py`
- Test: `tests/provenance/test_report.py`, `tests/cli/test_pr_report_cli.py`

**Interfaces:**
- Produces:
  - `parse_diff_added(diff_text: str) -> dict[str, list[str]]` (path to added lines, from `git diff --unified=0 -M`, ignoring binary and deleted files)
  - `@dataclass Report` with `base: str, head: str, commits: int, added: dict[str, int]` (keys `agent`, `human`, `not_observed`), `requests: list[RequestRef]`, `sessions: int`, `models: list[str]`, `skills: list[tuple[str, str]]` (id, status at the time), `rules_missed: int`, `pii_state: str`, `pii_checked: str`, `cost_usd: float | None`
  - `build_report(db, project: Project, base: str, head: str = "HEAD", with_cost: bool = True) -> Report`
  - `render_md(r: Report) -> str`
  - `gate(r: Report, fail_on: set[str]) -> list[str]` returning the reasons, for the values `rule-missed`, `pii-high`, `unapproved-skill`
- Command: `seen pr-report --base BASE [--head HEAD] [--format md|json] [--no-cost] [--fail-on ...]`; exit 1 when `gate` returns reasons, else 0.
- **Decision:** range attribution has no blame commit time, so ties pick the change with the greatest `ended_at`.

- [ ] **Step 1: Write the failing tests:** `parse_diff_added` on a diff with a rename, a binary file and a deleted file; `build_report` over a scratch repo with a squashed branch (agent lines still `agent`, counts add up to the lines added); `render_md` contains the three counts, "not observed", the `pii_checked` sentence and no text of any added line; `--no-cost` removes the cost line; `--fail-on rule-missed` exits 1 when a rule was missed and 0 without the flag; a range of 50 files builds in under 3 s (`perf` marker).
- [ ] **Step 2: Run to verify failure.**
- [ ] **Step 3: Implement.** Reuse `blame.load_index`, `fingerprint`, `is_trivial`; trivial added lines are counted as `neutral` and left out of the percentages. Requests, skills, rules and PII come from the ledger rows of the attributing changes (`Change`, `SkillInvocation`, `PolicyResult`, `PiiFinding`); the PII sentence is `seen_core.pii.checked.PII_CHECKED` (moved in Task 5).
- [ ] **Step 4: Run to verify pass.**
- [ ] **Step 5: Commit** `PV-6: seen pr-report`.

---

### Task 7: `--post` (PV-6b)

**Files:**
- Modify: `packages/cli/src/seen_cli/main.py`
- Test: `tests/cli/test_pr_report_post.py`

**Interfaces:**
- Produces: `seen pr-report ... --post [--yes]`. Renders the comment, asks `Post this to the PR? [y/N]` unless `--yes`, then runs `gh pr comment --body-file -` for the current branch's PR; on success appends audit event `provenance.reported` with `detail={"added": n, "requests": n}` only (not added to the sync allowlist).

- [ ] **Step 1: Write the failing tests** with `gh` replaced by a stub executable on `PATH`: declining posts nothing and writes no audit event; accepting calls the stub once with the rendered body and records one `provenance.reported` event whose detail has only the two counts; a missing `gh` exits 2 with an install hint.
- [ ] **Step 2: Run to verify failure.**
- [ ] **Step 3: Implement** with `subprocess.run([...], input=body, text=True, timeout=30)`; no shell.
- [ ] **Step 4: Run to verify pass.**
- [ ] **Step 5: Commit** `PV-6b: pr-report --post with confirmation`.

---

### Task 8: API and settings (PV-7)

**Files:**
- Create: `packages/local_server/src/seen_local/provenance_api.py`
- Modify: `packages/local_server/src/seen_local/app.py` (register), `schemas.py`, `packages/core/src/seen_core/devseed.py`, `scripts/capture_web_fixtures.py`; regenerate `web/openapi.json` and `web/src/api/schema.d.ts`
- Test: `tests/local/test_api_provenance.py`

**Interfaces:**
- Produces: `GET /api/projects/{pid}/provenance/file?path=&rev=` returning `ProvenanceFile` (`path, rev, counts, blocks[{start,end,who,change_id,headline,started_at,model,skills}], truncated, reason`); `GET /api/projects/{pid}/provenance/range?base=&head=` returning the `Report` as JSON; `SettingsOut.provenance: dict` (read-only). Revs must match `^[A-Za-z0-9._/~^@{}:-]{1,200}$` and not start with `-`.
- Devseed: demo repos get files with realistic lines and `line_prints` rows attributing them to seeded changes.

- [ ] **Step 1: Write the failing tests:** the file route returns blocks that cover every line exactly once and counts that sum to the line count; `path=../x`, an absolute path, a symlink, a rev starting with `-`, a 50 MB file and a binary each return 422 or a `reason` (no 500); a path with spaces and unicode works (Review Focus 2); a budget timeout (monkeypatched to 0) returns `truncated: true`; the range route matches `build_report`.
- [ ] **Step 2: Run to verify failure.**
- [ ] **Step 3: Implement** the routes with `register(app, state)` like `writes.py`, plus the devseed extension and the fixture capture of one file route. Run `uv run python scripts/gen_openapi.py && (cd web && npm run gen:api)`.
- [ ] **Step 4: Run to verify pass**: `uv run pytest tests/local -q`, `gen_openapi --check`.
- [ ] **Step 5: Commit** `PV-7: provenance API and settings`.

---

### Task 9: Dashboard page (PV-8)

**Files:**
- Create: `web/src/pages/Provenance.tsx`
- Modify: `web/src/App.tsx`, `web/src/api/hooks.ts` (`useProvenanceFile`), `web/src/components/Layout.tsx` (nav entry), `web/src/pages/ChangeDetail.tsx` (link), `web/src/pages/Settings.tsx` (read-only card), `web/src/styles/index.css`, `docs/TESTING.md`, `README.md`, `CHANGELOG.md`, `docs/schema.md`, `PRODUCT.md`
- Test: `web/src/pages/pages.test.tsx` (add `Provenance`), `web/e2e/dashboard.spec.ts`, `web/e2e/a11y.spec.ts`

**Interfaces:**
- Consumes: `GET .../provenance/file`.
- Produces: route `/p/:pid/provenance?path=`; test ids `prov-count`, `prov-block`, `prov-path`; hook `useProvenanceFile(pid: string, path: string | undefined, rev?: string)`.

- [ ] **Step 1: Write the failing tests:** unit (page renders its heading, blocks and an alert when the API is down, and with every list empty); e2e: open the page for a seeded path, see blocks with a word and an icon for who (never colour alone), click a block's link to the Change, "Table view" lists the same blocks; axe in light and dark on desktop and phone; the 320 px reflow test includes the page; a CSP-violation listener stays empty.
- [ ] **Step 2: Run to verify failure.**
- [ ] **Step 3: Implement** the page: a path picker (files from the Changes API), a summary line with the three counts and the limits sentence, blocks with the headline, time (IST) and a link to the Change, a focusable labelled scroll region for the file, and a table view. Tokens only. Add the nav entry, the Change-detail "Provenance" link on each file row, and the read-only Settings card. Docs in this task: a TESTING.md part, README Dashboard sentence, CHANGELOG entry, `schema.md` row for `line_prints`, and the PRODUCT.md line that provenance says "not observed" instead of guessing.
- [ ] **Step 4: Run to verify pass:** `npm run lint && npm run typecheck && npm test && npm run check:api && npx playwright test`.
- [ ] **Step 5: Commit** `PV-8: provenance page`.

---

### Task 10: Real-session e2e and closing the loop (PV-10)

**Files:**
- Modify: `tests/e2e/test_headless.py`, `docs/specs/provenance.md`, `docs/adr/0018-provenance-capture.md`, `docs/plan/SEEN_BUILD_PLAN.md`

**Interfaces:**
- Consumes: the whole feature through a real `claude -p` session.

- [ ] **Step 1: Write the opt-in test** `test_pv10_blame_shows_agent_written_file`: a headless session creates `greeting.py` with the Write tool; after the Stop, `seen blame greeting.py --json` (with the scratch `SEEN_HOME`) reports `agent` for every non-trivial line and cites the request.
- [ ] **Step 2: Run it:** `uv run pytest -m e2e tests/e2e -k pv10` (costs a few cents). Expected: pass.
- [ ] **Step 3: Update the docs.** Write the Decisions made in this plan back into the spec (gap-window definition, range tie-break), set the spec status to "implemented", mark ADR 0018 accepted, and add a dated note at the top of the build plan pointing at both.
- [ ] **Step 4: Run every gate** in Global Constraints and read each exit code.
- [ ] **Step 5: Commit** `PV-10: real-session e2e, spec and ADR closed out`.

---

## Self-review

- **Spec coverage:** capture rules, caps, config flag and fail-open (Tasks 1, 2); data model, idempotent ingest, purge (3); blame, per-line rule, trivial lines, not observed, blocks (4); `seen blame` (5); `pr-report` and `--fail-on` (6); `--post` and its audit event (7); API, safety caps, time budget, settings (8); dashboard, table view, accessibility, docs (9); acceptance 1 to 3, 6, 7 (4, 8, 9, 10); acceptance 4 and 5 (2, 4, 6). Deferred on purpose and not in this plan: `provenance prune`, survival and the Overview tile (v1.1), transcript fingerprints (v1.2), git notes and CI (v2).
- **Types:** `Index`, `BlameLine`, `LineAttr`, `Block`, `FileProvenance`, `Report` are defined in Tasks 4 and 6 and used unchanged in Tasks 5, 7, 8 and 9.
- **Open items for the owner** (spec section 13) are answered by defaults here: tool inputs only, `--post` included behind confirmation, fingerprints kept as long as their ledger rows, threshold 10, v2 fields undecided.
