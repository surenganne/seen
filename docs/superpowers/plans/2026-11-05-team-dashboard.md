# Team Dashboard Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a read-only `/team` page to the Seen dashboard that shows the team server's per-project aggregates (changes, lines, cost, skills, models, PII type counts).

**Architecture:** The local FastAPI (`seen_local`) gets a small server-side client for the team server and two GET routes under `/api/team/*`. The team API key stays in the host environment (`api_key_env`, default `SEEN_TEAM_API_KEY`) and never reaches the browser. Every team failure becomes a 200 with a `state` and a fixed `reason`, so the page always renders. The React page reads those routes like any other.

**Tech Stack:** FastAPI + Pydantic, stdlib `urllib` (no new dependency), React + TanStack Query + openapi-fetch, Vitest, Playwright.

**Spec:** None written (brainstorming skipped at the owner's request). The design calls are listed under "Calls made" below. Source facts: `docs/schema.md`, `packages/team_server/src/seen_team/app.py` (`/api/projects`, `/api/projects/{pid}/overview`), `packages/core/src/seen_core/sync.py::_server`.

## Prerequisite: SSO

This plan assumes a key exists. Today that is a hand-minted API key from an env var, and there is no SSO. `2026-11-05-team-sso.md` replaces it with sign-in through the company IdP. Build SSO-0 to SSO-3 first. When it lands:
- The key comes from `SEEN_TEAM_API_KEY` first, then `teamauth.load_key()` (the `~/.seen/team_key` file written by `seen team login`). TD-1's `fetch` uses `sync.server_and_key`, which already follows that order.
- `TeamState` gains `login_required` (no key anywhere). The page shows "Sign in with SSO" instead of the env-var instructions. The reason string for `not_configured` is only used when no server URL is set.
- Without SSO this plan still works with a manually minted key, but the members list then shows only pseudonymous ids.

## Calls made (owner to confirm)

- Proxy through the local server, not a team-server-hosted UI and not a browser-held key.
- Overview aggregates only. No per-person change detail (the team server already restricts that to the person; the local dashboard shows your own changes).
- **Last synced per member** is the one per-person item. It is "when the team server last accepted a batch from that member's key", read from `team_batches`, not from the newest change. A member who syncs but has done no new work still shows as fresh. Visible to `lead` and `admin` keys only.
- A member is shown by `user_id` (a keyed pseudonymous actor id, not a name). That is still personal data under DPDP, so it is lead/admin-only and the ADR in TD-4 records it as a decision item.
- A member counts as **stale** when the last sync is older than 24 hours (constant `STALE_AFTER_H = 24` in `Team.tsx`, my call). **Never synced** is a separate state, so "missing" and "late" are distinguishable.
- No audit-anchor panel in v1 (follow-up).
- Works from the host dashboard (`seen serve`). The Docker snapshot dashboard has no key in its environment, so it shows the "not configured" state.
- Viewing needs `sync.server` and the key env var only. It does not need `sync.enabled`.

## Global Constraints

- The API key comes from the env var named by `sync.api_key_env`. Never in config, a response body, a log line, an error `reason` or a test fixture that looks like a real key.
- `https` only, except `http` for `localhost`, `127.0.0.1` or `::1` (same rule as `sync._server`). Reuse it, do not copy it.
- Repo rule: never write a PII value, secret, prompt text or command argument to logs. Team data here is aggregate metadata only.
- Never show a bare "no PII" or "clean" label. Say what was checked.
- Cost comes from the server as `cost_usd`. Format with `web/src/lib/format.ts::money`. Do not hardcode prices.
- UI: tokens from `web/src/styles/tokens.css` only, IBM Plex, lucide icons, no side stripes or eyebrows. Keep test ids and accessible names stable.
- After changing routes or schemas: `uv run python scripts/gen_openapi.py && (cd web && npm run gen:api)`.
- Gates: `uv run ruff check . && uv run mypy packages/core/src && uv run pytest`, `uv run python scripts/gen_openapi.py --check`, and in `web`: `npm run lint && npm run typecheck && npm test && npm run check:api && npx playwright test`.
- Commit messages name the task ID (`TD-0` ... `TD-4`).

## Review Focus

1. **Redirect from the team server** to another host must not forward the `Authorization` header. Result: state `unreachable`, no second request. Pinned in TD-1.
2. **Path injection:** a `pid` like `../keys`, `a%2Fb`, `x?y=1` or 65 characters is refused with 422 before any outbound request. Pinned in TD-2.
3. **Hostile or malformed team response** (extra or missing fields, wrong types, body over 2 MB, non-JSON): state `bad_response`, never a 500, never echoed. Pinned in TD-1.
4. **Key leakage:** a sentinel key value never appears in any `/api/team/*` response, including every error state. Pinned in TD-2.
5. **Project id or name containing markup** (`<img src=x onerror=...>`) renders as text on the page. Pinned in TD-3.
6. **Members list privacy and accuracy:** a `member` key gets 403 on the members route (no one sees colleagues). A revoked or erased user does not appear. A user with a key but no batch shows "never synced", and one whose key expired is marked expired, so neither looks like a late sync. Pinned in TD-0 and TD-3.

---

### Task 0: TD-0 Team server members route (last synced per member)

**Files:**
- Modify: `packages/team_server/src/seen_team/app.py` (new route after `/api/projects/{pid}/changes`)
- Test: `tests/team/test_members.py` (uses the `team`, `admin`, `make_key` helpers from `tests/team/conftest.py`)

**Interfaces:**
- Produces: `GET /api/projects/{pid}/members` returns `list[{user_id: str, last_synced_at: str | None, changes: int, key_expired: bool}]`, sorted by `user_id`.
  - Auth: `can_see(k, pid)`, then `lead` or `admin` only. A `member` key gets 403 `"only leads and admins can list members"`.
  - One entry per distinct `user_id` among non-revoked `member` keys with `project_id == pid`.
  - `last_synced_at` is the newest `TeamBatch.received_at` across that user's keys, or `None` if none.
  - `changes` is the count of that user's `TeamChange` rows in the project.
  - `key_expired` is true when every one of the user's non-revoked keys has `expires_at <= now()`.

- [ ] **Step 1: Write the failing tests** in `tests/team/test_members.py`:
  - `test_lists_each_member_with_last_synced`: two members push batches. Assert both appear, with `last_synced_at` equal to each one's own newest batch time (not the other's) and `changes` counts.
  - `test_synced_with_no_new_changes_still_counts`: a batch with `changes=[]` and an audit head moves `last_synced_at`.
  - `test_never_synced_is_none`: a member key with no batch gives `last_synced_at is None`.
  - `test_member_key_is_forbidden`: 403 for a `member` key, 200 for `lead` and `admin`.
  - `test_other_project_is_forbidden`: a `lead` scoped to project A gets 403 on project B.
  - `test_revoked_and_erased_users_disappear`: after `DELETE /api/users/{id}` the user is not listed.
  - `test_expired_key_is_flagged`: a member whose only key is expired shows `key_expired: true` with the last sync time preserved.
