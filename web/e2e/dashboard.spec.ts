import { expect, test } from "./fixtures";

test.describe("P2-4 overview, changes, change detail", () => {
  test("switch project, filter, open a change, go back", async ({ page }) => {
    await page.goto("/projects");
    await expect(page.getByTestId("project-card")).toHaveCount(3);
    await page.getByTestId("project-card").filter({ hasText: "payments-api" }).click();
    await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();
    await expect(page.getByTestId("tile-Requests")).toContainText(/\d/);
    await expect(page.getByTestId("background-spend")).toContainText(/plus \$[\d.]+ in \d+ background turns?/);

    await page.getByLabel("Project", { exact: true }).selectOption({ label: "patient360-web" });
    await expect(page).toHaveURL(/\/p\/demo-patient/);
    await page.getByRole("group", { name: "Date range" }).getByRole("button", { name: "28d" }).click();
    await expect(page).toHaveURL(/range=28/);

    await page.getByRole("button", { name: "All changes →" }).click();
    await expect(page.getByRole("heading", { name: "Changes" })).toBeVisible();
    await expect(page.getByTestId("changes-count")).toContainText("changes");
    const total = Number((await page.getByTestId("changes-count").textContent())!.split(" ")[0]);
    await expect(page.getByTestId("change-row")).toHaveCount(Math.min(total, 50)); // one page
    const before = total;
    await page.getByRole("button", { name: "PII exposed" }).click();
    await expect(page).toHaveURL(/pii=true/);
    await expect.poll(() => page.getByTestId("change-row").count()).toBeLessThan(before);
    const filtered = page.getByTestId("change-row");
    await expect(filtered.first().getByText(/PII ×/)).toBeVisible();

    await filtered.first().click();
    await expect(page.getByTestId("change-detail")).toBeVisible();
    await expect(page.getByTestId("pii-panel")).toBeVisible();
    await expect(page.getByTestId("change-files")).toBeVisible();
    await page.getByTestId("back").click();
    await expect(page).toHaveURL(/pii=true/);
    await expect(page.getByRole("button", { name: "PII exposed" })).toHaveAttribute("aria-pressed", "true");
  });

  test("a folder on the Overview opens the requests that touched it", async ({ page }) => {
    await page.goto("/p/demo-payments?range=28");
    const card = page.locator(".panel", { has: page.getByRole("heading", { name: "Where the work happened" }) });
    const link = card.getByRole("link").first();
    const name = (await link.textContent())!;
    await link.click();
    await expect(page).toHaveURL(new RegExp(`q=${encodeURIComponent(name).replace(/[.]/g, "\\.")}`));
    await expect(page.getByTestId("change-row").first()).toBeVisible();
  });

  test("the dashboard answers its four questions: changed, cost, rules and skills, PII", async ({ page }) => {
    await page.goto("/p/demo-payments?range=28");
    for (const name of ["Activity", "Spend", "Where the work happened", "What happened to it", "When the work happens", "Required-skill rules", "Skills", "PII exposure by type"])
      await expect(page.getByRole("heading", { name })).toBeVisible();
    await expect(page.getByTestId("tile-Cost").getByTestId("delta")).toBeVisible(); // against the period before
    await expect(page.getByTestId("spend-legend")).toContainText("$");
    await expect(page.getByTestId("rule-list")).toContainText("of");
    await page.locator(".heat-cell").nth(30).hover();
    await expect(page.getByTestId("rhythm-caption")).toContainText(/\d{2}:00 · \d+ requests?/);
  });

  test("sort by cost toggles direction", async ({ page }) => {
    await page.goto("/p/demo-payments/changes?range=28&view=list"); // sorting is in the flat list view
    await page.getByRole("button", { name: /Cost/ }).click();
    await expect(page).toHaveURL(/sort=cost&dir=desc/);
    await page.getByRole("button", { name: /Cost/ }).click();
    await expect(page).toHaveURL(/dir=asc/);
  });

  test("never a bare clean badge", async ({ page }) => {
    for (const path of ["/p/demo-pipes?range=28", "/p/demo-pipes/changes?range=28"]) {
      await page.goto(path);
      await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
      await expect(page.getByText(/^\s*clean\s*$/i)).toHaveCount(0);
    }
  });

  test("deny-list snippet for a top PII source", async ({ page }) => {
    await page.goto("/p/demo-patient?range=28");
    await page.getByTestId("pii-sources").getByRole("button", { name: /deny rule/ }).first().click();
    await expect(page.getByTestId("deny-snippet")).toContainText('"Read(./data/patients.csv)"');
  });
});

