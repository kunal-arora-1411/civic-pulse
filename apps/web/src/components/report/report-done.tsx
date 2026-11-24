"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowRight, Check, CircleCheckBig, Copy, Plus } from "lucide-react";
import { useTranslations } from "next-intl";
import { useEffect, useRef, useState } from "react";
import { MatchingStatus } from "@/components/citizen/matching-status";
import { Button, buttonVariants } from "@/components/ui/button";
import { Link } from "@/i18n/navigation";
import { getReport, type Report } from "@/lib/api";
import { matchingRefetchInterval } from "@/lib/report/matching";

export function ReportDone({
  report: submitted,
  onAnother,
}: {
  report: Report;
  onAnother: () => void;
}) {
  const t = useTranslations("report.done");
  const heading = useRef<HTMLHeadingElement>(null);
  const [copied, setCopied] = useState(false);

  // Matching runs after the report is accepted, so the response usually
  // says "pending". Follow the report until it has an issue. Seeding the
  // cache also makes "View your report" open instantly.
  const query = useQuery({
    queryKey: ["reports", "detail", submitted.id],
    queryFn: ({ signal }) => getReport(submitted.id, signal),
    initialData: submitted,
    // The response is fresh; only the polling below should refetch.
    staleTime: Number.POSITIVE_INFINITY,
    refetchInterval: ({ state }) =>
      matchingRefetchInterval(state.data, state.dataUpdateCount),
  });
  const report = query.data;

  useEffect(() => {
    heading.current?.focus();
  }, []);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(report.reference);
      setCopied(true);
      setTimeout(() => setCopied(false), 2500);
    } catch {
      // Clipboard blocked: the reference is on screen to copy by hand.
    }
  };

  return (
    <div className="grid justify-items-center gap-6 py-6 text-center motion-safe:animate-rise">
      <span className="relative grid size-20 place-items-center">
        <span
          aria-hidden="true"
          className="bg-brand-gradient absolute inset-0 rounded-full opacity-25 blur-xl"
        />
        <span className="bg-brand-gradient relative grid size-20 place-items-center rounded-full text-white shadow-raised">
          <CircleCheckBig aria-hidden="true" className="size-10" />
        </span>
      </span>
      <div className="grid gap-2">
        <h2
          ref={heading}
          tabIndex={-1}
          className="text-3xl font-semibold tracking-tight outline-none sm:text-4xl"
        >
          {t("title")}
        </h2>
        <p className="max-w-md text-muted-foreground">
          {report.ward?.name
            ? t("body", { ward: report.ward.name })
            : t("bodyNoWard")}
        </p>
      </div>

      <div className="grid w-full max-w-sm gap-2 rounded-2xl border border-border bg-card p-5 shadow-card">
        <p className="eyebrow">{t("referenceLabel")}</p>
        <div className="flex items-center justify-center gap-2">
          <p className="font-mono text-2xl font-semibold tracking-wide">
            {report.reference}
          </p>
          <Button
            variant="ghost"
            size="icon-sm"
            onClick={copy}
            aria-label={copied ? t("copied") : t("copy")}
          >
            {copied ? (
              <Check aria-hidden="true" className="text-primary" />
            ) : (
              <Copy aria-hidden="true" />
            )}
          </Button>
        </div>
        <p className="text-sm text-muted-foreground">{t("referenceHelp")}</p>
        <output className="sr-only">{copied ? t("copied") : ""}</output>
      </div>

      <MatchingStatus report={report} className="w-full max-w-sm" />

      <div className="grid w-full max-w-sm gap-2">
        <Link
          href={`/reports/${report.id}`}
          className={buttonVariants({ variant: "ink", size: "lg" })}
        >
          {t("view")}
          <ArrowRight aria-hidden="true" className="rtl:rotate-180" />
        </Link>
        <Button size="lg" variant="outline" onClick={onAnother}>
          <Plus aria-hidden="true" />
          {t("another")}
        </Button>
        <Link href="/" className={buttonVariants({ variant: "ghost" })}>
          {t("home")}
        </Link>
      </div>
    </div>
  );
}
