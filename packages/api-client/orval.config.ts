import { defineConfig } from "orval";

/*
 * `pnpm gen:api` (from the repo root) regenerates src/generated from the
 * API's OpenAPI document. The output is committed; CI should run
 * `pnpm gen:api && git diff --exit-code` so a spec change without a
 * regenerated client fails the build. orval is pinned to an exact version
 * so the output only changes when the spec does.
 */

/**
 * Drop `format` from every schema before generating.
 *
 * orval turns `format: uuid | date-time | date | email` into `z.uuid()`,
 * `z.iso.datetime()` and so on. The web app has always validated those
 * fields as plain strings (ids in tests and fixtures aren't UUIDs, and a
 * timestamp's exact ISO flavour isn't something the UI should fail on), so
 * the generated schemas keep that behaviour. Types are unaffected: they are
 * strings either way.
 */
function stripFormats(node: unknown): unknown {
  if (Array.isArray(node)) return node.map(stripFormats);
  if (!node || typeof node !== "object") return node;
  const out: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(node)) {
    if (key === "format" && typeof value === "string") continue;
    out[key] = stripFormats(value);
  }
  return out;
}

export default defineConfig({
  civicpulse: {
    input: {
      target: "../../apps/api/openapi.json",
      override: {
        transformer: (spec) => stripFormats(spec) as typeof spec,
      },
    },
    output: {
      // Request functions, one per operation, all routed through the
      // mutator below. "axios-functions" only describes the shape of the
      // config object the mutator receives; nothing imports axios.
      client: "axios-functions",
      mode: "single",
      target: "./src/generated/endpoints.ts",
      // One zod schema per component; the TypeScript types are inferred
      // from them, so types and runtime validation can't drift apart.
      schemas: {
        path: "./src/generated/schemas.ts",
        type: "zod",
        mode: "single",
      },
      clean: true,
      urlEncodeParameters: true,
      override: {
        mutator: { path: "./src/mutator.ts", name: "customInstance" },
        zod: { version: 4, generateReusableSchemas: true },
      },
    },
  },
});