test.describe("P2-5 skills", () => {
  test("open a skill, see its recent changes", async ({ page }) => {
    await page.goto("/p/demo-payments/skills?range=28");
    await page.getByTestId("skill-row").filter({ hasText: "security-review" }).click();
    const panel = page.getByTestId("skill-panel");
    await expect(panel).toBeVisible();
    await expect(panel.getByText("approved").first()).toBeVisible();
    await expect(panel.getByTestId("change-row").first()).toBeVisible();
  });

  test("required skills tab shows compliance", async ({ page }) => {
    await page.goto("/p/demo-payments/skills?tab=required");
    await expect(page.getByTestId("policies")).toContainText("Compliance");
    await expect(page.getByTestId("policies")).toContainText("security-review");
  });
});

test.describe("P2-6 projects and settings", () => {
  test("settings render from real data", async ({ page }) => {
    await page.goto("/settings");
    const s = page.getByTestId("settings");
    await expect(s).toContainText("report");
    await expect(s).toContainText("unverified");
    await expect(s).toContainText("claude-sonnet-5-5");
  });
});

test.describe("P2-7 audit", () => {
  test("filter the timeline, see the verified badge, export", async ({ page }) => {
    await page.goto("/p/demo-payments/audit");
    await expect(page.getByTestId("chain-seal")).toContainText("Chain verified");
    await expect(page.getByTestId("anchor-note")).toContainText("Not anchored");
    await page.getByLabel("Event type").selectOption("skill.invoked");
    await expect(page).toHaveURL(/type=skill\.invoked/);
    const rows = page.getByTestId("audit-row");
    await expect(rows.first()).toContainText("skill.invoked");
    await rows.first().click();
    await expect(page.getByTestId("audit-detail")).toContainText("Prev hash");
    await page.getByRole("button", { name: "Close" }).click();
    await page.getByTestId("export").click();
    await expect(page.getByTestId("export-result")).toContainText("(verified)");
  });
});