- [ ] **Step 2: Run to verify failure:** `uv run pytest tests/team/test_members.py -v`. Expected: FAIL (404 on the route).
- [ ] **Step 3: Implement** the route with one SQL join of `TeamApiKey` and `TeamBatch` grouped by `user_id`, plus one count query on `TeamChange`.
- [ ] **Step 4: Run to verify pass:** `uv run pytest tests/team -q`. Expected: PASS. (The `pg` marker runs the same tests against Postgres once the stack is up.)
- [ ] **Step 5: Commit:** `git add packages/team_server tests/team && git commit -m "TD-0: team server members route with last synced"`

### Task 1: TD-1 Team client in the local server

**Files:**
- Modify: `packages/core/src/seen_core/sync.py` (add public `server_and_key`)
- Create: `packages/local_server/src/seen_local/team.py`
- Test: `tests/local/test_team_client.py`

**Interfaces:**
- Produces in `sync.py`: `def server_and_key() -> tuple[str, str]` that delegates to `_server()` unchanged. It raises `SyncError`.
- Produces in `team.py`:
  - `TeamState = Literal["ok", "not_configured", "unreachable", "unauthorized", "forbidden", "bad_response"]`
  - `class TeamResult(NamedTuple): state: TeamState; reason: str | None; body: Any`
  - `REASONS: dict[TeamState, str]`, fixed strings, one per non-ok state. The `not_configured` text names the env var and says to run the host dashboard (`seen serve`).
  - `def fetch(path: str, query: dict[str, int] | None = None) -> TeamResult`. It GETs `<server><path>` with `Authorization: Bearer <key>`, a 10 s timeout, a 2 MB response cap, and redirects disabled. The module-level `_open(req) -> tuple[int, bytes]` is the single network seam tests monkeypatch.

