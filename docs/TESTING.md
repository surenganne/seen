# How to test Seen, step by step

This guide walks through every feature by hand, from a fresh clone to a real Claude Code session. Each step
says what to run and what you should see. Work top to bottom: later parts build on earlier ones.

**Your real data stays safe.** Every step below uses a throwaway `SEEN_HOME` (or a Docker volume) and
scratch git repos. Nothing writes to `~/.seen` unless you choose to in Part 13.

**Ports used** (all off the common defaults): 47821 dashboard, 47822 Vite dev server, 47823 team Postgres,
47824 team server, 47825 dashboard on real data (host), 47826 the host dashboard in this guide.

The automated suites cover the same ground. Part 1 runs them; the rest is the manual pass.

---

## Part 0. Prerequisites

| Tool | Version | Check |
|---|---|---|
| git | any recent | `git --version` |
| Python | 3.11+ | `python3 --version` |
| uv | 0.8+ | `uv --version` |
| Node.js | 22 | `node --version` |
| Docker Desktop (or Engine + Compose v2) | recent | `docker compose version` |
| Claude Code CLI (Parts 9–12 only) | recent, logged in | `claude --version` |

```bash
git clone https://github.com/surenganne/seen && cd seen
uv sync && (cd web && npm ci && npm run build)
export SEEN_TEST=$HOME/seen-manual-test        # scratch area for this guide
rm -rf "$SEEN_TEST" && mkdir -p "$SEEN_TEST"
```

Expected: `uv sync` and `npm ci` finish without errors, and `web/dist/index.html` exists.

---

## Part 1. Automated suites (5 minutes)

```bash
uv run pytest                                   # unit + integration
(cd web && npm run lint && npm run typecheck && npm test && npm run check:api)
(cd web && npx playwright install chromium && npx playwright test)
uv run python scripts/pii_benchmark.py --check  # detector precision/recall gate
```

Expected:
- pytest: `376 passed, 7 deselected` (the deselected ones are the real-Claude and Postgres suites).
- Vitest: `10 passed`. `check:api` reports the client matches the OpenAPI schema.
- Playwright: `37 passed, 1 skipped`, desktop and phone. The run fails on any CSP violation or console error.
- The benchmark exits 0.

The same checks run in CI on every push: <https://github.com/surenganne/seen/actions>.

---

## Part 2. Docker (no host Python needed)

```bash
docker compose up -d --build                     # dashboard on generated mock data
open http://127.0.0.1:47821                      # or paste into a browser
docker compose --profile test run --rm tests     # lint, types, unit tests in a container
docker compose --profile test run --rm e2e       # Playwright against a tmpfs test database
docker compose --profile dev up -d               # optional: Vite hot reload on :47822
docker compose down                              # stop (add -v to drop the mock-data volume)
```

Expected:
- [ ] The dashboard opens with three projects: data-pipelines, patient360-web and payments-api.
- [ ] `tests` ends with the pytest summary and exit code 0. Latency gates are skipped in containers by design (`perf` marker).
- [ ] `e2e` ends with `37 passed`. Its database lives in tmpfs and disappears with the container.
- [ ] `docker compose ps` shows the dashboard as `healthy`, and `docker compose exec dashboard id` shows a non-root user.

---

## Part 3. CLI on mock data

```bash
uv tool install --force ./packages/cli          # puts `seen` and `seen-hook` on PATH
export SEEN_HOME=$SEEN_TEST/home
seen dev-seed --home "$SEEN_HOME"
seen audit verify
seen report --project demo-payments --days 7 | head -20
seen audit export --project demo-payments --format csv --out "$SEEN_TEST/export"
cd "$SEEN_HOME/demo-repos/payments-api" && seen memory list && seen skills scan && seen skills list && cd -
seen doctor
```

Expected:
- [ ] `dev-seed` prints `Seeded …: 3 projects, 98 sessions, 254 changes, 2033 events`. It refuses to run without an explicit scratch home.
- [ ] `audit verify` prints `Chain verified: 2033 events, head … Not anchored off this machine.`
- [ ] `report` lists changes with tokens, cost (`cost≈$…` with the price-table version), git status, files and skills.
- [ ] `export` writes `export.csv` plus a manifest with the event count, head hash and verification result.
- [ ] `memory list` shows four memories with status, type and the file each one describes.
- [ ] `doctor` prints `ok` for Python, ledger, audit chain and config. A `!!` for the plugin is expected until Part 9.

---

## Part 4. Dashboard: start it

