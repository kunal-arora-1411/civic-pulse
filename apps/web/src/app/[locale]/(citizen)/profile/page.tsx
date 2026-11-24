import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { ProfileScreen } from "@/components/profile/profile-screen";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("profile");
  return { title: t("title"), robots: { index: false } };
}

export default function ProfilePage() {
  return (
    <main
      id="main"
      className="mx-auto w-full max-w-2xl flex-1 px-5 py-10 sm:px-8"
    >
      <ProfileScreen />
    </main>
  );
}
