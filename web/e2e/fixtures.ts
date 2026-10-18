import { expect, test as base } from "@playwright/test";

/** Every page fails on a CSP violation or console error: CSP can silently break fonts, charts and workers. */
export const test = base.extend<{ guard: void }>({
  guard: [
    async ({ page }, use) => {
      const problems: string[] = [];
      await page.addInitScript(() => {
        document.addEventListener("securitypolicyviolation", (e) => {
          (window as unknown as { __csp: string[] }).__csp = [...((window as unknown as { __csp?: string[] }).__csp ?? []), `${e.violatedDirective} ${e.blockedURI}`];
        });
      });
      page.on("console", (m) => { if (m.type() === "error") problems.push(m.text()); });
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
