import { useTranslations } from "next-intl";
import { Logo } from "@/components/brand/logo";
import { LanguageSwitcher } from "@/components/language-switcher";

export default function HomePage() {
  const t = useTranslations();
  return (
    <>
      <header className="flex items-center justify-between gap-4 px-4 py-3 sm:px-6">
        <Logo />
        <LanguageSwitcher />
      </header>
      <main id="main" className="bg-survey-grid flex-1 px-4 py-12 sm:px-6">
        <div className="mx-auto grid max-w-xl gap-4">
          <h1 className="text-4xl font-semibold">{t("common.tagline")}</h1>
          <p className="text-lg text-muted-foreground">{t("home.intro")}</p>
        </div>
      </main>
    </>
  );
}
