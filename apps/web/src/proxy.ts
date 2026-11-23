import createMiddleware from "next-intl/middleware";
import { routing } from "./i18n/routing";

// Next 16 renamed middleware to proxy. This only resolves the locale and
// rewrites to the internal `[locale]` segment; it does no auth checks.
export default createMiddleware(routing);

export const config = {
  // Skip Next internals and anything that looks like a file (has a dot).
  matcher: "/((?!api|_next|_vercel|.*\\..*).*)",
};
