"use client";

import { useCallback, useSyncExternalStore } from "react";
import { createReport, session, TENANT } from "@/lib/api";
import type { CreateReportBody } from "@/lib/api/endpoints/reports";
import { type PreparedImage, uploadImage } from "@/lib/upload/upload";
import {
  type FlushResult,
  flushQueue,
  indexedDbStore,
  newEntry,
  type QueueEntry,
  type QueueStore,
  queueAvailable,
} from "./report-queue";

/*
 * The app-wide report queue: one store, one flush at a time, and a count
 * the UI can subscribe to.
 */

const SYNC_TAG = "report-queue";

let store: QueueStore | null = null;
let entries: QueueEntry[] = [];
let flushing: Promise<FlushResult | null> | null = null;
const listeners = new Set<() => void>();
const sentListeners = new Set<(result: FlushResult) => void>();

function getStore(): QueueStore | null {
  if (!queueAvailable()) return null;
  store ??= indexedDbStore();
  return store;
}

async function refresh() {
  const s = getStore();
  entries = s ? (await s.all()).filter((e) => e.tenant === TENANT) : [];
  for (const listener of listeners) listener();
}

export async function enqueueReport(
  idempotencyKey: string,
  body: CreateReportBody,
  pending: PreparedImage[] = [],
): Promise<boolean> {
  const s = getStore();
  if (!s) return false;
  try {
    await s.put(newEntry(idempotencyKey, TENANT, body, pending));
  } catch {
    return false; // storage full or blocked (private mode): not queued
  }
  await refresh();
  // Ask the browser to wake the service worker when the network returns.
  try {
    const registration = await navigator.serviceWorker?.ready;
    const sync = (
      registration as
        | (ServiceWorkerRegistration & {
            sync?: { register(tag: string): Promise<void> };
          })
        | undefined
    )?.sync;
    await sync?.register(SYNC_TAG);
  } catch {
    // No Background Sync (Firefox, Safari): the `online` event covers it.
  }
  return true;
}

/** Send what's queued, if signed in and online. Concurrent calls share one run. */
export function flushReportQueue(): Promise<FlushResult | null> {
  const s = getStore();
  if (!s || session.getSnapshot().status !== "authenticated") {
    return Promise.resolve(null);
  }
  if (typeof navigator !== "undefined" && navigator.onLine === false) {
    return Promise.resolve(null);
  }
  flushing ??= flushQueue(
    s,
    {
      upload: (image) => uploadImage(image),
      create: (body, key) => createReport(body, { idempotencyKey: key }),
    },
    TENANT,
  )
    .then(async (result) => {
      await refresh();
      if (result.sent.length || result.failed.length) {
        for (const listener of sentListeners) listener(result);
      }
      return result;
    })
    .catch(() => null)
    .finally(() => {
      flushing = null;
    });
  return flushing;
}

export async function discardQueued(id: string) {
  await getStore()?.remove(id);
  await refresh();
}

export function onQueueFlushed(listener: (result: FlushResult) => void) {
  sentListeners.add(listener);
  return () => {
    sentListeners.delete(listener);
  };
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  if (listeners.size === 1) void refresh();
  return () => {
    listeners.delete(listener);
  };
}

const EMPTY: QueueEntry[] = [];

export function useReportQueue() {
  const items = useSyncExternalStore(
    subscribe,
    () => entries,
    () => EMPTY,
  );
  const flush = useCallback(() => flushReportQueue(), []);
  return { items, flush };
}
