/**
 * A script that runs while the HTML is parsed, before first paint. On the
 * client it renders as text/plain, so React doesn't warn about rendering
 * a script tag (it would never run there anyway); suppressHydrationWarning
 * covers the differing type. See the Next guide on preventing a flash
 * before hydration.
 */
export function InlineScript({ html }: { html: string }) {
  return (
    <script
      type={typeof window === "undefined" ? "text/javascript" : "text/plain"}
      suppressHydrationWarning
      // biome-ignore lint/security/noDangerouslySetInnerHtml: callers pass fixed, first-party code only
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
}
