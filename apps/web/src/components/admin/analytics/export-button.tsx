"use client";

import { Download } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { useToast } from "@/components/ui/toast";
import { useErrorMessage } from "@/hooks/use-error-message";
import {
  type AnalyticsFilters,
  isRangeInvalid,
  toQuery,
} from "@/lib/analytics/filters";
import { exportAnalyticsCsv } from "@/lib/api";
import { saveFile } from "@/lib/download";

/**
 * AN-002: the issues behind these figures, as a CSV. It sends the filters
 * currently in the URL, so the file covers the same period, ward, category
 * and statuses as the dashboard. Reporter identity is never in it.
 */
export function ExportButton({ filters }: { filters: AnalyticsFilters }) {
  const t = useTranslations("admin.analytics.export");
  const describeError = useErrorMessage();
  const { toast } = useToast();
  const [busy, setBusy] = useState(false);
  const invalid = isRangeInvalid(filters);

  async function download() {
    setBusy(true);
    try {
      const file = await exportAnalyticsCsv(toQuery(filters));
      saveFile(file.blob, file.filename ?? t("fallbackFilename"));
      const rows = Number(file.headers.get("X-Export-Rows") ?? 0);
      // The backend caps the file and says so in a header, so nobody
      // mistakes a partial file for the whole period.
      if (file.headers.get("X-Export-Truncated") === "true") {
        toast({
          variant: "info",
          title: t("truncatedTitle", { rows }),
          description: t("truncatedDescription"),
        });
      } else {
        toast({ variant: "success", title: t("doneTitle", { rows }) });
      }
    } catch (error) {
      toast({
        variant: "error",
        title: t("failedTitle"),
        description: describeError(error),
      });
    } finally {
      setBusy(false);
    }
  }

  return (
    <Button
      variant="secondary"
      onClick={download}
      disabled={busy || invalid}
      aria-busy={busy}
      title={invalid ? t("rangeInvalid") : undefined}
    >
      {busy ? <Spinner label={t("busy")} /> : <Download aria-hidden="true" />}
      {busy ? t("busy") : t("label")}
    </Button>
  );
}