test("dark theme toggle wins over the OS setting", async ({ page }) => {
  await page.emulateMedia({ colorScheme: "light" });
  await page.goto("/projects");
  await page.getByRole("group", { name: "Theme" }).getByRole("button", { name: "dark" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  const bg = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);
  expect(bg).toBe("oklch(0.165 0.035 258)");
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
});

test.describe("P4-2 / P4-5 skill audit", () => {
  test("approve a changed skill version; UI reflects it", async ({ page }, info) => {
    const pid = info.project.name === "phone" ? "demo-pipes" : "demo-payments";
    await page.goto(`/p/${pid}/skills?skill=tdd`);
    const panel = page.getByTestId("skill-panel");
    await expect(panel.getByText("changed").first()).toBeVisible();
    await panel.getByRole("button", { name: /Approve/ }).click();
    await expect(panel.getByRole("button", { name: "Version approved" })).toBeDisabled();
    await expect(page.getByTestId("skill-row").filter({ hasText: "tdd" }).getByText("approved")).toBeVisible();
    await page.goto(`/p/${pid}/audit?type=approval.skill`);
    await expect(page.getByTestId("audit-row").first()).toContainText("tdd");
  });

  test("required-skill rule links to missed changes", async ({ page }) => {
    await page.goto("/p/demo-payments/skills?tab=required");
    await page.getByTestId("policies").getByRole("link", { name: /missed/ }).first().click();
    await expect(page).toHaveURL(/policy_missed=true/);
    await expect(page.getByTestId("change-row").first().getByText("policy missed")).toBeVisible();
  });

  test("changes skill select filters", async ({ page }) => {
    await page.goto("/p/demo-payments/changes?range=28");
    await page.getByLabel("Skill").selectOption("security-review");
    await expect(page).toHaveURL(/skill=security-review/);
    await expect(page.getByTestId("change-row").first()).toContainText("security-review");
  });
});

test.describe("P4B-8 PII in the dashboard", () => {
  test("open a change with findings, mark one as test data", async ({ page }, info) => {
    const pid = info.project.name === "phone" ? "demo-pipes" : "demo-patient";
    await page.goto(`/p/${pid}/changes?range=28&pii=true`);
    await page.getByTestId("change-row").first().click();
    const panel = page.getByTestId("pii-panel");
    await expect(panel).toBeVisible();
    const openBefore = await panel.getByRole("button", { name: "Mark as test data" }).count();
    await panel.getByRole("button", { name: "Mark as test data" }).first().click();
    await expect(panel.getByRole("button", { name: "Mark as test data" })).toHaveCount(openBefore - 1);
    await expect(panel.getByText("test data").first()).toBeVisible();
    await page.goto(`/p/${pid}/audit?type=approval.pii_test_data`);
    await expect(page.getByTestId("audit-row").first()).toContainText("approval.pii_test_data");
  });

  test("overview shows PII tile and top sources", async ({ page }) => {
    await page.goto("/p/demo-patient?range=28");
    await expect(page.getByTestId("tile-PII exposure")).toBeVisible();
    await expect(page.getByTestId("pii-sources")).toContainText("Read data/patients.csv");
  });

  test("settings: change PII mode and it persists", async ({ page }, info) => {
    test.skip(info.project.name === "phone", "global setting: run once");
    await page.goto("/settings");
    await page.getByLabel("PII mode").selectOption("warn");
    await page.getByTestId("pii-settings").getByRole("button", { name: "Save" }).click();
    await expect(page.getByText("Saved.")).toBeVisible();
    await page.reload();
    await expect(page.getByLabel("PII mode")).toHaveValue("warn");
    await page.getByLabel("PII mode").selectOption("report");
    await page.getByTestId("pii-settings").getByRole("button", { name: "Save" }).click();
    await expect(page.getByText("Saved.")).toBeVisible();
  });
});

test.describe("timeline", () => {
  test("shows file-changing requests as points with a one-line headline, by day", async ({ page }) => {
    await page.goto("/p/demo-payments/timeline");
    await expect(page.getByTestId("timeline-count")).toContainText("changes");
    const day = page.getByTestId("timeline-day").first();
    await expect(day).toContainText(/commits?/);
    const entry = page.getByTestId("timeline-entry").first();
    await expect(entry).toContainText("u_demo");
    await expect(entry).toContainText(/\d+ files?/);
    expect((await entry.getByRole("link").textContent())?.length).toBeGreaterThan(14);
    await expect(page.getByRole("table")).toHaveCount(0); // a timeline, not a second Changes table
  });

  test("filters by user, can include turns without file changes, and opens a change", async ({ page }) => {
    await page.goto("/p/demo-payments/timeline");
    await page.getByLabel("User").selectOption("u_demo");
    await expect(page).toHaveURL(/actor=u_demo/);
    const before = await page.getByTestId("timeline-entry").count();
    await page.getByRole("button", { name: /Include turns without file changes/ }).click();
    await expect(page).toHaveURL(/turns=all/);
    await expect.poll(() => page.getByTestId("timeline-entry").count()).toBeGreaterThanOrEqual(before);
    await page.getByTestId("timeline-entry").first().getByRole("link").click();
    await expect(page.getByTestId("change-detail")).toBeVisible();
  });
});

test.describe("sessions", () => {
  test("lists sessions with status and opens a session's activity", async ({ page }) => {
    await page.goto("/p/demo-payments/sessions");
    await expect(page.getByTestId("sessions-count")).toContainText("sessions");
    const row = page.getByTestId("session-row").first();
    await expect(row).toHaveAttribute("data-status", /active|ended|incomplete/);
    await row.click();
    const drawer = page.getByTestId("session-activity");
    await expect(drawer.getByTestId("activity-list")).toContainText("session.start");
    await drawer.getByRole("button", { name: "Close" }).click();
    await expect(drawer).toHaveCount(0);
  });

  test("defaults to your sessions; background ones are one click away and labelled", async ({ page }) => {
    await page.goto("/p/demo-payments/sessions");
    const kind = page.getByTestId("session-kind");
    await expect(kind.getByRole("button", { name: /Yours/ })).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByTestId("session-row").filter({ hasText: "background" })).toHaveCount(0);
    await kind.getByRole("button", { name: /Background/ }).click();
    await expect(page).toHaveURL(/kind=background/);
    const rows = page.getByTestId("session-row");
    await expect(rows.first()).toContainText("background");
    expect(await rows.filter({ hasNotText: "background" }).count()).toBe(0);
  });
});