- [ ] **Step 1: Write the failing tests** in `tests/local/test_team_client.py`, monkeypatching `team._open`. Use `seen_home` and `monkeypatch.setenv` with the sentinel key `"sentinel-" + "z" * 40`:
  - `test_not_configured_without_server_or_key`: state `not_configured`, `_open` never called.
  - `test_sends_bearer_and_returns_json`: asserts `Authorization` header equals `Bearer <sentinel>`, state `ok`, body parsed.
  - `test_status_mapping`: 401 gives `unauthorized`, 403 gives `forbidden`, 0/500/404/429 give `unreachable`.
  - `test_redirect_is_not_followed`: drive the real `_open` against a local `http.server` thread that answers 302 to a second port. Assert the second port received no request, state `unreachable`.
  - `test_bad_body_states`: non-JSON, JSON list where an object is expected, and a body over 2 MB each give `bad_response`.
  - `test_reason_never_contains_the_key`: for every state, `sentinel not in repr(result)`.
- [ ] **Step 2: Run to verify failure:** `uv run pytest tests/local/test_team_client.py -v`. Expected: FAIL (module missing).
- [ ] **Step 3: Implement** `server_and_key` and `team.py`. `_open` uses `urllib.request.build_opener` with a redirect handler whose `redirect_request` returns `None`. A 3xx surfaces as `HTTPError` and maps to `unreachable`. Map `SyncError` to `not_configured` without using its message.
- [ ] **Step 4: Run to verify pass:** same command. Expected: PASS.
- [ ] **Step 5: Commit:** `git add packages/core/src/seen_core/sync.py packages/local_server/src/seen_local/team.py tests/local/test_team_client.py && git commit -m "TD-1: team server client for the local dashboard"`

### Task 2: TD-2 `/api/team/*` routes and schemas

**Files:**
- Modify: `packages/local_server/src/seen_local/schemas.py`, `packages/local_server/src/seen_local/app.py` (two routes, placed after `/api/settings`)
- Test: `tests/local/test_api_team.py`
- Regenerate: `docs/openapi.json` (whatever `scripts/gen_openapi.py` writes), `web/src/api/schema.d.ts`

**Interfaces:**
- Consumes: `team.fetch`, `team.TeamState` from TD-1.
- Produces schemas (field names match the team server payload exactly):
  - `TeamProjectOut{id: str, name: str, changes: int, last_change_at: str | None, cost_7d: float}`
  - `TeamProjects{state: TeamState, reason: str | None, projects: list[TeamProjectOut]}`
  - `TeamTiles{changes, lines_added, lines_removed, policy_missed, pii_changes: int; cost_usd: float}`
  - `TeamOverviewOut{state, reason, range: int | None, tiles: TeamTiles | None, cost_by_day: list[{date: str, by_tool: dict[str, float]}], top_skills: list[{skill_id: str, runs: int}], by_model: list[{model: str, changes: int, tok_out: int, cost_usd: float}], pii_by_type: list[{type: str, count: int}]}`. The lists default to `[]`.
  - `TeamMemberOut{user_id: str, last_synced_at: str | None, changes: int, key_expired: bool}`
  - `TeamMembers{state: TeamState, reason: str | None, members: list[TeamMemberOut]}`
  - Routes: `GET /api/team/projects` -> `TeamProjects`; `GET /api/team/projects/{pid}/overview?range=7|14|28` -> `TeamOverviewOut`; `GET /api/team/projects/{pid}/members` -> `TeamMembers`. All return 200 for every team state. The team server's 403 on members (a `member` key) maps to state `forbidden` like any other 403.
- Validation: `pid` must match `^[A-Za-z0-9_.:-]{1,64}$` and not be `.` or `..`, else 422. `range` must be 7, 14 or 28, else 422 (same as the local overview). The `pid` goes into the outbound path via `urllib.parse.quote(pid, safe="")`.
- Body validation: parse the team body through the response models. A `ValidationError` gives state `bad_response`.

