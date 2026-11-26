import {
  usersAnonymizeMe,
  usersGetMe,
  usersUpdateMe,
} from "@civicpulse/api-client";
import { call, callVoid } from "../generated-client";
import { type CurrentUser, currentUserSchema } from "../schemas";
import { session } from "../session";

/**
 * Narrower than the spec's `UserMeUpdate`, which also accepts `null` for
 * `display_name`, `locale` and `preferences`; the app never clears those.
 */
export type UpdateMeBody = Partial<{
  display_name: string;
  email: string | null;
  locale: string;
  preferences: Record<string, unknown>;
}>;

export function getMe(signal?: AbortSignal): Promise<CurrentUser> {
  return call(currentUserSchema, (o) => usersGetMe(o), { signal });
}

export function updateMe(body: UpdateMeBody): Promise<CurrentUser> {
  return call(currentUserSchema, (o) => usersUpdateMe(body, o));
}

/**
 * Wipe the caller's personal data and end every session (citizens only).
 * Irreversible. The server also clears the refresh cookie.
 */
export async function anonymizeMe(): Promise<void> {
  await callVoid((o) => usersAnonymizeMe(o), { credentials: "include" });
  session.clear();
}
