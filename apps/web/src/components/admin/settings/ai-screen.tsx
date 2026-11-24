"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { CircleCheck } from "lucide-react";
import { useFormatter, useTranslations } from "next-intl";
import { type ReactNode, useState } from "react";
import { useFilterCategories } from "@/components/admin/issues/issue-filters";
import { PageHeader } from "@/components/admin/page-header";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useErrorMessage } from "@/hooks/use-error-message";
import { useLocalized } from "@/hooks/use-reference-data";
import {
  getAiQuality,
  listModels,
  MODEL_TASKS,
  type ModelTask,
} from "@/lib/api";

/** YYYY-MM-DD for a date in Asia/Kolkata, the contract's date zone. */
export function istDate(date: Date): string {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Kolkata",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(date);
}

function isModelTask(task: string): task is ModelTask {
  return (MODEL_TASKS as readonly string[]).includes(task);
}

/** One row per category code that was kept or corrected, busiest first. */
export function categoryChoices(counts: {
  accepted_by_category: Record<string, number>;
  corrected_by_category: Record<string, number>;
}): { code: string; accepted: number; corrected: number }[] {
  const codes = new Set([
    ...Object.keys(counts.accepted_by_category),
    ...Object.keys(counts.corrected_by_category),
  ]);
  return [...codes]
    .map((code) => ({
      code,
      accepted: counts.accepted_by_category[code] ?? 0,
      corrected: counts.corrected_by_category[code] ?? 0,
    }))
    .sort(
      (a, b) =>
        b.accepted + b.corrected - (a.accepted + a.corrected) ||
        a.code.localeCompare(b.code),
    );
}

function defaultRange() {
  const now = new Date();
  return {
    from: istDate(new Date(now.getTime() - 29 * 86_400_000)),
    to: istDate(now),
  };
}

function QueryError({ error, retry }: { error: unknown; retry: () => void }) {
  const t = useTranslations("admin.ai");
  const errorMessage = useErrorMessage();
  return (
    <Alert variant="destructive" live="assertive" title={t("loadError")}>
      <p>{errorMessage(error)}</p>
      <Button variant="outline" size="sm" className="mt-3" onClick={retry}>
        {t("retry")}
      </Button>
    </Alert>
  );
}

