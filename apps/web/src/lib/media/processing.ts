import type { Media } from "@/lib/api";

/** How often to look again while a photo is still being processed. */
export const PROCESSING_POLL_MS = 3_000;
/** Give up after about two minutes; the photo shows on the next visit. */
export const PROCESSING_MAX_POLLS = 40;

/**
 * A React Query `refetchInterval` for pages that show photos. Variants are
 * made by a background job after the upload completes, so a page opened
 * straight after submitting can arrive before they exist and would
 * otherwise keep its placeholders until the next visit.
 */
export function processingRefetchInterval(
  media: readonly Pick<Media, "status">[] | undefined,
  pollsSoFar: number,
): number | false {
  if (pollsSoFar >= PROCESSING_MAX_POLLS) return false;
  return media?.some((item) => item.status === "processing")
    ? PROCESSING_POLL_MS
    : false;
}
