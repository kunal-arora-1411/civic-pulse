import { usersGetMe, usersUpdateMe } from "@civicpulse/api-client";
import { call } from "../generated-client";
import { type CurrentUser, currentUserSchema } from "../schemas";

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