test.describe("changes are your requests", () => {
  test("defaults to Yours; background turns are separate and tagged", async ({ page }) => {
    await page.goto("/p/demo-payments/changes?range=28&view=list");
    const kind = page.getByTestId("change-kind");
    await expect(kind.getByRole("button", { name: /Yours/ })).toHaveAttribute("aria-pressed", "true");
    await expect(page.getByTestId("change-row").first()).toBeVisible();
    await expect(page.getByTestId("change-row").filter({ hasText: "background" })).toHaveCount(0);
    await kind.getByRole("button", { name: /Background/ }).click();
    await expect(page).toHaveURL(/kind=background/);
    await expect(page.getByTestId("change-row").first()).toContainText("background");
  });
});

test.describe("changes grouped by session, with paging", () => {
  test("default view groups by session; list view pages", async ({ page }) => {
    await page.goto("/p/demo-payments/changes?range=28");
    const groups = page.getByTestId("session-group");
    await expect(groups.first()).toContainText("Session");
    expect(await groups.count()).toBeGreaterThan(1);
    await page.getByRole("button", { name: "All changes" }).click();
    const pager = page.getByTestId("pager");
    await expect(pager).toContainText("1–50 of");
    await pager.getByRole("button", { name: "Next →" }).click();
    await expect(pager).toContainText("page 2 of");
    await expect(page).toHaveURL(/page=2/);
  });

  test("a session's changes are one click from its row", async ({ page }) => {
    await page.goto("/p/demo-payments/sessions");
    await page.getByTestId("session-row").first().click();
    await page.getByTestId("session-changes").click();
    await expect(page).toHaveURL(/session=/);
    await expect(page.getByTestId("session-group")).toHaveCount(1);
    await expect(page.getByRole("button", { name: /Clear session filter/ })).toBeVisible();
  });
});


test.describe("the mark watches the pointer", () => {
  const gaze = (page: import("@playwright/test").Page) =>
    page.locator(".eyes:visible").first().locator(".eyes-look").first().getAttribute("transform");
  const dx = async (page: import("@playwright/test").Page) => Number(/translate\((-?[\d.]+)/.exec((await gaze(page)) ?? "")?.[1] ?? "0");

  for (const path of ["/projects", "/settings"]) {
    test(`eyes on ${path} follow the mouse left and right`, async ({ page, isMobile }) => {
      test.skip(isMobile, "no pointer on a phone");
      await page.goto(path);
      await expect(page.locator(".eyes:visible").first()).toBeVisible();
      await page.mouse.move(1200, 400);
      await expect.poll(() => dx(page), { timeout: 4000 }).toBeGreaterThan(1.5);
      await page.mouse.move(2, 400);
      await expect.poll(() => dx(page), { timeout: 4000 }).toBeLessThan(0.5);
    });
  }

  test("eyes are present on a project page too", async ({ page }) => {
    await page.goto("/projects");
    await page.getByTestId("project-card").first().click();
    await expect(page.locator(".eyes:visible").first()).toBeVisible();
  });
});