function Models() {
  const t = useTranslations("admin.ai");
  const format = useFormatter();
  const models = useQuery({
    queryKey: ["admin", "ai", "models"],
    queryFn: ({ signal }) => listModels(signal),
  });
  return (
    <section aria-labelledby="ai-models" className="grid gap-3">
      <div className="grid gap-1">
        <h2 id="ai-models" className="text-lg font-semibold">
          {t("modelsTitle")}
        </h2>
        <p className="text-sm text-muted-foreground">{t("modelsIntro")}</p>
      </div>
      {models.isError ? (
        <QueryError error={models.error} retry={() => models.refetch()} />
      ) : (
        <Table label={t("modelsTitle")}>
          <TableHeader>
            <TableRow className="hover:bg-transparent">
              <TableHead>{t("colTask")}</TableHead>
              <TableHead>{t("colModel")}</TableHead>
              <TableHead>{t("colSource")}</TableHead>
              <TableHead>{t("colLicense")}</TableHead>
              <TableHead>{t("colDeployed")}</TableHead>
              <TableHead>{t("colUse")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {models.isPending ? (
              <TableRow>
                <TableCell colSpan={6}>
                  <Skeleton className="h-5 w-full" />
                </TableCell>
              </TableRow>
            ) : models.data.items.length === 0 ? (
              <TableRow className="hover:bg-transparent">
                <TableCell colSpan={6} className="text-muted-foreground">
                  {t("noModels")}
                </TableCell>
              </TableRow>
            ) : (
              models.data.items.map((model) => (
                <TableRow key={model.model_id}>
                  <TableCell className="whitespace-nowrap">
                    {isModelTask(model.task)
                      ? t(`task.${model.task}`)
                      : model.task}
                  </TableCell>
                  <TableCell>
                    <span className="font-semibold">{model.name}</span>{" "}
                    <span className="font-mono text-xs">{model.version}</span>
                    {model.active ? (
                      <Badge variant="success" className="ms-2">
                        <CircleCheck aria-hidden="true" />
                        {t("active")}
                      </Badge>
                    ) : null}
                  </TableCell>
                  <TableCell className="max-w-56 break-words font-mono text-xs">
                    {model.source ?? "—"}
                  </TableCell>
                  <TableCell>{model.license ?? "—"}</TableCell>
                  <TableCell className="whitespace-nowrap">
                    {model.deployed_at
                      ? format.dateTime(new Date(model.deployed_at), {
                          dateStyle: "medium",
                        })
                      : "—"}
                  </TableCell>
                  <TableCell className="min-w-48 text-sm">
                    {model.intended_use ?? "—"}
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      )}
    </section>
  );
}

function percent(
  part: number,
  whole: number,
  format: ReturnType<typeof useFormatter>,
) {
  return whole > 0
    ? format.number(part / whole, {
        style: "percent",
        maximumFractionDigits: 0,
      })
    : "—";
}

function Stat({
  label,
  value,
  note,
}: {
  label: string;
  value: ReactNode;
  note?: ReactNode;
}) {
  // Labels take up the slack and the note keeps its line, so the numbers
  // in a row line up even when one label wraps.
  return (
    <div className="flex flex-col gap-0.5">
      <dt className="flex flex-1 items-end text-sm text-muted-foreground">
        {label}
      </dt>
      <dd className="text-2xl font-semibold tabular-nums">{value}</dd>
      <dd className="min-h-4 text-xs text-muted-foreground">{note}</dd>
    </div>
  );
}

function Quality() {
  const t = useTranslations("admin.ai");
  const format = useFormatter();
  const [range, setRange] = useState(defaultRange);
  const inverted = range.from > range.to;
  const quality = useQuery({
    queryKey: ["admin", "ai", "quality", range],
    queryFn: ({ signal }) => getAiQuality(range, signal),
    enabled: !inverted,
    placeholderData: keepPreviousData,
  });
  const q = quality.data;
  const n = (value: number) => format.number(value);
  const localized = useLocalized();
  const categories = useFilterCategories();
  const categoryName = (code: string) => {
    const category = categories.data?.find((item) => item.code === code);
    return category ? localized(category.name_i18n) : null;
  };
  const choices = q ? categoryChoices(q.classifications) : [];

  return (
    <section aria-labelledby="ai-quality" className="grid gap-3">
      <div className="grid gap-1">
        <h2 id="ai-quality" className="text-lg font-semibold">
          {t("qualityTitle")}
        </h2>
        <p className="text-sm text-muted-foreground">{t("qualityIntro")}</p>
      </div>
      <div className="flex flex-wrap items-end gap-3">
        <Field label={t("from")} className="w-44">
          {(control) => (
            <Input
              {...control}
              type="date"
              value={range.from}
              max={range.to}
              onChange={(event) =>
                event.target.value &&
                setRange((current) => ({
                  ...current,
                  from: event.target.value,
                }))
              }
            />
          )}
        </Field>
        <Field
          label={t("to")}
          className="w-44"
          error={inverted ? t("rangeInvalid") : undefined}
        >
          {(control) => (
            <Input
              {...control}
              type="date"
              value={range.to}
              min={range.from}
              onChange={(event) =>
                event.target.value &&
                setRange((current) => ({ ...current, to: event.target.value }))
              }
            />
          )}
        </Field>
      </div>

      {quality.isError ? (
        <QueryError error={quality.error} retry={() => quality.refetch()} />
      ) : !q ? (
        <Skeleton className="h-40 rounded-xl" />
      ) : (
        <div className="grid gap-4" aria-busy={quality.isFetching || undefined}>
          <div className="grid gap-4 md:grid-cols-3">
            <Card className="p-5">
              <h3 className="mb-3 font-semibold">
                {t("classificationsTitle")}
              </h3>
              <dl className="grid grid-cols-2 gap-3">
                <Stat label={t("done")} value={n(q.classifications.done)} />
                <Stat
                  label={t("failed")}
                  value={n(q.classifications.failed)}
                  note={percent(
                    q.classifications.failed,
                    q.classifications.done + q.classifications.failed,
                    format,
                  )}
                />
              </dl>
            </Card>
            <Card className="p-5">
              <h3 className="mb-3 font-semibold">{t("matchingTitle")}</h3>
              <dl className="grid grid-cols-3 gap-3">
                <Stat
                  label={t("autoLinked")}
                  value={n(q.matching.auto_linked)}
                />
                <Stat
                  label={t("sentToReview")}
                  value={n(q.matching.sent_to_review)}
                />
                <Stat label={t("newIssues")} value={n(q.matching.new_issue)} />
              </dl>
            </Card>
            <Card className="p-5">
              <h3 className="mb-3 font-semibold">{t("outcomesTitle")}</h3>
              <dl className="grid grid-cols-2 gap-3">
                <Stat
                  label={t("reviewsLinked")}
                  value={n(q.reviews.linked)}
                  note={t("reviewsNew", { count: q.reviews.new_issue })}
                />
                <Stat
                  label={t("feedbackCorrect")}
                  value={percent(
                    q.auto_link_feedback.correct,
                    q.auto_link_feedback.correct +
                      q.auto_link_feedback.incorrect,
                    format,
                  )}
                  note={t("feedbackCounts", {
                    correct: q.auto_link_feedback.correct,
                    incorrect: q.auto_link_feedback.incorrect,
                  })}
                />
              </dl>
            </Card>
          </div>

          <Table label={t("categoriesTitle")}>
            <caption className="caption-top px-4 pt-3 text-start text-sm font-semibold text-foreground">
              {t("categoriesTitle")}
            </caption>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead>{t("colCategory")}</TableHead>
                <TableHead className="text-end">{t("colAccepted")}</TableHead>
                <TableHead className="text-end">{t("colCorrected")}</TableHead>
                <TableHead className="text-end">{t("colAcceptance")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {choices.length === 0 ? (
                <TableRow className="hover:bg-transparent">
                  <TableCell colSpan={4} className="text-muted-foreground">
                    {t("noChoices")}
                  </TableCell>
                </TableRow>
              ) : (
                choices.map((row) => (
                  <TableRow key={row.code}>
                    <TableCell>
                      {categoryName(row.code) ?? (
                        <span className="font-mono text-sm">{row.code}</span>
                      )}
                    </TableCell>
                    <TableCell className="text-end tabular-nums">
                      {n(row.accepted)}
                    </TableCell>
                    <TableCell className="text-end tabular-nums">
                      {n(row.corrected)}
                    </TableCell>
                    <TableCell className="text-end tabular-nums">
                      {percent(
                        row.accepted,
                        row.accepted + row.corrected,
                        format,
                      )}
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
          <p className="text-xs text-muted-foreground">{t("qualityNote")}</p>
        </div>
      )}
    </section>
  );
}

/**
 * AI governance (PRD §8.6): which models are deployed and for what, and
 * how their suggestions and matches fared over a period. Read-only; the
 * fuller dashboards come in Phase 5.
 */
export function AiScreen() {
  const t = useTranslations("admin.ai");
  return (
    <div className="grid gap-8 motion-safe:animate-rise">
      <PageHeader title={t("title")} description={t("description")} />
      <Models />
      <Quality />
    </div>
  );
}
