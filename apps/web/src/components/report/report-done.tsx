"use client";

import { ArrowRight, Check, CircleCheckBig, Copy, Plus } from "lucide-react";
import { useTranslations } from "next-intl";
import { useEffect, useRef, useState } from "react";
import { Button, buttonVariants } from "@/components/ui/button";
import { Link } from "@/i18n/navigation";
import type { Report } from "@/lib/api";

export function ReportDone({
  report,
  onAnother,
}: {
  report: Report;
  onAnother: () => void;
}) {
  const t = useTranslations("report.done");
  const heading = useRef<HTMLHeadingElement>(null);
  const [copied, setCopied] = useState(false);

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
      <span className="grid size-16 place-items-center rounded-full bg-success-soft text-success-soft-foreground">
        <CircleCheckBig aria-hidden="true" className="size-9" />
      </span>
      <div className="grid gap-2">
        <h2
          ref={heading}
          tabIndex={-1}
          className="text-2xl font-semibold outline-none sm:text-3xl"
        >
          {t("title")}
        </h2>
        <p className="max-w-md text-muted-foreground">
          {report.ward?.name
            ? t("body", { ward: report.ward.name })
            : t("bodyNoWard")}
        </p>
      </div>

      <div className="grid w-full max-w-sm gap-2 rounded-xl border border-border bg-card p-5 shadow-card">
        <p className="text-sm font-semibold text-muted-foreground">
          {t("referenceLabel")}
        </p>
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

      <div className="grid w-full max-w-sm gap-2">
        <Link
          href={`/reports/${report.id}`}
          className={buttonVariants({ size: "lg" })}
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
