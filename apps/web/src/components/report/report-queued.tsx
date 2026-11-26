"use client";

import { CloudUpload, Plus, Send, Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { useEffect, useRef } from "react";
import { Button, buttonVariants } from "@/components/ui/button";
import { Link } from "@/i18n/navigation";
import { discardQueued, useReportQueue } from "@/lib/offline/use-report-queue";

/** Shown instead of the confirmation when the report was queued offline. */
export function ReportQueued({ onAnother }: { onAnother: () => void }) {
  const t = useTranslations("offline");
  const tDone = useTranslations("report.done");
  const heading = useRef<HTMLHeadingElement>(null);
  const { items, flush } = useReportQueue();
  const waiting = items.filter((item) => item.status === "queued").length;
  const failed = items.filter((item) => item.status === "failed");

  useEffect(() => {
    heading.current?.focus();
  }, []);

  return (
    <div className="grid justify-items-center gap-6 py-6 text-center motion-safe:animate-rise">
      <span className="grid size-20 place-items-center rounded-full bg-muted text-foreground">
        <CloudUpload aria-hidden="true" className="size-10" />
      </span>
      <div className="grid gap-2">
        <h2
          ref={heading}
          tabIndex={-1}
          className="text-3xl font-semibold tracking-tight outline-none sm:text-4xl"
        >
          {t("queuedTitle")}
        </h2>
        <p className="max-w-md text-muted-foreground">{t("queuedBody")}</p>
        <output className="text-sm font-medium">
          {waiting > 0 ? t("queuedPending", { count: waiting }) : null}
        </output>
      </div>

      {failed.length > 0 ? (
        <ul className="grid w-full max-w-sm gap-2 text-start">
          {failed.map((item) => (
            <li
              key={item.id}
              className="flex items-center justify-between gap-2 rounded-xl border border-border bg-card p-3 text-sm"
            >
              <span>
                {t("queuedFailed")}
                {item.body.description ? (
                  <span className="block truncate text-muted-foreground">
                    {item.body.description}
                  </span>
                ) : null}
              </span>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => void discardQueued(item.id)}
              >
                <Trash2 aria-hidden="true" />
                {t("discard")}
              </Button>
            </li>
          ))}
        </ul>
      ) : null}

      <div className="grid w-full max-w-sm gap-2">
        {waiting > 0 ? (
          <Button size="lg" variant="ink" onClick={() => void flush()}>
            <Send aria-hidden="true" />
            {t("sendNow")}
          </Button>
        ) : null}
        <Button size="lg" variant="outline" onClick={onAnother}>
          <Plus aria-hidden="true" />
          {tDone("another")}
        </Button>
        <Link href="/" className={buttonVariants({ variant: "ghost" })}>
          {tDone("home")}
        </Link>
      </div>
    </div>
  );
}
