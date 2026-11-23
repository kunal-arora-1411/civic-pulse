import { apiRequest } from "../client";
import { type CurrentUser, currentUserSchema } from "../schemas";

export type UpdateMeBody = Partial<{
  display_name: string;
  email: string | null;
  locale: string;
  preferences: Record<string, unknown>;
}>;

export function getMe(signal?: AbortSignal): Promise<CurrentUser> {
  return apiRequest({ path: "/users/me", schema: currentUserSchema, signal });
}

export function updateMe(body: UpdateMeBody): Promise<CurrentUser> {
  return apiRequest({
    method: "PATCH",
    path: "/users/me",
    body,
    schema: currentUserSchema,
  });
}
