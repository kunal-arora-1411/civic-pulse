import { describe, expect, it } from "vitest";
import { pushState, pushSupported, urlBase64ToUint8Array } from "./push";

describe("push helpers", () => {
  it("decodes a base64url VAPID key to bytes", () => {
    expect(Array.from(urlBase64ToUint8Array("AQID_-8"))).toEqual([
      1, 2, 3, 255, 239,
    ]);
  });

  it("reports unsupported where there is no Push API", async () => {
    // jsdom has neither service workers nor PushManager.
    expect(pushSupported()).toBe(false);
    expect(await pushState()).toBe("unsupported");
  });
});
