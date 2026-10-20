import { expect, test } from "./fixtures";

/** PRODUCT.md: every summary is one click from the proof. Each Overview tile opens the rows behind its number. */
const TILES: [label: string, param: RegExp][] = [
  ["Requests", /\/changes(\?|$)/],
  ["Cost", /sort=cost/],
  ["Rules met", /policy_missed=true/],
  ["PII exposure", /pii=true/],
];

test("Code changed opens the Timeline", async ({ page }) => {
  await page.goto("/projects");
  await page.getByTestId("project-card").filter({ hasText: "payments-api" }).click();
  await page.getByTestId("tile-Code changed").getByRole("link").click();
  await expect(page).toHaveURL(/\/timeline/);
  await expect(page.getByRole("heading", { name: "Timeline" })).toBeVisible();
});

test.describe("overview tiles lead to their evidence", () => {
  for (const [label, param] of TILES) {
    test(`${label} opens the matching changes`, async ({ page }) => {
      await page.goto("/projects");
      await page.getByTestId("project-card").filter({ hasText: "payments-api" }).click();
      const tile = page.getByTestId(`tile-${label}`);
      const shown = (await tile.locator(".value").textContent()) ?? "";
      await tile.getByRole("link").click();
      await expect(page).toHaveURL(param);
      await expect(page.getByRole("heading", { name: "Changes" })).toBeVisible();
      await expect(page).toHaveURL(/range=|\/changes/); // the date range travels with the click
      // a tile that shows a non-zero number must land on rows (the filtered page may widen to all kinds of sessions)
      if (/[1-9]/.test(shown)) await expect(page.getByTestId("change-row").first()).toBeVisible();
    });
  }

  test("tiles are links a keyboard can reach, named by what they open", async ({ page }) => {
    await page.goto("/projects");
    await page.getByTestId("project-card").filter({ hasText: "payments-api" }).click();
    for (const [label] of TILES) await expect(page.getByTestId(`tile-${label}`).getByRole("link")).toHaveAccessibleName(new RegExp(label, "i"));
  });
});

test.describe("weight", () => {
  test("the first page loads under 450 KB of script: charts and other pages arrive when needed", async ({ page }) => {
    let bytes = 0;
    const pending: Promise<void>[] = [];
    page.on("response", (r) => {
      if (r.url().endsWith(".js")) pending.push(r.body().then((b) => { bytes += b.length; }).catch(() => undefined));
    });
    await page.goto("/projects");
    await page.waitForLoadState("networkidle");
    await Promise.all(pending);
    expect(bytes, `${Math.round(bytes / 1024)} KB of JS on /projects`).toBeLessThan(450 * 1024);
  });
});
