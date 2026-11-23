"use client";

import { useTranslations } from "next-intl";
import { RequireSession } from "@/components/auth/require-session";
import { useSession } from "@/lib/auth/use-session";
import { ProfileForm } from "./profile-form";

function ProfileBody() {
  const { user } = useSession();
  // Re-mount the form when the user changes so its defaults stay in sync.
  return user ? <ProfileForm key={user.id} user={user} /> : null;
}

export function ProfileScreen() {
  const t = useTranslations("profile");
  return (
    <div className="grid gap-6 motion-safe:animate-rise">
      <div className="grid gap-1">
        <h1 className="text-3xl font-semibold">{t("title")}</h1>
        <p className="text-muted-foreground">{t("description")}</p>
      </div>
      <RequireSession>
        <ProfileBody />
      </RequireSession>
    </div>
  );
}
