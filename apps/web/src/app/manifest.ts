import type { MetadataRoute } from "next";

/**
 * The web app manifest (P6-01). English and Hindi share one manifest: the
 * name is the brand, and the start URL lets the proxy pick the locale.
 */
export default function manifest(): MetadataRoute.Manifest {
  return {
    id: "/",
    name: "CivicPulse",
    short_name: "CivicPulse",
    description:
      "Report civic issues to your municipality and follow them until they are fixed.",
    start_url: "/",
    scope: "/",
    display: "standalone",
    orientation: "portrait",
    background_color: "#fafbfb",
    theme_color: "#0f5d57",
    categories: ["government", "utilities"],
    icons: [
      { src: "/icons/icon-192.png", sizes: "192x192", type: "image/png" },
      { src: "/icons/icon-512.png", sizes: "512x512", type: "image/png" },
      {
        src: "/icons/maskable-192.png",
        sizes: "192x192",
        type: "image/png",
        purpose: "maskable",
      },
      {
        src: "/icons/maskable-512.png",
        sizes: "512x512",
        type: "image/png",
        purpose: "maskable",
      },
    ],
    shortcuts: [
      { name: "Report an issue", short_name: "Report", url: "/report" },
    ],
  };
}
