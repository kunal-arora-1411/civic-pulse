import { notFound } from "next/navigation";

// The proxy rewrites every path under `[locale]`, so unknown URLs land here
// and render the localized not-found page instead of a bare 404.
export default function CatchAll() {
  notFound();
}
