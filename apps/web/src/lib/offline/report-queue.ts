import type { CreateReportBody } from "@/lib/api/endpoints/reports";
import type { PreparedImage } from "@/lib/upload/upload";

/*
 * Reports waiting for the network (P6-01, FR-014).
 *
 * When a citizen presses Send without a connection, the finished report is
 * queued in IndexedDB instead of failing. The queue is flushed when the
 * browser is back online (the `online` event, or a Background Sync message
 * from the service worker) and whenever the app starts.
 *
 * Retries must be byte-for-byte the same request, or the API answers
 * `idempotency_key_reused` instead of replaying the first result. So an
 * entry keeps the draft's Idempotency-Key and its `client_created_at`, and
 * photos still to be uploaded are uploaded once: each media id is saved to
 * the entry as soon as its upload completes, and the body is only built
 * when every photo has one.
 *
 * Entries live in IndexedDB, not sessionStorage, so they survive closing
 * the tab. They hold the report text, the location and photo bytes; no
 * credentials. Sending needs a signed-in session, which the page has.
 */

export type QueuedPhoto = {
  id: string;
  /** Set once uploaded; then `image` is dropped. */
  mediaId: string | null;
  image: PreparedImage | null;
};

export type QueueEntryStatus = "queued" | "failed";

export type QueueEntry = {
  /** The draft's Idempotency-Key, which also identifies the entry. */
  id: string;
  tenant: string;
  queuedAt: string;
  /** Everything but `media_ids`, which come from `photos`. */
  body: Omit<CreateReportBody, "media_ids">;
  /** Media ids of photos uploaded before the report was queued. */
  mediaIds: string[];
  photos: QueuedPhoto[];
  status: QueueEntryStatus;
  attempts: number;
  /** The API's error code when the server refused the report. */
  error: string | null;
};

/** Where entries are kept: IndexedDB in the browser, memory in tests. */
export interface QueueStore {
  all(): Promise<QueueEntry[]>;
  put(entry: QueueEntry): Promise<void>;
  remove(id: string): Promise<void>;
}

export type Sender = {
  upload(image: PreparedImage): Promise<{ id: string }>;
  create(body: CreateReportBody, idempotencyKey: string): Promise<unknown>;
};

export type FlushResult = {
  sent: string[];
  failed: string[];
  /** True when the flush stopped because the network went away again. */
  offline: boolean;
};

type ErrorLike = { status?: unknown; code?: unknown };

/** Errors worth retrying later: no network, rate limits, server trouble. */
export function isTransient(error: unknown): boolean {
  if (!error || typeof error !== "object") return true;
  const { status } = error as ErrorLike;
  if (typeof status !== "number") return true;
  return status === 0 || status === 408 || status === 429 || status >= 500;
}

function errorCode(error: unknown): string {
  const code = (error as ErrorLike | null)?.code;
  return typeof code === "string" ? code : "unknown_error";
}

export function newEntry(
  idempotencyKey: string,
  tenant: string,
  body: CreateReportBody,
  pending: PreparedImage[] = [],
  now: Date = new Date(),
): QueueEntry {
  const { media_ids, ...rest } = body;
  return {
    id: idempotencyKey,
    tenant,
    queuedAt: now.toISOString(),
    body: rest,
    mediaIds: [...media_ids],
    photos: pending.map((image, index) => ({
      id: `${idempotencyKey}:${index}`,
      mediaId: null,
      image,
    })),
    status: "queued",
    attempts: 0,
    error: null,
  };
}

/**
 * Send every queued entry for `tenant`, oldest first. Stops at the first
 * network failure (the rest would fail the same way); a report the server
 * refuses is marked `failed` and kept for the citizen to see.
 */
export async function flushQueue(
  store: QueueStore,
  sender: Sender,
  tenant: string,
): Promise<FlushResult> {
  const result: FlushResult = { sent: [], failed: [], offline: false };
  const entries = (await store.all())
    .filter((entry) => entry.tenant === tenant && entry.status === "queued")
    .sort((a, b) => a.queuedAt.localeCompare(b.queuedAt));

  for (const original of entries) {
    const entry: QueueEntry = {
      ...original,
      photos: original.photos.map((p) => ({ ...p })),
      attempts: original.attempts + 1,
    };
    try {
      for (const photo of entry.photos) {
        if (photo.mediaId || !photo.image) continue;
        const asset = await sender.upload(photo.image);
        photo.mediaId = asset.id;
        photo.image = null;
        // Saved at once, so a later failure never uploads it twice.
        await store.put(entry);
      }
      const mediaIds = [
        ...entry.mediaIds,
        ...entry.photos.flatMap((p) => (p.mediaId ? [p.mediaId] : [])),
      ];
      await sender.create({ ...entry.body, media_ids: mediaIds }, entry.id);
      await store.remove(entry.id);
      result.sent.push(entry.id);
    } catch (error) {
      if (isTransient(error)) {
        await store.put(entry);
        result.offline = true;
        break;
      }
      await store.put({ ...entry, status: "failed", error: errorCode(error) });
      result.failed.push(entry.id);
    }
  }
  return result;
}

// ---- IndexedDB store ---------------------------------------------------

const DB_NAME = "civicpulse-offline";
const DB_VERSION = 1;
const STORE = "report-queue";

function request<T>(req: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

function openDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, DB_VERSION);
    req.onupgradeneeded = () => {
      if (!req.result.objectStoreNames.contains(STORE)) {
        req.result.createObjectStore(STORE, { keyPath: "id" });
      }
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

export function indexedDbStore(): QueueStore {
  let db: Promise<IDBDatabase> | null = null;
  const tx = async (mode: IDBTransactionMode) => {
    db ??= openDb();
    return (await db).transaction(STORE, mode).objectStore(STORE);
  };
  return {
    async all() {
      return request(
        (await tx("readonly")).getAll() as IDBRequest<QueueEntry[]>,
      );
    },
    async put(entry) {
      await request((await tx("readwrite")).put(entry));
    },
    async remove(id) {
      await request((await tx("readwrite")).delete(id));
    },
  };
}

export function memoryStore(initial: QueueEntry[] = []): QueueStore & {
  entries: Map<string, QueueEntry>;
} {
  const entries = new Map(initial.map((e) => [e.id, structuredClone(e)]));
  return {
    entries,
    async all() {
      return [...entries.values()].map((e) => structuredClone(e));
    },
    async put(entry) {
      entries.set(entry.id, structuredClone(entry));
    },
    async remove(id) {
      entries.delete(id);
    },
  };
}

export function queueAvailable(): boolean {
  return typeof indexedDB !== "undefined";
}
