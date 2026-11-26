"use client";

import { useTranslations } from "next-intl";
import { RequireSession } from "@/components/auth/require-session";
import { useSession } from "@/lib/auth/use-session";
import { NotificationSettings } from "./notification-settings";
import { ProfileForm } from "./profile-form";

function ProfileBody() {
  const { user } = useSession();
  if (!user) return null;
  // Re-mount the form when the user changes so its defaults stay in sync.
  return (
    <div className="grid gap-6">
      <ProfileForm key={user.id} user={user} />
      {/* A platform administrator has no municipality, so no notifications. */}
      {user.tenant_id ? <NotificationSettings key={`n-${user.id}`} /> : null}
    </div>
  );
}

export function ProfileScreen() {
  const t = useTranslations("profile");
  return (
    <div className="grid gap-6 motion-safe:animate-rise">
      <div className="grid gap-2">
        <h1 className="text-3xl font-semibold tracking-tight sm:text-5xl">
          {t("title")}
        </h1>
        <p className="text-lg text-muted-foreground">{t("description")}</p>
      </div>
      <RequireSession>
        <ProfileBody />
      </RequireSession>
    </div>
  );
}
