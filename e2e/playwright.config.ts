import { defineConfig, devices } from "@playwright/test";
import { WEB_URL } from "./support/env";

const CI = Boolean(process.env.CI);

/*
 * End-to-end tests against the real stack: the API, worker, Postgres and
 * MinIO from infra/docker-compose.yml (started and seeded beforehand), and
 * the web app, which Playwright starts itself.
 *
 * The web app runs as a production build (`next build` + `next start`)
 * rather than `next dev`. Dev mode compiles each route on its first
 * request, which turns the first visit to every page into a multi-second
 * wait that varies from run to run, and it renders differently enough
 * (Strict Mode double effects, no prerendered shells) that a green run
 * says less about what users get. CI builds in its own step, so there the
 * server only has to start. Locally, a server already listening on :3000
 * (for example `pnpm dev`) is reused as is.
 */
export default defineConfig({
  testDir: "./tests",
  globalSetup: "./support/global-setup.ts",
  fullyParallel: true,
  forbidOnly: CI,
  retries: CI ? 1 : 0,
  workers: CI ? 2 : undefined,
  timeout: 60_000,
  expect: { timeout: 10_000 },
  reporter: CI
    ? [["github"], ["list"], ["html", { open: "never" }]]
    : [["list"], ["html", { open: "never" }]],
  use: {
    baseURL: WEB_URL,
    locale: "en-IN",
    timezoneId: "Asia/Kolkata",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  /*
   * Two scenarios can't share the stack with anything else, so they run
   * after the main project, one at a time: the burst of simultaneous
   * reports (load.spec.ts), whose timings would otherwise include other
   * tests' work, and AC-03 (ai-down.spec.ts), which stops the AI worker.
   */
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
      testIgnore: [/load\.spec\.ts/, /ai-down\.spec\.ts/],
    },
    {
      name: "load",
      use: { ...devices["Desktop Chrome"] },
      testMatch: /load\.spec\.ts/,
      dependencies: ["chromium"],
    },
    {
      name: "ai-down",
      use: { ...devices["Desktop Chrome"] },
      testMatch: /ai-down\.spec\.ts/,
      dependencies: ["load"],
    },
  ],
  webServer: {
    command: CI
      ? "pnpm --filter @civicpulse/web start"
      : "pnpm --filter @civicpulse/web build && pnpm --filter @civicpulse/web start",
    cwd: "..",
    url: WEB_URL,
    // `next start` serves on $PORT; match it to E2E_WEB_URL's port.
    env: { PORT: new URL(WEB_URL).port || "3000" },
    reuseExistingServer: !CI,
    timeout: 300_000,
    stdout: "ignore",
    stderr: "pipe",
  },
});
