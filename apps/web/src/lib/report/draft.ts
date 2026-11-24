import type { LocationSource } from "@/lib/api";
import type { DraftSuggestion } from "./suggestion";

/*
 * The report draft, kept in sessionStorage so a reload, a trip to the
 * camera app that evicts the tab, or a sign-in in the middle of the flow
 * doesn't lose what the citizen has entered.
 *
 * The draft owns its Idempotency-Key. It's generated once, when the draft
 * is created, and sent with every submission attempt of that draft, so a
 * retry after a dropped connection replays the first result instead of
 * creating a second report. Only a new draft gets a new key.
 *
 * sessionStorage is per tab and cleared when the tab closes, which is the
 * right lifetime on a shared phone. It holds no secrets: media ids, the
 * location and the text the citizen typed.
 */

export const DRAFT_STORAGE_KEY = "civicpulse:report-draft";
const DRAFT_VERSION = 1;

export type ReportStep = 1 | 2 | 3 | 4;
export const REPORT_STEPS: readonly ReportStep[] = [1, 2, 3, 4];

/** A photo that finished uploading, as kept across reloads. */
export type DraftPhoto = {
  /** Local id, stable for React keys. */
  id: string;
  mediaId: string;
  /** A small JPEG data URL, so the thumbnail survives a reload. */
  thumbDataUrl: string | null;
};

export type DraftLocation = {
  lat: number;
  lng: number;
  /** Only for GPS fixes the citizen hasn't moved. */
  accuracyM: number | null;
  source: LocationSource;
  /** Set when the citizen confirmed an imprecise GPS fix. */
  accuracyConfirmed?: boolean;
};

export type ReportDraft = {
  version: typeof DRAFT_VERSION;
  idempotencyKey: string;
  /**
   * When the citizen first pressed Send with the current key, sent as
   * `client_created_at`. It's fixed on the first attempt and reused on
   * retries: the key only replays the original report if the body is
   * byte-for-byte the same, so a fresh timestamp on every attempt would
   * turn a retry into `idempotency_key_reused`. Absent until then (and in
   * drafts saved before this field existed).
   */
  submittedAt?: string;
  createdAt: string;
  step: ReportStep;
  photos: DraftPhoto[];
  location: DraftLocation | null;
  /** What the geocoder returned for `location`, shown on review. */
  addressText: string | null;
  wardName: string | null;
  categoryId: string | null;
  /**
   * Who picked `categoryId`: the AI suggestion, pre-selected for the
   * citizen, or the citizen. A citizen's choice is never overridden.
   */
  categorySource?: "ai" | "citizen" | null;
  /**
   * The classification whose suggestion was shown on the category step.
   * It's sent with the report so the server can tell an accepted
   * suggestion from a corrected one; left unset when none was shown.
   */
  classificationId?: string | null;
  /** The last finished classification, so a reload doesn't ask again. */
  suggestion?: DraftSuggestion | null;
  details: Record<string, string | boolean>;
  description: string;
};

export function randomId(): string {
  if (typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  // Insecure contexts (plain-http LAN testing) have no randomUUID.
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, "0"));
  return `${hex.slice(0, 4).join("")}-${hex.slice(4, 6).join("")}-${hex.slice(6, 8).join("")}-${hex.slice(8, 10).join("")}-${hex.slice(10).join("")}`;
}

export function newDraft(now: Date = new Date()): ReportDraft {
  return {
    version: DRAFT_VERSION,
    idempotencyKey: randomId(),
    createdAt: now.toISOString(),
    step: 1,
    photos: [],
    location: null,
    addressText: null,
    wardName: null,
    categoryId: null,
    details: {},
    description: "",
  };
}

function isDraft(value: unknown): value is ReportDraft {
  if (!value || typeof value !== "object") return false;
  const draft = value as Partial<ReportDraft>;
  return (
    draft.version === DRAFT_VERSION &&
    typeof draft.idempotencyKey === "string" &&
    draft.idempotencyKey.length > 0 &&
    Array.isArray(draft.photos) &&
    typeof draft.step === "number" &&
    REPORT_STEPS.includes(draft.step as ReportStep)
  );
}

type StorageLike = Pick<Storage, "getItem" | "setItem" | "removeItem">;

function defaultStorage(): StorageLike | null {
  try {
    return typeof window === "undefined" ? null : window.sessionStorage;
  } catch {
    // Storage can throw in private modes with storage disabled.
    return null;
  }
}

/** The stored draft, or a fresh one (with a new key) if there's none. */
export function loadDraft(
  storage: StorageLike | null = defaultStorage(),
): ReportDraft {
  try {
    const raw = storage?.getItem(DRAFT_STORAGE_KEY);
    if (raw) {
      const parsed: unknown = JSON.parse(raw);
      if (isDraft(parsed)) return parsed;
    }
  } catch {
    // A corrupt entry is treated as no draft.
  }
  return newDraft();
}

export function saveDraft(
  draft: ReportDraft,
  storage: StorageLike | null = defaultStorage(),
): void {
  try {
    storage?.setItem(DRAFT_STORAGE_KEY, JSON.stringify(draft));
  } catch {
    // Quota exceeded: the flow keeps working, it just won't survive a
    // reload. Thumbnails are small, so this is unlikely.
  }
}

export function clearDraft(
  storage: StorageLike | null = defaultStorage(),
): void {
  try {
    storage?.removeItem(DRAFT_STORAGE_KEY);
  } catch {
    // Nothing to do.
  }
}

/** True once the citizen has entered anything worth keeping. */
export function hasProgress(draft: ReportDraft): boolean {
  return (
    draft.photos.length > 0 ||
    draft.location !== null ||
    draft.categoryId !== null ||
    draft.description.trim() !== ""
  );
}
