import { beforeEach, describe, expect, it } from "vitest";
import {
  clearDraft,
  DRAFT_STORAGE_KEY,
  hasProgress,
  loadDraft,
  newDraft,
  saveDraft,
} from "./draft";

beforeEach(() => sessionStorage.clear());

describe("report draft", () => {
  it("keeps the same idempotency key every time the draft is loaded", () => {
    const first = loadDraft();
    saveDraft({ ...first, description: "Broken light" });

    const reloaded = loadDraft();
    expect(reloaded.idempotencyKey).toBe(first.idempotencyKey);
    expect(reloaded.description).toBe("Broken light");
    expect(loadDraft().idempotencyKey).toBe(first.idempotencyKey);
  });

  it("gives a new draft a new key", () => {
    const first = loadDraft();
    saveDraft(first);
    clearDraft();
    const second = loadDraft();
    expect(second.idempotencyKey).not.toBe(first.idempotencyKey);
    expect(newDraft().idempotencyKey).not.toBe(newDraft().idempotencyKey);
  });

  it("generates keys the API accepts (printable ASCII, ≤ 255)", () => {
    const { idempotencyKey } = newDraft();
    expect(idempotencyKey).toMatch(/^[\x21-\x7e]{1,255}$/);
  });

  it("starts fresh when the stored draft is corrupt or from another version", () => {
    sessionStorage.setItem(DRAFT_STORAGE_KEY, "{not json");
    expect(loadDraft().step).toBe(1);
    sessionStorage.setItem(
      DRAFT_STORAGE_KEY,
      JSON.stringify({ version: 99, idempotencyKey: "x" }),
    );
    expect(loadDraft().idempotencyKey).not.toBe("x");
  });

  it("knows when there is something worth resuming", () => {
    expect(hasProgress(newDraft())).toBe(false);
    expect(hasProgress({ ...newDraft(), categoryId: "c" })).toBe(true);
  });
});
