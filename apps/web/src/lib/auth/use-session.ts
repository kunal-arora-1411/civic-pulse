"use client";

import { useSyncExternalStore } from "react";
import { type SessionSnapshot, session } from "@/lib/api";

const serverSnapshot: SessionSnapshot = { status: "unknown", user: null };

/**
 * The current session. During prerendering and the first client render it
 * is always "unknown", because the token only exists in browser memory.
 * Pages render a loading state for that case, which is also what ends up
 * in the static shell.
 */
export function useSession(): SessionSnapshot {
  return useSyncExternalStore(
    session.subscribe,
    session.getSnapshot,
    () => serverSnapshot,
  );
}