```bash
SEEN_HOME=$SEEN_TEST/home SEEN_WEB_DIST=$PWD/web/dist seen serve --port 47826 --open
```

Open <http://127.0.0.1:47826>. Do Parts 5–8 in a desktop browser, then repeat a few of them at phone width
(DevTools device toolbar, 390px). Check the console stays free of errors throughout.

---

## Part 5. Dashboard: shell, Projects and Overview

**Shell**
- [ ] The left rail shows the round eyes mark (orange rim and brows, blue iris) beside "Seen". It looks around, blinks and lifts its brows now and then.
- [ ] Turn on "Reduce motion" in your OS settings and reload: the eyes stop moving.
- [ ] The theme switch (sun / monitor / moon, top right) changes light and dark at once. Reload: your choice is kept.
- [ ] The rail footer says `Audit chain verified (2,033)`.

**Projects** (`/`)
- [ ] Three project cards, each with the brand mark, changes, 7-day cost, last change and a red "Needs attention" badge.
- [ ] Click payments-api: you land on its Overview, and the rail's Project select now shows payments-api. The rail eyes stop wandering and stare with lowered brows (alert), because this project has open findings.

**Overview**
- [ ] Six summary tiles: Changes, Cost, Tokens, Memory loaded, Policy missed, Changes with PII exposure. Tiles that need attention are tinted with an icon.
- [ ] Switch the date range 7d → 14d → 28d: every figure and the chart update, and the URL keeps `range=`.
- [ ] Cost per day: hover a bar to see the tooltip. Click "Table view" to see the same numbers as a table.
- [ ] Needs attention: each item has a Review button that opens Changes with the matching filter applied.
- [ ] Most edited files: click a path to open Changes filtered to that file. Top skills: click one to filter by that skill.
- [ ] Top PII sources: click "Show deny rule" on `data/patients.csv` to see a `permissions.deny` snippet for `.claude/settings.json`.

---

## Part 6. Dashboard: Changes and Change detail

**Changes**
- [ ] The header shows `N changes · $X.XX`.
- [ ] Type in "Search changes": rows filter as you type.
- [ ] Try the Git status and Skill selects, then the chips Memory not loaded, Skill policy missed and PII exposed. Each one narrows the list and appears in the URL.
- [ ] Click a column header (When, Lines, Cost) to sort, and click again to reverse it.
- [ ] Focus a row with Tab and press Enter: it opens.

