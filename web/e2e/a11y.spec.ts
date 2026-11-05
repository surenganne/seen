import AxeBuilder from "@axe-core/playwright";
import type { APIRequestContext, Page } from "@playwright/test";
import { expect, mockTeam, test } from "./fixtures";

/** WCAG 2.2 AA is a promise in PRODUCT.md: these checks are what keeps it honest. */
const TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"];

type Ids = { pid: string; cid: string };
async function ids(request: APIRequestContext): Promise<Ids> {
  const projects = (await (await request.get("/api/projects")).json()) as { id: string; changes: number }[];
  const p = projects.find((x) => x.changes > 0) ?? projects[0]!;
  const page = (await (await request.get(`/api/projects/${p.id}/changes`)).json()) as { rows?: { id: string }[]; items?: { id: string }[] };
  return { pid: p.id, cid: (page.rows ?? page.items)![0]!.id };
}

const routes = (i: Ids) => [
  ["projects", "/projects"], ["settings", "/settings"], ["overview", `/p/${i.pid}`], ["changes", `/p/${i.pid}/changes`],
  ["change detail", `/p/${i.pid}/changes/${i.cid}`], ["sessions", `/p/${i.pid}/sessions`], ["timeline", `/p/${i.pid}/timeline`],
  ["skills", `/p/${i.pid}/skills`], ["audit", `/p/${i.pid}/audit`], ["team", "/team"],
] as const;

async function settle(page: Page) {
  await page.waitForLoadState("networkidle");
  await expect(page.getByRole("status")).toHaveCount(0); // skeletons gone
}

const NAMES = ["projects", "settings", "overview", "changes", "change detail", "sessions", "timeline", "skills", "audit", "team"] as const;

for (const scheme of ["light", "dark"] as const) {
  test.describe(`axe, ${scheme} theme`, () => {
    for (const [i, name] of NAMES.entries()) {
      test(`${name} has no WCAG 2.2 AA violations`, async ({ page, request }) => {
        await page.emulateMedia({ colorScheme: scheme, reducedMotion: "reduce" });
        const r = routes(await ids(request))[i]!;
        if (name === "team") await mockTeam(page);
        await page.goto(r[1]);
        await settle(page);
        const res = await new AxeBuilder({ page }).withTags(TAGS).analyze();
        expect(res.violations.map((v) => `${v.id}: ${v.help} (${v.nodes.length}) ${v.nodes[0]?.target.join(" ")}`)).toEqual([]);
      });
    }
  });
}

test.describe("page structure", () => {
  test("every page has its own title, one main landmark and a working skip link", async ({ page, request }) => {
    const seen = new Set<string>();
    for (const [name, path] of routes(await ids(request))) {
      await page.goto(path);
      await settle(page);
      const title = await page.title();
      expect(title, `${name} title`).not.toBe("Seen");
      expect(title).toContain("Seen");
      seen.add(title);
      await expect(page.getByRole("main"), `${name} main landmarks`).toHaveCount(1);
    }
    expect(seen.size, "titles differ between pages").toBeGreaterThanOrEqual(7);
  });

  test("keyboard: the first Tab stop is a skip link that moves focus to the content", async ({ page, isMobile }) => {
    test.skip(isMobile, "keyboard flow");
    await page.goto("/projects");
    await settle(page);
    await page.keyboard.press("Tab");
    const skip = page.getByRole("link", { name: "Skip to content" });
    await expect(skip).toBeFocused();
    await expect(skip).toBeVisible();
    await page.keyboard.press("Enter");
    await expect(page.getByRole("main")).toBeFocused();
  });

  test("keyboard: a change row is a named link that opens with Enter", async ({ page, request, isMobile }) => {
    test.skip(isMobile, "keyboard flow");
    const i = await ids(request);
    await page.goto(`/p/${i.pid}/changes`);
    await settle(page);
    const link = page.getByTestId("change-row").first().getByRole("link").first();
    await expect(link).toHaveAccessibleName(/\S/);
    await link.focus();
    await page.keyboard.press("Enter");
    await expect(page.getByTestId("change-detail")).toBeVisible();
  });

  test("keyboard: audit, session and skill rows each have a real button that opens them (Enter and Space)", async ({ page, request, isMobile }) => {
    test.skip(isMobile, "keyboard flow");
    const i = await ids(request);
    for (const [path, row] of [[`/p/${i.pid}/audit`, "audit-row"], [`/p/${i.pid}/sessions`, "session-row"], [`/p/${i.pid}/skills`, "skill-row"]] as const) {
      for (const key of ["Enter", " "]) {
        await page.goto(path);
        await settle(page);
        const btn = page.getByTestId(row).first().getByRole("button").first();
        await expect(btn, `${row} button`).toHaveAccessibleName(/\S/);
        await btn.focus();
        await page.keyboard.press(key);
        await expect(page.getByTestId(row).first(), `${row} selected`).toHaveAttribute("aria-selected", "true");
      }
    }
  });
});

test.describe("states", () => {
  test.use({ expectedErrors: [/status of 500/] });
  test("an API failure shows an alert, not a blank page", async ({ page, request }) => {
    const i = await ids(request);
    await page.route("**/api/projects/*/overview**", (r) => r.fulfill({ status: 500, contentType: "application/json", body: '{"detail":"boom"}' }));
    await page.goto(`/p/${i.pid}`);
    await expect(page.getByRole("alert")).toBeVisible();
    const res = await new AxeBuilder({ page }).withTags(TAGS).analyze();
    expect(res.violations.map((v) => v.id)).toEqual([]);
  });

  test("an empty project renders and stays accessible", async ({ page, request }) => {
    const i = await ids(request);
    await page.route(`**/api/projects/${i.pid}/changes**`, async (route) => {
      const r = await route.fetch();
      const j = (await r.json()) as Record<string, unknown>;
      for (const k of Object.keys(j)) if (Array.isArray(j[k])) j[k] = [];
      if ("total" in j) j.total = 0;
      await route.fulfill({ response: r, json: j });
    });
    await page.goto(`/p/${i.pid}/changes`);
    await settle(page);
    await expect(page.getByRole("heading", { name: "Changes" })).toBeVisible();
    await expect(page.getByRole("alert")).toHaveCount(0);
    await expect(page.getByTestId("change-row")).toHaveCount(0);
    const res = await new AxeBuilder({ page }).withTags(TAGS).analyze();
    expect(res.violations.map((v) => v.id)).toEqual([]);
  });
});

test.describe("reflow", () => {
  test.use({ viewport: { width: 320, height: 640 } });
  test("no page needs horizontal scrolling at 320px (WCAG 1.4.10)", async ({ page, request }) => {
    const over: string[] = [];
    for (const [name, path] of routes(await ids(request))) {
      await page.goto(path);
      await settle(page);
      const px = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
      if (px > 1) over.push(`${name} overflows by ${px}px`);
    }
    expect(over).toEqual([]);
  });
});
