import type { NextConfig } from "next";
import createNextIntlPlugin from "next-intl/plugin";

const isDev = process.env.NODE_ENV === "development";

function origin(url: string | undefined): string | null {
  if (!url) return null;
  try {
    // Tile templates like https://{s}.tile.example/{z}/... aren't valid URLs
    // until the placeholders are filled in.
    return new URL(url.replace(/\{s\}\./, "")).origin;
  } catch {
    return null;
  }
}

/*
 * Where the browser may connect and load images from, besides this origin:
 * the API, object storage (pre-signed PUTs and photo URLs) and map tiles.
 * Read at build time, like the NEXT_PUBLIC_* values themselves.
 * CSP_EXTRA_ORIGINS is a space- or comma-separated list for anything else
 * (a CDN in front of storage, for example); it defaults to the compose MinIO.
 */
const apiOrigin =
  origin(process.env.NEXT_PUBLIC_API_URL) ?? "http://localhost:8000";
const tileOrigin =
  origin(process.env.NEXT_PUBLIC_MAP_TILE_URL) ??
  "https://tile.openstreetmap.org";
const tileWildcard = process.env.NEXT_PUBLIC_MAP_TILE_URL?.includes("{s}.")
  ? tileOrigin.replace("://", "://*.")
  : null;
const extra = (process.env.CSP_EXTRA_ORIGINS ?? "http://localhost:9000")
  .split(/[\s,]+/)
  .filter(Boolean);

const remote = [apiOrigin, ...extra].join(" ");
const images = [tileOrigin, tileWildcard, ...extra].filter(Boolean).join(" ");

/*
 * No nonces: Cache Components serves a static shell, which can't carry a
 * per-request nonce (see the Next CSP guide), so inline scripts are allowed
 * and the policy relies on everything else being locked down.
 */
const csp = [
  "default-src 'self'",
  `script-src 'self' 'unsafe-inline'${isDev ? " 'unsafe-eval'" : ""}`,
  // Leaflet positions map tiles with inline styles.
  "style-src 'self' 'unsafe-inline'",
  `img-src 'self' blob: data: ${images}`,
  "font-src 'self'",
  `connect-src 'self' ${remote}${isDev ? " ws:" : ""}`,
  "media-src 'self' blob:",
  "worker-src 'self'",
  "manifest-src 'self'",
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "frame-ancestors 'none'",
  ...(isDev ? [] : ["upgrade-insecure-requests"]),
].join("; ");

const securityHeaders = [
  { key: "Content-Security-Policy", value: csp },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  // The report flow uses the camera, location and (for voice notes) the
  // microphone, on this origin only.
  {
    key: "Permissions-Policy",
    value:
      "camera=(self), geolocation=(self), microphone=(self), payment=(), usb=()",
  },
];

const nextConfig: NextConfig = {
  cacheComponents: true,
  partialPrefetching: true,
  experimental: {
    // Failed navigations wait for the network instead of throwing, and
    // useOffline() drives the offline banner (P6-01).
    useOffline: true,
  },
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
  async headers() {
    return [
      { source: "/(.*)", headers: securityHeaders },
      {
        source: "/sw.js",
        headers: [
          {
            key: "Content-Type",
            value: "application/javascript; charset=utf-8",
          },
          {
            key: "Cache-Control",
            value: "no-cache, no-store, must-revalidate",
          },
          {
            key: "Content-Security-Policy",
            value: "default-src 'self'; script-src 'self'",
          },
        ],
      },
    ];
  },
};

const withNextIntl = createNextIntlPlugin("./src/i18n/request.ts");

export default withNextIntl(nextConfig);