**Change detail**
- [ ] Shows the summary, a mono line (change #, time, tool, model, duration) and check badges.
- [ ] Files lists each path with `+added −removed` and HEAD before/after.
- [ ] Tokens and cost: input, output, cache read and cache write, each with its share of the cost.
- [ ] Prompt: by default it reads "Not stored (prompt storage is redacted)".
- [ ] Memory read, Skills used (with version hash, trigger and approval) and Required-skill checks (met or missed).
- [ ] Open a change flagged PII (filter with the PII exposed chip). A red banner says high-confidence data reached the model, and the PII table shows type, count, confidence, source and destination, never the values.
- [ ] Click "Mark as test data" on one finding: its status changes. Check it in Audit (Part 8) as an `approval.*` event.

---

**Sessions**
- [ ] Lists every session newest first with status (active, ended, incomplete), model, turns, tool calls, files and cost.
- [ ] While a `claude` session is running in the repo, its row shows **active** and updates within 10 seconds.
- [ ] Click a row: the drawer shows that session's activity in order (session.start, turns, tool calls, file changes, session.end).

## Part 7. Dashboard: Memory and Skills

**Memory**
- [ ] Count badges at the top right (for example `1 unverified`, `3 stale`).
- [ ] Stale memories are tinted and open by default, with "Why stale" naming the change that edited the file.
- [ ] Click "Re-verify" on a stale memory: it turns verified. Click "Archive": it leaves the list.
- [ ] The Freshness select and the type chips (decision, convention, gotcha, context) filter the list.

**Skills → Installed skills**
- [ ] The table shows each skill's kind, short version hash, status (approved, changed, unreviewed, blocked), runs and last used.
- [ ] `quick-sql-helper` is blocked and `tdd` is changed.
- [ ] Click `tdd`: a drawer opens with its versions. Click "Approve <hash>": the status becomes approved, and `.seen/skills.lock.json` in the demo repo now holds that hash.
- [ ] Block a skill, then "Unblock and approve" it.
- [ ] The Never used chip and the Kind and Status selects filter the table. The × closes the drawer.

**Skills → Required skills**
- [ ] Each rule shows the required skill, its paths, mode (report or enforce) and a compliance meter.
- [ ] "N missed →" opens Changes filtered to the misses.

---

## Part 8. Dashboard: Audit and Settings

**Audit**
- [ ] The green seal reads `Chain verified · 2,033 events`. The note under it explains that the chain is not anchored yet.
- [ ] Filter by event type (try `approval.*` and check your Part 6/7 actions are there), actor, session, date range and search.
- [ ] Click a row: the drawer shows seq, timestamps, actor, prev hash and hash, and a detail JSON with no prompt text, diffs or PII values.
- [ ] Use Newer / Older to page.
- [ ] Choose CSV and click Export: a status line shows `N events → <path> (verified)`.

**Tamper check** (stop the server first with Ctrl-C):

```bash
sqlite3 "$SEEN_TEST/home/audit.db" "UPDATE audit_events SET detail_json='{}' WHERE seq=100;"
```

- [ ] SQLite refuses with `audit_events is append-only` (a trigger). That is the first line of defence.
- [ ] Optional deeper check: copy `audit.db`, drop the triggers in the copy, edit one row, and point `seen audit verify` at a `SEEN_HOME` holding the copy. It reports the first broken seq.

**Settings** (`/settings`)
- [ ] Connected tools, PII detection, team sync (off), memory, skill auditing, audit retention, price table (marked unverified) and local data paths.
- [ ] Change PII Mode to `warn` and click Save: "Saved." appears. Reload: the setting is kept, and Audit has a `config.changed` event.
- [ ] Set it back to `report`.

**Phone width (390px)**
- [ ] The rail becomes a horizontal nav strip with the project switcher in the top bar. No sideways page scroll; wide tables scroll inside their own panel.

---

## Part 9. Install the plugin and record a real session

This uses a scratch repo and a scratch `SEEN_HOME`, so your real ledger is untouched. A short Sonnet session
costs a few cents.

```bash
export SEEN_HOME=$SEEN_TEST/live-home
mkdir -p "$SEEN_TEST/demo" && cd "$SEEN_TEST/demo" && git init -q -b main
printf 'def add(a, b):\n    return a + b\n' > calc.py && git add -A && git commit -qm init
seen init                                       # .seen/ folder, policies.yaml, pii.yaml, memory permission
claude plugin marketplace add surenganne/seen   # or: --plugin-dir /path/to/seen/plugin on each claude call
claude plugin install seen@seen-tools
seen doctor
claude -p "Add a subtract function to calc.py with a docstring." --permission-mode acceptEdits
seen status && seen report --days 1
```

Expected:
- [ ] `seen init` creates `.seen/` with `memory/`, `policies.yaml`, `pii.yaml` and `.gitignore`.
- [ ] `doctor` is all `ok`, including the plugin and `seen-hook on PATH`.
- [ ] After the session, `status` shows `Changes recorded: 1`, and `report` shows `calc.py +N −0`, real token counts and a cost estimate.
- [ ] Inside an interactive `claude` session, `/seen:status` summarises the same thing.
- [ ] Start the dashboard on this home (Part 4 command with `SEEN_HOME=$SEEN_TEST/live-home`): the demo project and the change appear.

---

## Part 9b. Import past sessions

```bash
cd "$SEEN_TEST/demo"
seen import --dry-run      # counts only, writes nothing
seen import                # records sessions from ~/.claude/projects/<this repo>/*.jsonl
seen import                # again: imports nothing new
```

- [ ] The dry run and the real run report the same session and change counts; `seen audit verify` still passes.
- [ ] Sessions shows the imported sessions with an **imported** tag; a session still running stays **active**.
- [ ] Change detail for an imported change shows the "Imported from the Claude Code transcript" note; tokens and
      cost match the transcript, git status is empty.
- [ ] Sessions recorded live (Part 9) are listed as already recorded and are not changed.

## Part 10. Memory with a real session

```bash
cd "$SEEN_TEST/demo"
seen memory add --id calc-ints --type convention --file-ref calc.py --text "calc.py functions take and return ints only."
seen memory verify calc-ints
claude -p "What type rules apply to calc.py? Answer in one line." 
seen report --days 1
```

- [ ] The answer mentions ints, because the memory was injected at session start.
- [ ] The newest change shows the memory as loaded (Change detail → Memory read lists `calc-ints`).
- [ ] Ask Claude to change `calc.py` (for example `claude -p "Add a divide function to calc.py." --permission-mode acceptEdits`).
  In the dashboard, `calc-ints` turns **stale**, and Why stale names that change. Re-verify clears it.

---

## Part 11. Required-skill rules

Edit `.seen/policies.yaml` in the demo repo:

```yaml
- id: pol-calc
  title: Review calc changes
  paths: ["calc.py"]
  require_skill: code-review
  mode: report
```

```bash
claude -p "Add a multiply function to calc.py." --permission-mode acceptEdits
```

- [ ] Change detail shows the rule as **missed**. Overview and Skills → Required skills count the miss.
- [ ] Switch `mode: enforce` and repeat: at Stop, Claude is told once that `code-review` is required before finishing. The audit trail records a `gate.decision`.

---

## Part 12. PII detection modes

Use synthetic values only: a made-up PAN `ABCPE1234F` and an email on a fictional domain. Never test with real personal
data. Public test card numbers such as `4111 1111 1111 1111` are deliberately ignored by the detector (they are
test data by definition), and `example.com` addresses are allowlisted by `seen init`, so neither raises a finding.

```bash
cd "$SEEN_TEST/demo"
claude -p "Customer PAN ABCPE1234F, contact jane.doe@fictional-corp.in. Made-up test values. Reply OK."
```

- [ ] `report` mode (default): the session runs. Change detail lists `email` and `pan` (medium confidence) with counts, source Prompt and destination Model. The stored prompt reads `Customer PAN [PAN], contact [EMAIL]. …`.
- [ ] Settings → PII Mode `warn`, run again: Claude Code shows a Seen warning, and the prompt is still sent.
- [ ] Mode `block`, run again: the prompt is stopped before it reaches the model.
- [ ] Put the same values in `data/customers.csv` and ask Claude to read it: the finding's source is File read, and Overview offers a deny rule for that path.
- [ ] Add `"data/**"` to `allow_paths` in `.seen/pii.yaml` and repeat: Audit shows a `pii.allowlisted` event and no new open finding for that file.
- [ ] Set the mode back to `report`.

---

## Part 13. Dashboard on your real data (optional)

```bash
unset SEEN_HOME                                   # your real ~/.seen
SEEN_WEB_DIST=$PWD/web/dist seen serve --port 47825 --open
```

- [ ] Shows your real `~/.seen` ledger. It runs on the host, not in Docker: SQLite WAL locking does not cross the Docker Desktop VM, so a container would read a torn database while hooks write (ADR 0008). Stop it with Ctrl-C.

---

## Part 14. Team server (Phase 5 skeleton, optional)

Secrets are generated on your machine and never printed or committed.

```bash
sh deploy/init-env.sh                                   # writes deploy/.env (0600)
docker compose -f deploy/docker-compose.team.yml --env-file deploy/.env up -d --build
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:47824/api/projects   # expect 401 without a key
uv run pytest -m pg                                     # team tests against the separate seen_team_test DB
```

- [ ] Both containers are healthy, and the API answers 401 without a key.
- [ ] The `pg` suite passes. It uses the `seen_team_test` database, not the team data.
- [ ] Sync check: mint a member key through `POST /api/keys` with the admin key from `deploy/.env` (read it into a variable; do not paste it into chat or tickets). Set `[sync] enabled = true` and `server = "http://127.0.0.1:47824"` in `$SEEN_HOME/config.toml`, export the member key as `SEEN_TEAM_API_KEY`, and run `seen sync`. It reports the batch and `audit anchored through seq N`, and the local audit trail records a `sync.batch` event.
- [ ] Only metadata syncs: no prompts, diffs, file contents or PII values.

---

## Clean up

```bash
docker compose down -v
docker compose -f deploy/docker-compose.team.yml --env-file deploy/.env down -v
claude plugin uninstall seen@seen-tools          # if you installed it only for this test
rm -rf "$SEEN_TEST"
unset SEEN_HOME SEEN_TEST
```

## When something fails

| Symptom | Look at |
|---|---|
| Session not recorded | `seen doctor`; `$SEEN_HOME/log/hook.log`; hooks fail open by design, so Claude keeps working |
| Dashboard shows "Not found" for an API call | An older `seen serve` is still running on that port; stop it and start again |
| Playwright fails on CSP | The console guard prints the blocked resource; everything must load from `'self'` |
| Chain not verified | `seen audit verify` names the first broken seq and why |

Open an issue at <https://github.com/surenganne/seen/issues> with the `seen doctor` output. Remove paths,
names and any personal data first.
