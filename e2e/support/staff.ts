import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { STAFF_PATH } from "./env";

/*
 * Staff accounts made fresh for each run by global setup, one per test
 * that needs one. A sign-in starts a 30-second cooldown on its phone
 * number, so tests running in parallel (or a rerun straight after the
 * last) can't share an account; the seeded staff numbers are each kept
 * for one test (env.ts).
 */
export const STAFF_ROLES = {
  consoleAdmin: "municipal_admin",
  ac05Operator: "operator",
  ac06Operator: "operator",
  ac07Operator: "operator",
  ac08Operator: "operator",
  loadOperator: "operator",
  aiDownOperator: "operator",
} as const;

export type StaffKey = keyof typeof STAFF_ROLES;

export type GeneratedStaff = {
  phones: Record<StaffKey, string>;
  /** The active embedding model, e.g. "clip-vit-b32@onnx-1" or a fake one. */
  embeddingModel: string | null;
};

let cached: GeneratedStaff | undefined;

function generated(): GeneratedStaff {
  cached ??= JSON.parse(
    readFileSync(fileURLToPath(STAFF_PATH), "utf8"),
  ) as GeneratedStaff;
  return cached;
}

export function staffPhone(key: StaffKey): string {
  return generated().phones[key];
}

/**
 * Whether the stack runs the real vision model. The fake one
 * (infra/docker-compose.fake-ai.yml) can't recognise a pothole or tell two
 * different photos of one apart, so the tests about that skip under it.
 */
export function realModel(): boolean {
  const model = generated().embeddingModel;
  return Boolean(model) && !model?.startsWith("fake");
}
