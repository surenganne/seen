import { expect, test as base } from "@playwright/test";

/** Every page fails on a CSP violation or console error: CSP can silently break fonts, charts and workers. */
export const test = base.extend<{ guard: void; expectedErrors: RegExp[] }>({
  expectedErrors: [[], { option: true }],
  guard: [
    async ({ page, expectedErrors }, use) => {
      const problems: string[] = [];
      await page.addInitScript(() => {
        document.addEventListener("securitypolicyviolation", (e) => {
          (window as unknown as { __csp: string[] }).__csp = [...((window as unknown as { __csp?: string[] }).__csp ?? []), `${e.violatedDirective} ${e.blockedURI}`];
        });
      });
      page.on("console", (m) => { if (m.type() === "error" && !expectedErrors.some((r) => r.test(m.text()))) problems.push(m.text()); });
      page.on("pageerror", (e) => problems.push(e.message));
      await use();
      const csp = await page.evaluate(() => (window as unknown as { __csp?: string[] }).__csp ?? []).catch(() => []);
      expect(csp, "CSP violations").toEqual([]);
      expect(problems, "console errors").toEqual([]);
    },
    { auto: true },
  ],
});
export { expect };

/** Mocks every /api/team/* route (the e2e server has no team server). `over` replaces a response per path; a function gets the request. */
export type TeamMock = Record<string, unknown | ((req: { method: string; url: URL }) => unknown)>;
export const TEAM_DEFAULTS: TeamMock = {
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
    projects: [
      { id: "tp1", name: "alpha", changes: 11, cost_7d: 1.5, last_change_at: "2026-11-04T10:00:00Z" },
      { id: "tp2", name: "beta", changes: 22, cost_7d: 2.5, last_change_at: "2026-11-03T10:00:00Z" },
    ],
  },
};
const overview = (changes: number, range: number) => ({
  state: "ok", reason: null, range,
  tiles: { changes, cost_usd: 3, lines_added: 10, lines_removed: 2, pii_changes: 1, policy_missed: 0 },
  cost_by_day: [{ date: "2026-11-03", by_tool: { claude: 3 } }], top_skills: [{ skill_id: "tdd", runs: 4 }],
  by_model: [{ model: "model-a", changes, cost_usd: 3, tok_out: 100 }], pii_by_type: [{ type: "email", count: 1 }],
});
const members = (id: string) => ({ state: "ok", reason: null, members: [{ user_id: id, email: null, last_synced_at: null, changes: 1, key_expired: false }] });

export async function mockTeam(page: import("@playwright/test").Page, over: TeamMock = {}): Promise<{ calls: string[] }> {
  const calls: string[] = [];
  await page.route("**/api/team/**", async (route) => {
    const req = route.request();
    const url = new URL(req.url());
    const p = url.pathname;
    calls.push(`${req.method()} ${p}${url.search}`);
    let body: unknown = { ...TEAM_DEFAULTS, ...over }[p];
    if (typeof body === "function") body = (body as (r: { method: string; url: URL }) => unknown)({ method: req.method(), url });
    const m = /^\/api\/team\/projects\/(\w+)\/(overview|members)$/.exec(p);
    if (body === undefined && m) body = m[2] === "overview" ? overview(m[1] === "tp1" ? 111 : 222, Number(url.searchParams.get("range") ?? 7)) : members(`member-of-${m[1]}`);
    await route.fulfill({ status: body === undefined ? 404 : 200, contentType: "application/json", body: JSON.stringify(body ?? { detail: "no mock" }) });
  });
  return { calls };
}
