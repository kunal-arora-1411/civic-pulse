import { describe, expect, it } from "vitest";
import {
  PROCESSING_MAX_POLLS,
  PROCESSING_POLL_MS,
  processingRefetchInterval,
} from "./processing";

describe("processingRefetchInterval", () => {
  it("polls while any photo is still processing", () => {
    expect(
      processingRefetchInterval(
        [{ status: "ready" }, { status: "processing" }],
        1,
      ),
    ).toBe(PROCESSING_POLL_MS);
  });

  it("stops once every photo is ready or failed, or there are none", () => {
    expect(
      processingRefetchInterval([{ status: "ready" }, { status: "failed" }], 1),
    ).toBe(false);
    expect(processingRefetchInterval([], 1)).toBe(false);
    expect(processingRefetchInterval(undefined, 0)).toBe(false);
  });

  it("gives up after a while so a stuck job doesn't poll forever", () => {
    expect(
      processingRefetchInterval(
        [{ status: "processing" }],
        PROCESSING_MAX_POLLS,
      ),
    ).toBe(false);
  });
});
