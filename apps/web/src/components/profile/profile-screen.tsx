"use client";

import { useTranslations } from "next-intl";
import { RequireSession } from "@/components/auth/require-session";
import { canUseAdmin, canUseField } from "@/lib/auth/access";
import { useSession } from "@/lib/auth/use-session";
import { DeleteAccount } from "./delete-account";
import { NotificationSettings } from "./notification-settings";
import { ProfileForm } from "./profile-form";

function ProfileBody() {
  const { user } = useSession();
  if (!user) return null;
  // Re-mount the form when the user changes so its defaults stay in sync.
  // Staff accounts are deactivated by an administrator instead.
  const citizen = !canUseAdmin(user) && !canUseField(user);
  return (
    <div className="grid gap-6">
      <ProfileForm key={user.id} user={user} />
      {/* A platform administrator has no municipality, so no notifications. */}
      {user.tenant_id ? <NotificationSettings key={`n-${user.id}`} /> : null}
      {citizen ? <DeleteAccount /> : null}
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
