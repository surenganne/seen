import { defineConfig, devices } from "@playwright/test";

// E2E runs against the real API on a seeded scratch SEEN_HOME (never ~/.seen).
// `npm run e2e` starts it via scripts/e2e-server.sh unless SEEN_E2E_URL points at a running stack (Docker).
const url = process.env.SEEN_E2E_URL ?? "http://127.0.0.1:47832";

export default defineConfig({
  testDir: "e2e",
  timeout: 30_000,
  retries: 0,
  reporter: [["list"]],
  use: { baseURL: url, trace: "retain-on-failure" },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"] } },
    { name: "phone", use: { ...devices["Pixel 7"] } },
  ],
  webServer: process.env.SEEN_E2E_URL
    ? undefined
    : { command: "sh ../scripts/e2e-server.sh 47832", url: `${url}/api/projects`, reuseExistingServer: false, timeout: 60_000 },
});
