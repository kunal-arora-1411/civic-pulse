/*
 * CivicPulse service worker (P6-01). Hand-written, no build step: Next 16's
 * PWA guide registers a plain file, and served from /public it controls the
 * whole origin (scope "/") without a Service-Worker-Allowed header.
 *
 * What it does:
 * - Precaches a small offline shell (offline.html, its script, icons).
 * - Page navigations: network first, then the cached copy of that page,
 *   then the offline shell. Successful navigations are cached, so pages a
 *   citizen has visited (the report form included) open offline.
 * - Build assets under /_next/static are content-hashed: cache first.
 * - Never touches the API (another origin), uploads, or non-GET requests.
 *   Queued reports live in IndexedDB and are sent by the page itself,
 *   which holds the access token; see src/lib/offline/report-queue.ts.
 * - Background Sync: when the browser says the network is back, it asks
 *   every open page to flush the report queue.
 *
 * Bump VERSION to drop old caches on the next activation.
 */

const VERSION = "v1";
const SHELL_CACHE = `cp-shell-${VERSION}`;
const PAGE_CACHE = `cp-pages-${VERSION}`;
const STATIC_CACHE = `cp-static-${VERSION}`;
const OFFLINE_URL = "/offline.html";
const PRECACHE = [
  OFFLINE_URL,
  "/offline.js",
  "/icons/icon-192.png",
  "/icons/icon-512.png",
];
const MAX_PAGES = 40;
const SYNC_TAG = "report-queue";

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(SHELL_CACHE)
      .then((cache) => cache.addAll(PRECACHE))
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener("activate", (event) => {
  const keep = new Set([SHELL_CACHE, PAGE_CACHE, STATIC_CACHE]);
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys
            .filter((key) => key.startsWith("cp-") && !keep.has(key))
            .map((key) => caches.delete(key)),
        ),
      )
      .then(() => self.clients.claim()),
  );
});

async function trimPages() {
  const cache = await caches.open(PAGE_CACHE);
  const keys = await cache.keys();
  await Promise.all(
    keys
      .slice(0, Math.max(0, keys.length - MAX_PAGES))
      .map((k) => cache.delete(k)),
  );
}

async function handleNavigation(request) {
  try {
    const response = await fetch(request);
    // Only plain, successful HTML pages: never redirects or error pages.
    if (response.ok && response.type === "basic") {
      const copy = response.clone();
      caches
        .open(PAGE_CACHE)
        .then((cache) => cache.put(request, copy))
        .then(trimPages);
    }
    return response;
  } catch {
    const cached = await caches.match(request, { ignoreSearch: true });
    if (cached) return cached;
    return (await caches.match(OFFLINE_URL)) || Response.error();
  }
}

async function handleStatic(request) {
  const cached = await caches.match(request);
  if (cached) return cached;
  const response = await fetch(request);
  if (response.ok) {
    const copy = response.clone();
    caches.open(STATIC_CACHE).then((cache) => cache.put(request, copy));
  }
  return response;
}

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  if (request.mode === "navigate") {
    event.respondWith(handleNavigation(request));
    return;
  }
  if (url.pathname.startsWith("/_next/static/")) {
    event.respondWith(handleStatic(request));
  }
});

async function askPagesToFlush() {
  const pages = await self.clients.matchAll({
    type: "window",
    includeUncontrolled: true,
  });
  for (const page of pages) page.postMessage({ type: "flush-report-queue" });
}

self.addEventListener("sync", (event) => {
  if (event.tag === SYNC_TAG) event.waitUntil(askPagesToFlush());
});

self.addEventListener("message", (event) => {
  if (event.data && event.data.type === "skip-waiting") self.skipWaiting();
});

/*
 * ---- Push notifications ----------------------------------------------
 * Reserved for the notifications work (push + notificationclick). Add the
 * handlers below this line; nothing above depends on them.
 */
