import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { type BrowserContext, test as base, expect } from "@playwright/test";
import { Api, type Session } from "./api";
import { API_URL, PHOTO_PATH } from "./env";

/**
 * Give a browser context the session's refresh cookie, exactly as the API
 * sets it after sign-in. The web app keeps the access token in memory and
 * restores it from this cookie on load, so pages open signed in.
 *
 * The path must be the API's own (`/api/v1/auth`). Given only a URL,
 * Playwright derives the default path, `/api/v1`, so the rotated cookie
 * the API sets on the first refresh would sit next to this one instead of
 * replacing it. The next page load would then send both, the server would
 * read the stale token, and reuse detection would end the session.
 */
export async function giveSession(context: BrowserContext, session: Session) {
  const api = new URL(API_URL);
  await context.addCookies([
    {
      name: "cp_refresh",
      value: session.refreshToken,
      domain: api.hostname,
      path: "/api/v1/auth",
      secure: api.protocol === "https:",
      httpOnly: true,
      sameSite: "Strict",
    },
  ]);
}

type Fixtures = {
  api: Api;
  /** The generated JPEG (see global setup). */
  photo: Buffer;
  /**
   * Fails the test on uncaught page errors, console errors and API 5xx
   * responses, which a passing UI assertion could otherwise hide. Failed
   * resource loads are left out: a signed-out page's 401 from
   * /auth/refresh is expected, and tests assert on the requests they care
   * about.
   */
  pageHealth: undefined;
};

export const test = base.extend<Fixtures>({
  pageHealth: [
    async ({ page }, use, testInfo) => {
      const problems: string[] = [];
      page.on("pageerror", (error) => problems.push(`page error: ${error}`));
      page.on("console", (message) => {
        if (message.type() !== "error") return;
        if (message.text().startsWith("Failed to load resource")) return;
        problems.push(`console error: ${message.text()}`);
      });
      page.on("response", (response) => {
        if (response.url().startsWith(API_URL) && response.status() >= 500) {
          problems.push(`${response.status()} from ${response.url()}`);
        }
      });
      await use(undefined);
      if (testInfo.status === testInfo.expectedStatus) {
        expect(problems, "the page stayed healthy").toEqual([]);
      }
    },
    { auto: true },
  ],
  api: async ({ request }, use) => {
    await use(new Api(request));
  },
  // biome-ignore lint/correctness/noEmptyPattern: Playwright fixtures must destructure
  photo: async ({}, use) => {
    await use(await readFile(fileURLToPath(PHOTO_PATH)));
  },
});

export { expect };

/** A phone-sized Chromium context: about the width of most Android phones. */
export const PHONE = {
  viewport: { width: 390, height: 844 },
  deviceScaleFactor: 3,
  isMobile: true,
  hasTouch: true,
  userAgent:
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/156.0.0.0 Mobile Safari/537.36",
} as const;
