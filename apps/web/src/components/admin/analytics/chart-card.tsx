"use client";

import { BarChart3, ChartNoAxesColumn, Table2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { type ReactNode, useId, useState } from "react";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useErrorMessage } from "@/hooks/use-error-message";
import { cn } from "@/lib/utils";

export type ChartState = {
  isPending: boolean;
  isError: boolean;
  error: unknown;
  refetch: () => unknown;
};

/**
 * The frame every chart sits in: a titled card with a "view as table"
 * switch, and the loading, error and empty states, so each chart only
 * draws its data. The chart itself is a figure named by the card title and
 * described by a one-line summary; the table is the accessible equivalent.
 */
export function ChartCard({
  title,
  description,
  summary,
  state,
  empty,
  table,
  actions,
  className,
  height = "h-72",
  children,
}: {
  title: string;
  description?: string;
  /** One sentence a screen reader hears for the chart. */
  summary?: string;
  state: ChartState;
  /** True when the data loaded but there's nothing to draw. */
  empty?: boolean;
  table?: () => ReactNode;
  /** Extra controls in the header, e.g. a daily/weekly switch. */
  actions?: ReactNode;
  className?: string;
  height?: string;
  children: () => ReactNode;
}) {
  const t = useTranslations("admin.analytics");
  const errorMessage = useErrorMessage();
  const [asTable, setAsTable] = useState(false);
  const titleId = useId();
  const summaryId = useId();

  let body: ReactNode;
  if (state.isPending) {
    body = (
      <div className={cn("relative", height)}>
        <Skeleton className="absolute inset-0 rounded-lg" />
        <output className="sr-only">{t("loading")}</output>
      </div>
    );
  } else if (state.isError) {
    body = (
      <Alert variant="destructive" title={t("error")} live="polite">
        <p>{errorMessage(state.error)}</p>
        <Button
          variant="outline"
          size="sm"
          className="mt-2"
          onClick={() => state.refetch()}
        >
          {t("retry")}
        </Button>
      </Alert>
    );
  } else if (empty) {
    body = (
      <div
        className={cn(
          "grid place-items-center rounded-lg border border-dashed border-border text-center text-sm text-muted-foreground",
          height,
        )}
      >
        <div className="grid justify-items-center gap-2 p-4">
          <ChartNoAxesColumn aria-hidden="true" className="size-6 opacity-60" />
          <p>{t("empty")}</p>
        </div>
      </div>
    );
  } else if (asTable && table) {
    body = table();
  } else {
    body = (
      <figure
        aria-labelledby={titleId}
        aria-describedby={summary ? summaryId : undefined}
        className={cn("m-0", height)}
      >
        {children()}
        {summary ? (
          <figcaption id={summaryId} className="sr-only">
            {summary}
          </figcaption>
        ) : null}
      </figure>
    );
  }

  const canToggle = Boolean(
    table && !state.isPending && !state.isError && !empty,
  );

  return (
    <section
      aria-labelledby={titleId}
      className={cn(
        "flex min-w-0 flex-col rounded-xl border border-border bg-card text-card-foreground shadow-card",
        className,
      )}
    >
      <header className="flex flex-wrap items-start justify-between gap-2 p-5 pb-3">
        <div className="grid min-w-0 gap-0.5">
          <h2 id={titleId} className="text-base font-semibold leading-tight">
            {title}
          </h2>
          {description ? (
            <p className="text-sm text-muted-foreground">{description}</p>
          ) : null}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {actions}
          {canToggle ? (
            <Button
              variant="ghost"
              size="sm"
              aria-pressed={asTable}
              onClick={() => setAsTable((v) => !v)}
            >
              {asTable ? (
                <BarChart3 aria-hidden="true" />
              ) : (
                <Table2 aria-hidden="true" />
              )}
              <span>{asTable ? t("viewChart") : t("viewTable")}</span>
              <span className="sr-only">: {title}</span>
            </Button>
          ) : null}
        </div>
      </header>
      <div className="min-w-0 flex-1 px-5 pb-5">{body}</div>
    </section>
  );
}

/** A compact table for the "view as table" side of a chart. */
export function DataTable({
  label,
  columns,
  rows,
}: {
  label: string;
  columns: { key: string; label: string; numeric?: boolean }[];
  rows: { key: string; cells: ReactNode[] }[];
}) {
  return (
    <section
      aria-label={label}
      // biome-ignore lint/a11y/noNoninteractiveTabindex: a scrollable region must be keyboard reachable
      tabIndex={0}
      className="max-h-80 overflow-auto rounded-lg border border-border"
    >
      <table className="w-full text-sm">
        <caption className="sr-only">{label}</caption>
        <thead className="sticky top-0 bg-muted text-start text-muted-foreground">
          <tr>
            {columns.map((column) => (
              <th
                key={column.key}
                scope="col"
                className={cn(
                  "px-3 py-2 font-medium",
                  column.numeric ? "text-end" : "text-start",
                )}
              >
                {column.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.key} className="border-t border-border">
              {row.cells.map((cell, index) => {
                const column = columns[index];
                return index === 0 ? (
                  <th
                    key={column?.key}
                    scope="row"
                    className="px-3 py-1.5 text-start font-normal"
                  >
                    {cell}
                  </th>
                ) : (
                  <td
                    key={column?.key}
                    className={cn(
                      "px-3 py-1.5",
                      column?.numeric && "text-end tabular-nums",
                    )}
                  >
                    {cell}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
