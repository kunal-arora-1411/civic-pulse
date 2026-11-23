import { Camera, CheckCheck, Route } from "lucide-react";
import { useTranslations } from "next-intl";
import { MyReports } from "@/components/citizen/my-reports";
import { ReportCta } from "@/components/citizen/report-cta";

export default function HomePage() {
  const t = useTranslations("citizen");
  const tCommon = useTranslations("common");
  const steps = [
    { icon: Camera, title: t("step1Title"), body: t("step1Body") },
    { icon: Route, title: t("step2Title"), body: t("step2Body") },
    { icon: CheckCheck, title: t("step3Title"), body: t("step3Body") },
  ];

  return (
    <main id="main" className="flex-1">
      <section className="bg-survey-grid relative overflow-hidden border-b border-border/70">
        <div
          aria-hidden="true"
          className="absolute -end-32 -top-32 size-[28rem] rounded-full bg-accent-soft blur-3xl"
        />
        <div className="relative mx-auto grid max-w-5xl gap-8 px-4 py-12 sm:px-6 sm:py-20">
          <div className="grid max-w-2xl gap-5 motion-safe:animate-rise">
            <p className="w-fit rounded-full border border-primary/25 bg-primary-soft px-3 py-1 text-sm font-semibold text-primary-soft-foreground">
              {tCommon("tagline")}
            </p>
            <h1 className="text-4xl leading-[1.1] font-semibold sm:text-6xl">
              {t.rich("headline", {
                accent: (chunks) => (
                  <span className="relative whitespace-nowrap text-primary">
                    {chunks}
                    <svg
                      aria-hidden="true"
                      viewBox="0 0 200 12"
                      preserveAspectRatio="none"
                      className="absolute inset-x-0 -bottom-1.5 h-2.5 w-full"
                    >
                      <path
                        d="M2 9C40 3 80 2 198 6"
                        fill="none"
                        strokeWidth="5"
                        strokeLinecap="round"
                        className="stroke-accent"
                      />
                    </svg>
                  </span>
                ),
              })}
            </h1>
            <p className="max-w-xl text-lg text-muted-foreground sm:text-xl">
              {t("intro")}
            </p>
          </div>
          <ReportCta />
        </div>
      </section>

      <div className="mx-auto grid max-w-5xl gap-12 px-4 py-12 sm:px-6">
        <MyReports />

        <section aria-labelledby="how-it-works" className="grid gap-6">
          <h2 id="how-it-works" className="text-2xl font-semibold">
            {t("howItWorks")}
          </h2>
          <ol className="grid gap-4 sm:grid-cols-3">
            {steps.map(({ icon: Icon, title, body }, index) => (
              <li
                key={title}
                className="relative grid gap-3 rounded-xl border border-border bg-card p-5 shadow-card"
              >
                <div className="flex items-center justify-between">
                  <span className="grid size-10 place-items-center rounded-lg bg-primary-soft text-primary-soft-foreground">
                    <Icon aria-hidden="true" className="size-5" />
                  </span>
                  <span
                    aria-hidden="true"
                    className="font-display text-3xl font-semibold text-border"
                  >
                    {String(index + 1).padStart(2, "0")}
                  </span>
                </div>
                <h3 className="text-lg font-semibold">{title}</h3>
                <p className="text-muted-foreground">{body}</p>
              </li>
            ))}
          </ol>
        </section>
      </div>
    </main>
  );
}