- [ ] **Step 1: Write the failing tests** in `tests/local/test_api_team.py`, monkeypatching `team._open` and using the `client` fixture:
  - `test_projects_ok_maps_body`
  - `test_overview_ok_maps_tiles_and_lists`
  - `test_not_configured_is_200_with_reason`
  - `test_each_team_failure_is_200_with_state`: 401, 403, 500 and a malformed body.
  - `test_pid_is_validated_before_any_request`: `["../keys", "a%2Fb", "x?y=1", "a" * 65, ".."]` each give 422 and `_open` not called.
  - `test_members_ok_maps_body_and_drops_extra_fields`
  - `test_members_forbidden_state_for_member_key`
  - `test_members_pid_is_validated` (same hostile ids as above)
  - `test_range_must_be_7_14_28`
  - `test_extra_team_fields_are_dropped_not_forwarded`
  - `test_key_never_in_any_response`: the sentinel key against every state above.
  - `test_post_is_rejected`: the existing `X-Seen-Request` guard and the 405 for non-GET still hold.
- [ ] **Step 2: Run to verify failure:** `uv run pytest tests/local/test_api_team.py -v`. Expected: FAIL (404 on routes).
- [ ] **Step 3: Implement** the schemas and the two routes. The route body is `r = team.fetch(...)`, then build the model from `r.body` when state is `ok`.
- [ ] **Step 4: Regenerate and verify:** `uv run python scripts/gen_openapi.py && (cd web && npm run gen:api) && uv run pytest tests/local -q && uv run python scripts/gen_openapi.py --check`. Expected: PASS.
- [ ] **Step 5: Commit:** `git add packages/local_server tests/local docs web/src/api/schema.d.ts && git commit -m "TD-2: /api/team routes proxy team aggregates"`

### Task 3: TD-3 Team page in the web app

**Files:**
- Create: `web/src/pages/Team.tsx`
- Modify: `web/src/api/hooks.ts` (add `useTeamProjects`, `useTeamOverview`), `web/src/App.tsx` (lazy route `/team`), `web/src/components/Layout.tsx` (NavLink "Team" with the lucide `Users` icon before Settings; breadcrumb title "Team" like the Settings branch), `web/src/test/mock-api.ts` (team handlers)
- Test: `web/src/pages/pages.test.tsx` (add Team cases)

**Interfaces:**
- Consumes: `/api/team/projects`, `/api/team/projects/{pid}/overview`, `/api/team/projects/{pid}/members` from TD-2 via generated `schema.d.ts`. Hooks added: `useTeamMembers(pid)`.
- Members card (card title "Last synced"), shown for the selected project:
  - One row per member: `user_id` (mono), last sync as a relative time via `lib/format.ts::when` with the exact time in a `title`, and `changes`.
  - Status badge per row: **Synced** (within `STALE_AFTER_H = 24` hours), **Stale** (older), **Never synced** (`last_synced_at` null), **Key expired** (`key_expired`). Colour is never the only signal; the text is always present.
  - If the members route returns `forbidden` (a `member` key), the card shows one line: "Only leads and admins can see who has synced." The rest of the page is unaffected.
  - Caption: "Last time the team server accepted data from each member's machine. A member who has not synced is missing from the totals above."
  - Test id: `team-member-row`.
- Produces: `export function Team()`. Selected project lives in the `?project=` search param, range in `?range=` via `useRange`. Test ids: `team-state`, `team-project-row`, `team-tile`.
- Behaviour:
  - Any state other than `ok` shows the `reason` in a `Note` (`testId="team-state"`). `not_configured` uses an `Empty` that explains the two settings (`sync.server` and the key env var) without ever showing a key.
  - `ok` shows a project table (name, changes, cost 7 d, last change) and, for the selected project, `Tile`s, `MagnitudeBars` for skills, models and PII types, and a plain table of cost by day.
  - PII block: the caption says what is counted: "PII types and counts only, from machines where PII counts sync is on."
  - Page head description: "Metadata synced from team members' machines. Prompts, diffs and PII values are never synced."

