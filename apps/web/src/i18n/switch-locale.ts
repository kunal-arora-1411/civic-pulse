import { type AppLocale, localeCookie } from "./routing";

/**
 * Store the locale and load the page again in it.
 *
 * This is a full document load on purpose. A soft navigation (next-intl's
 * `router.replace(path, { locale })`) does work, but with Cache Components
 * the old-language tree stays mounted inside <Activity>, and App Shells
 * prefetched in the previous language can still be served from the client
 * cache for a few minutes, so parts of the UI could come back in the
 * wrong language. A reload clears all of that. The in-memory access
 * token is lost, but the session is restored from the refresh cookie as
 * on any page load.
 */
export function switchLocale(locale: AppLocale, href?: string): void {
  const { name, maxAge, sameSite } = localeCookie;
  // biome-ignore lint/suspicious/noDocumentCookie: a plain preference cookie the proxy reads; the Cookie Store API isn't available everywhere yet
  document.cookie = `${name}=${locale}; path=/; max-age=${maxAge}; samesite=${sameSite}`;
  if (href) window.location.assign(href);
  else window.location.reload();
}
