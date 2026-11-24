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
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
  webServer: {
    command: CI
      ? "pnpm --filter @civicpulse/web start"
      : "pnpm --filter @civicpulse/web build && pnpm --filter @civicpulse/web start",
    cwd: "..",
    url: WEB_URL,
    reuseExistingServer: !CI,
    timeout: 300_000,
    stdout: "ignore",
    stderr: "pipe",
  },
});
