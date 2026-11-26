import { describe, expect, it, vi } from "vitest";
import type { CreateReportBody } from "@/lib/api/endpoints/reports";
import {
  flushQueue,
  isTransient,
  memoryStore,
  newEntry,
  type Sender,
} from "./report-queue";

const body: CreateReportBody = {
  category_id: "cat-1",
  description: "Pothole outside the school",
  location: { lat: 28.6, lng: 77.2, accuracy_m: 8, source: "gps" },
  details: {},
  media_ids: ["m-1"],
  client_created_at: "2026-11-26T10:00:00.000Z",
} as CreateReportBody;

const image = () => ({
  blob: new Blob(["jpeg"], { type: "image/jpeg" }),
  contentType: "image/jpeg" as const,
});

const offline = Object.assign(new Error("offline"), {
  status: 0,
  code: "network_error",
});

function sender(overrides: Partial<Sender> = {}): Sender {
  let n = 0;
  return {
    upload: vi.fn(async () => ({ id: `up-${++n}` })),
    create: vi.fn(async () => ({ id: "report" })),
    ...overrides,
  };
}

describe("isTransient", () => {
  it("retries network, rate-limit and server errors only", () => {
    expect(isTransient({ status: 0 })).toBe(true);
    expect(isTransient({ status: 429 })).toBe(true);
    expect(isTransient({ status: 503 })).toBe(true);
    expect(isTransient({ status: 422 })).toBe(false);
    expect(isTransient({ status: 401 })).toBe(false);
    expect(isTransient(new Error("boom"))).toBe(true);
  });
});

describe("flushQueue", () => {
  it("sends the same body and key the citizen submitted", async () => {
    const store = memoryStore([newEntry("key-1", "demo", body)]);
    const send = sender();
    const result = await flushQueue(store, send, "demo");
    expect(result).toEqual({ sent: ["key-1"], failed: [], offline: false });
    expect(send.create).toHaveBeenCalledWith(body, "key-1");
    expect(store.entries.size).toBe(0);
  });

  it("uploads queued photos once, even across failed attempts", async () => {
    const store = memoryStore([
      newEntry("key-1", "demo", body, [image(), image()]),
    ]);
    const create = vi
      .fn()
      .mockRejectedValueOnce(offline)
      .mockResolvedValueOnce({ id: "r" });
    const send = sender({ create });

    const first = await flushQueue(store, send, "demo");
    expect(first.offline).toBe(true);
    const saved = store.entries.get("key-1");
    expect(saved?.photos.map((p) => p.mediaId)).toEqual(["up-1", "up-2"]);
    expect(saved?.photos.every((p) => p.image === null)).toBe(true);

    await flushQueue(store, send, "demo");
    expect(send.upload).toHaveBeenCalledTimes(2);
    expect(create).toHaveBeenLastCalledWith(
      { ...body, media_ids: ["m-1", "up-1", "up-2"] },
      "key-1",
    );
    expect(store.entries.size).toBe(0);
  });

  it("keeps a photo uploaded before the connection dropped", async () => {
    const upload = vi
      .fn()
      .mockResolvedValueOnce({ id: "up-1" })
      .mockRejectedValueOnce(offline);
    const store = memoryStore([
      newEntry("key-1", "demo", body, [image(), image()]),
    ]);
    const result = await flushQueue(store, sender({ upload }), "demo");
    expect(result.offline).toBe(true);
    const photos = store.entries.get("key-1")?.photos ?? [];
    expect(photos[0].mediaId).toBe("up-1");
    expect(photos[1].mediaId).toBeNull();
    expect(photos[1].image).not.toBeNull();
  });

  it("marks a refused report failed and moves on", async () => {
    const refused = Object.assign(new Error("bad"), {
      status: 422,
      code: "validation_failed",
    });
    const create = vi
      .fn()
      .mockRejectedValueOnce(refused)
      .mockResolvedValueOnce({});
    const store = memoryStore([
      newEntry("a", "demo", body, [], new Date("2026-11-26T10:00:00Z")),
      newEntry("b", "demo", body, [], new Date("2026-11-26T11:00:00Z")),
    ]);
    const result = await flushQueue(store, sender({ create }), "demo");
    expect(result).toEqual({ sent: ["b"], failed: ["a"], offline: false });
    expect(store.entries.get("a")).toMatchObject({
      status: "failed",
      error: "validation_failed",
      attempts: 1,
    });
  });

  it("stops at the first network failure and leaves the rest queued", async () => {
    const create = vi.fn().mockRejectedValue(offline);
    const store = memoryStore([
      newEntry("a", "demo", body, [], new Date("2026-11-26T10:00:00Z")),
      newEntry("b", "demo", body, [], new Date("2026-11-26T11:00:00Z")),
    ]);
    const result = await flushQueue(store, sender({ create }), "demo");
    expect(result.offline).toBe(true);
    expect(create).toHaveBeenCalledTimes(1);
    expect(store.entries.get("b")?.attempts).toBe(0);
  });

  it("only sends the current tenant's reports", async () => {
    const store = memoryStore([newEntry("a", "other-city", body)]);
    const send = sender();
    expect((await flushQueue(store, send, "demo")).sent).toEqual([]);
    expect(store.entries.size).toBe(1);
  });
});
