import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

/**
 * Live checks against a running API (the compose stack plus seed). Not
 * part of `pnpm test`: run `pnpm --filter @civicpulse/web test:live`.
 * They call the app's own endpoint functions, so every response goes
 * through the same schemas the UI relies on.
 */
export default defineConfig({
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  test: {
    environment: "node",
    include: ["src/test/live/**/*.live.ts"],
    testTimeout: 120_000,
    fileParallelism: false,
    env: {
      NEXT_PUBLIC_API_URL: process.env.LIVE_API_URL ?? "http://localhost:8000",
      NEXT_PUBLIC_TENANT: "demo-city",
    },
  },
});
