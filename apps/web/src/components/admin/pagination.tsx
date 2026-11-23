"use client";

import { ChevronLeft, ChevronRight } from "lucide-react";
import { useTranslations } from "next-intl";
import { Button } from "@/components/ui/button";

export function Pagination({
  offset,
  limit,
  total,
  onOffsetChange,
  label,
}: {
  offset: number;
  limit: number;
  total: number;
  onOffsetChange: (offset: number) => void;
  /** Names the navigation landmark, e.g. "Users pages". */
  label: string;
}) {
  const t = useTranslations("pagination");
  if (total === 0) return null;
  const from = offset + 1;
  const to = Math.min(offset + limit, total);

  return (
    <nav
      aria-label={label}
      className="mt-4 flex flex-col items-center justify-between gap-3 sm:flex-row"
    >
      <p className="text-sm text-muted-foreground" aria-live="polite">
        {t("range", { from, to, total })}
      </p>
      <div className="flex gap-2">
        <Button
          variant="outline"
          size="sm"
          disabled={offset === 0}
          onClick={() => onOffsetChange(Math.max(0, offset - limit))}
        >
          <ChevronLeft aria-hidden="true" className="rtl:rotate-180" />
          {t("previous")}
        </Button>
        <Button
          variant="outline"
          size="sm"
          disabled={to >= total}
          onClick={() => onOffsetChange(offset + limit)}
        >
          {t("next")}
          <ChevronRight aria-hidden="true" className="rtl:rotate-180" />
        </Button>
      </div>
    </nav>
  );
}
