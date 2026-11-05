import { expect, mockTeam, test } from "./fixtures";

test.describe("team page", () => {
  test("shows projects, switches project and reloads on range change", async ({ page }) => {
    const { calls } = await mockTeam(page);
    await page.goto("/team");
    await expect(page.getByTestId("team-project-row")).toHaveCount(2);
    await expect(page.getByTestId("tile-Changes").getByText("111", { exact: true })).toBeVisible();
    await expect(page.getByText("member-of-tp1")).toBeVisible();
    await page.getByRole("button", { name: "beta" }).click();
    await expect(page.getByTestId("tile-Changes").getByText("222", { exact: true })).toBeVisible();
    await expect(page.getByTestId("tile-Changes").getByText("111", { exact: true })).toHaveCount(0);
    await expect(page.getByText("member-of-tp2")).toBeVisible();
    await expect(page.getByTestId("team-member-row").getByText("Never synced")).toBeVisible();
    await page.getByRole("group", { name: "Date range" }).getByRole("button", { name: "14d" }).click();
    await expect.poll(() => calls.some((c) => c.includes("tp2/overview?range=14"))).toBe(true);
  });

  test("signed in: shows who, and sign out calls logout then offers sign-in", async ({ page }) => {
    let out = false;
    const { calls } = await mockTeam(page, {
      "/api/team/session": () => (out ? { state: "signed_out", email: null, role: null } : { state: "signed_in", email: "lead@example.test", role: "lead" }),
      "/api/team/logout": () => { out = true; return { state: "signed_out" }; },
      "/api/team/projects": () => (out ? { state: "login_required", reason: "Sign in to see the team.", projects: [] } : TEAM_PROJECTS),
    });
    await page.goto("/team");
    await expect(page.getByTestId("team-session")).toHaveText("Signed in as lead@example.test (lead)");
    await page.getByTestId("team-signout").click();
    await expect(page.getByTestId("team-signin")).toBeVisible();
    expect(calls.some((c) => c.startsWith("POST /api/team/logout"))).toBe(true);
  });

  test("signed out: Sign in with SSO navigates to the https URL from the server", async ({ page }) => {
    await page.route("https://sso.example.test/**", (r) => r.fulfill({ contentType: "text/html", body: "<title>idp</title>idp" }));
    await mockTeam(page, {
      "/api/team/session": { state: "signed_out", email: null, role: null },
      "/api/team/projects": { state: "login_required", reason: "Sign in to see the team.", projects: [] },
    });
    await page.goto("/team");
    await page.getByRole("button", { name: "Sign in with SSO" }).click();
    await page.waitForURL("https://sso.example.test/start");
  });

  test("sign-in unavailable shows the fixed message and stays on the page", async ({ page }) => {
    await mockTeam(page, {
      "/api/team/session": { state: "signed_out", email: null, role: null },
      "/api/team/projects": { state: "login_required", reason: "Sign in to see the team.", projects: [] },
      "/api/team/login": { url: null, reason: "unavailable" },
    });
    await page.goto("/team");
    await page.getByTestId("team-signin").click();
    await expect(page.getByText("Sign-in is unavailable right now. Try again later.")).toBeVisible();
    await expect(page).toHaveURL(/\/team/);
  });

  test("unreachable shows the reason and the rest of the app still works", async ({ page }) => {
    await mockTeam(page, { "/api/team/projects": { state: "unreachable", reason: "The team server did not answer.", projects: [] } });
    await page.goto("/team");
    await expect(page.getByTestId("team-state")).toHaveText(/did not answer/);
    await page.getByRole("link", { name: "Projects" }).first().click();
    await expect(page.getByRole("heading", { level: 1, name: /projects/i })).toBeVisible();
  });

  test("hostile project name and members forbidden", async ({ page }) => {
    await mockTeam(page, {
      "/api/team/projects": { state: "ok", reason: null, projects: [{ id: "tp1", name: "<img src=x onerror=alert(1)>", changes: 1, cost_7d: 0, last_change_at: null }] },
      "/api/team/projects/tp1/members": { state: "forbidden", reason: "no", members: [] },
    });
    await page.goto("/team");
    await expect(page.getByRole("button", { name: "<img src=x onerror=alert(1)>" })).toBeVisible();
    await expect(page.locator("main img")).toHaveCount(0);
    await expect(page.getByText("Only leads and admins can see who has synced.")).toBeVisible();
    await expect(page.getByTestId("team-tile").first()).toBeVisible();
  });
});

const TEAM_PROJECTS = {
  state: "ok", reason: null,
  projects: [{ id: "tp1", name: "alpha", changes: 11, cost_7d: 1.5, last_change_at: "2026-11-04T10:00:00Z" }],
};
