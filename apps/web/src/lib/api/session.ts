import type { CurrentUser } from "./schemas";

export type SessionStatus = "unknown" | "authenticated" | "anonymous";

export type SessionSnapshot = {
  status: SessionStatus;
  user: CurrentUser | null;
};

/*
 * The access token lives only in this module's memory: never in
 * localStorage, sessionStorage or a readable cookie, so an XSS payload
 * can't lift it from storage. A reload loses it, and the session is
 * restored from the HttpOnly refresh cookie instead.
 *
 * The token is deliberately kept out of the snapshot React subscribes to,
 * so it never ends up in component state or React DevTools.
 */
let accessToken: string | null = null;
let snapshot: SessionSnapshot = { status: "unknown", user: null };
const listeners = new Set<() => void>();

function emit(next: SessionSnapshot) {
  snapshot = next;
  for (const listener of listeners) listener();
}

export const session = {
  getAccessToken: (): string | null => accessToken,
  getSnapshot: (): SessionSnapshot => snapshot,
  subscribe(listener: () => void): () => void {
    listeners.add(listener);
    return () => listeners.delete(listener);
  },
  setAuthenticated(token: string, user: CurrentUser) {
    accessToken = token;
    emit({ status: "authenticated", user });
  },
  setUser(user: CurrentUser) {
    if (snapshot.status !== "authenticated") return;
    emit({ status: "authenticated", user });
  },
  clear() {
    accessToken = null;
    emit({ status: "anonymous", user: null });
  },
  /** Test helper: back to the pristine, not-yet-restored state. */
  reset() {
    accessToken = null;
    emit({ status: "unknown", user: null });
  },
};