- [ ] **Step 1: Write the failing tests** in `pages.test.tsx` (the shared Case table plus Team-specific tests):
  - `Team` renders the project rows and tiles for the `ok` mock.
  - `not_configured` renders `team-state` with the reason and no table.
  - Each of `unauthorized`, `forbidden`, `unreachable` and `bad_response` renders its reason.
  - A project named `<img src=x onerror=alert(1)>` renders as visible text and no `img` element exists.
  - The caption text for PII is present.
  - Members card: a fixed `now` (fake timers) with members at 1 h, 30 h, `null` and `key_expired` renders the badges **Synced**, **Stale**, **Never synced**, **Key expired** in that order.
  - Members `forbidden` renders the one-line message and the overview tiles still render.
  - A `user_id` containing markup renders as text.
- [ ] **Step 2: Run to verify failure:** `cd web && npx vitest run src/pages/pages.test.tsx`. Expected: FAIL (module missing).
- [ ] **Step 3: Implement** the hooks (same `unwrap(api.GET(...))` pattern as `useOverview`, `keepPreviousData` for the overview), the page, the route and the nav link.
- [ ] **Step 4: Run to verify pass:** `cd web && npm run lint && npm run typecheck && npm test`. Expected: PASS.
- [ ] **Step 5: Commit:** `git add web && git commit -m "TD-3: team dashboard page"`

### Task 4: TD-4 E2E, docs, security review, live check

**Files:**
- Create: `web/e2e/team.spec.ts`, `docs/adr/<next number>-team-dashboard-proxy.md`
- Modify: `web/e2e/a11y.spec.ts` (add `/team`), `docs/TESTING.md` (Part 14 checklist), `docs/schema.md` (one line), `CLAUDE.md` (one line: the dashboard can call the team server when `sync.server` is set)
- Test: the e2e spec itself

**Interfaces:**
- Consumes: the page and test ids from TD-3. The Playwright suite runs against a seeded local server, so `web/e2e/team.spec.ts` uses `page.route("**/api/team/**", ...)` to return the `ok` and `not_configured` states. This avoids needing Postgres.

- [ ] **Step 1: Write the e2e test:** golden path (`ok` shows rows, selecting a project updates the tiles and the members card, range switch reloads) and edge cases (`unreachable` shows the reason and the page stays usable; a never-synced member shows "Never synced"). Add `/team` to the axe pass in both themes.
- [ ] **Step 2: Run:** `cd web && npx playwright test e2e/team.spec.ts e2e/a11y.spec.ts`. Expected: PASS.
- [ ] **Step 3: Write the ADR** (why proxy and not browser key; outbound call only when configured; Docker dashboard limitation) and the docs lines.
- [ ] **Step 4: Security pass:** run `security-review` on the branch. The change adds outbound authenticated calls from the dashboard, so the §5 rule applies. Fix confirmed findings test-first.
- [ ] **Step 5: Live check (manual gate):** needs `sh deploy/init-env.sh` and the team stack up. Mint a `lead` key, export it as `SEEN_TEAM_API_KEY` in the shell that runs `seen serve`, set `[sync] server = "http://127.0.0.1:47824"`, run `seen sync`, then open `/team`. Verify with `curl` that `/api/team/projects` contains no key and that a wrong key shows "unauthorized". Record the evidence in the PR. If the stack is not up, say "live verification not done" in the PR instead.
- [ ] **Step 6: Run all gates** from Global Constraints. Expected: all pass.
- [ ] **Step 7: Commit:** `git add web docs CLAUDE.md && git commit -m "TD-4: team page e2e, docs and ADR"`

---

## Self-review

- **Coverage:** last synced per member (TD-0 server route, TD-2 proxy, TD-3 card); key stays server-side (TD-1, TD-2), never reaches the browser; page and states (TD-3); e2e, accessibility, docs, security and live check (TD-4). Anchor panel and per-person change detail are explicit non-goals.
- **Types:** `TeamState`, `TeamResult`, `TeamProjects`, `TeamOverviewOut`, `TeamMemberOut`, `TeamMembers` are named identically in TD-1, TD-2 and TD-3. `TeamMemberOut` fields match the TD-0 route.
- **Review Focus:** each of the five lines has a named test in the owning task.
