import fixtures from "./fixtures.json";

/** The API as the pages see it, from responses captured off a seeded scratch home (scripts/capture_web_fixtures.py).
 *  ok: the captured data. empty: the same shapes with every list emptied. down: every call answers 500. */
export type Mode = "ok" | "empty" | "down";
export const state: { mode: Mode; calls: string[]; team: Record<string, unknown> } = { mode: "ok", calls: [], team: {} };
export const ids = (fixtures as unknown as { _ids: { pid: string; cid: string } })._ids;

function empty(v: unknown): unknown {
  if (Array.isArray(v)) return [];
  if (v && typeof v === "object") return Object.fromEntries(Object.entries(v).map(([k, x]) => [k, k === "total" ? 0 : empty(x)]));
  return v;
}

export const TEAM_PID = "tp1";
/** The team routes. Not captured fixtures (the scratch home has no team server); a test overrides one with state.team[path]. */
const TEAM: Record<string, unknown> = {
  "/api/team/session": { state: "signed_in", email: "lead@example.test", role: "lead" },
  "/api/team/login": { url: "https://sso.example.test/start", reason: null },
  "/api/team/logout": { state: "signed_out" },
  "/api/team/sso": {
    state: "ok", reason: null, sso: "configured", client_id: "cid-1", provider_host: "login.microsoftonline.com",
    server: { configured: true, issuer: "https://login.microsoftonline.com/t/v2.0", client_id: "cid-1", allowed_domains: ["example.test"],
      bootstrap_key_enabled: false, admin_count: 2, proxy_hops: 1 },
  },
  "/api/team/projects": {
    state: "ok", reason: null,
    projects: [{ id: TEAM_PID, name: "payments-api", changes: 42, cost_7d: 12.5, last_change_at: "2026-11-04T10:00:00Z" }],
  },
  [`/api/team/projects/${TEAM_PID}/overview`]: {
    state: "ok", reason: null, range: 7,
    tiles: { changes: 42, cost_usd: 12.5, lines_added: 900, lines_removed: 120, pii_changes: 3, policy_missed: 1 },
    cost_by_day: [{ date: "2026-11-03", by_tool: { claude: 5, codex: 2.5 } }],
    top_skills: [{ skill_id: "tdd", runs: 7 }],
    by_model: [{ model: "model-a", changes: 30, cost_usd: 9, tok_out: 1000 }],
    pii_by_type: [{ type: "email", count: 3 }],
  },
  [`/api/team/projects/${TEAM_PID}/members`]: {
    state: "ok", reason: null,
    members: [{ user_id: "u-1", email: "dev@example.test", last_synced_at: "2026-11-04T10:00:00Z", changes: 42, key_expired: false }],
  },
};

export async function mockFetch(input: RequestInfo | URL): Promise<Response> {
  const url = new URL(typeof input === "string" ? input : input instanceof URL ? input.href : input.url, "http://localhost");
  state.calls.push(url.pathname);
  const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
  if (url.pathname.startsWith("/api/team/") && state.mode !== "down") {
    const found = state.team[url.pathname] ?? TEAM[url.pathname];
    const body = typeof found === "function" ? await (found as () => Promise<unknown>)() : found; // a function lets a test delay or compute the answer
    if (body === undefined) return json(404, { detail: `no team mock for ${url.pathname}` });
    if (state.mode === "empty" && url.pathname === "/api/team/projects") return json(200, { state: "ok", reason: null, projects: [] });
    return json(200, body);
  }
  if (state.mode === "down") return json(500, { detail: "the ledger is unavailable" });
  const hit = (fixtures as Record<string, unknown>)[url.pathname];
  if (hit === undefined) return json(404, { detail: `no fixture for ${url.pathname}` });
  return json(200, state.mode === "empty" ? empty(hit) : hit);
}
