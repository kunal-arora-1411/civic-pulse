"use client";

import { Hand, Pencil } from "lucide-react";
import { useFormatter, useTranslations } from "next-intl";
import {
  PriorityBadge,
  SeverityBadge,
} from "@/components/issues/priority-badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import type { IssueDetail, PriorityFactor } from "@/lib/api";
import { unit } from "@/lib/issues/signals";

/**
 * Turns a factor's `explanation_key` (e.g. `priority.reporters`) into a
 * sentence in the user's language, using the factor's value. A key the
 * client doesn't know yet falls back to the factor's name, so a new
 * backend factor still shows up rather than breaking the card.
 */
export function useFactorText() {
  const t = useTranslations("priorityFactors");
  const tLevel = useTranslations("severity.level");
  return (factor: PriorityFactor): string => {
    const key = factor.explanation_key.replace(/^priority\./, "");
    const value = factor.value;
    const count = typeof value === "number" ? Math.round(value) : 0;
    switch (key) {
      case "severity":
        return typeof value === "string" &&
          ["low", "medium", "high", "critical"].includes(value)
          ? t("severity", {
              level: tLevel(value as "low" | "medium" | "high" | "critical"),
            })
          : t("severityUnknown");
      case "reporters":
        return t("reporters", { count });
      case "age":
        return t("age", { count });
      case "recurrence":
        return t("recurrence", { count });
      case "near_places":
        return value === true || count > 0 ? t("nearPlaces") : t("noPlaces");
      default: {
        const words = factor.factor.replace(/[_-]+/g, " ");
        return words.charAt(0).toUpperCase() + words.slice(1);
      }
    }
  };
}

export function PriorityCard({
  issue,
  canSetPriority,
  canSetSeverity,
  onOverridePriority,
  onChangeSeverity,
}: {
  issue: IssueDetail;
  canSetPriority: boolean;
  canSetSeverity: boolean;
  onOverridePriority: () => void;
  onChangeSeverity: () => void;
}) {
  const t = useTranslations("admin.issueDetail.priority");
  const tBand = useTranslations("priority.band");
  const format = useFormatter();
  const factorText = useFactorText();
  const { priority, severity } = issue;
  const points = (value: number) =>
    format.number(value, {
      minimumFractionDigits: 1,
      maximumFractionDigits: 1,
    });

  return (
    <Card className="grid gap-4 p-5">
      <div className="flex items-start justify-between gap-3">
        <h2 className="font-semibold">{t("heading")}</h2>
        {canSetPriority && priority ? (
          <Button variant="outline" size="sm" onClick={onOverridePriority}>
            <Hand aria-hidden="true" />
            {t("override")}
          </Button>
        ) : null}
      </div>

      {priority ? (
        <div className="grid gap-3">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <PriorityBadge band={priority.band} className="px-3 py-1 text-sm" />
            <p className="text-sm tabular-nums text-muted-foreground">
              {t("score", { score: points(priority.score) })}
            </p>
          </div>
          {priority.overridden ? (
            <div className="rounded-lg border border-dashed border-warning-soft-foreground/40 bg-warning-soft/50 p-3 text-sm">
              <p className="flex items-center gap-1.5 font-semibold">
                <Hand aria-hidden="true" className="size-4" />
                {t("overridden", {
                  band: tBand(priority.band),
                  computed: tBand(priority.computed_band),
                })}
              </p>
              {priority.override_reason ? (
                <p className="mt-1 whitespace-pre-line">
                  <span className="text-muted-foreground">
                    {t("reasonLabel")}:{" "}
                  </span>
                  {priority.override_reason}
                </p>
              ) : null}
            </div>
          ) : null}

          {priority.factors?.length ? (
            <div className="grid gap-2">
              <h3 className="text-sm font-semibold">{t("factorsHeading")}</h3>
              <ul className="grid gap-2.5">
                {priority.factors.map((factor) => (
                  <li key={factor.factor} className="grid gap-1">
                    <div className="flex items-baseline justify-between gap-3 text-sm">
                      <span>{factorText(factor)}</span>
                      <span className="shrink-0 font-mono tabular-nums">
                        {t("points", { points: points(factor.points) })}
                      </span>
                    </div>
                    <div
                      aria-hidden="true"
                      className="h-1.5 overflow-hidden rounded-full bg-muted"
                    >
                      <div
                        className="h-full rounded-full bg-foreground/70"
                        style={{ width: `${unit(factor.normalized) * 100}%` }}
                      />
                    </div>
                  </li>
                ))}
              </ul>
              <p className="text-xs text-muted-foreground">
                {t("factorsHelp")}
              </p>
            </div>
          ) : null}
        </div>
      ) : (
        <p className="text-sm text-muted-foreground">{t("notScored")}</p>
      )}

      <div className="grid gap-2 border-t border-border pt-4">
        <div className="flex items-start justify-between gap-3">
          <h3 className="text-sm font-semibold">{t("severityHeading")}</h3>
          {canSetSeverity ? (
            <Button variant="ghost" size="sm" onClick={onChangeSeverity}>
              <Pencil aria-hidden="true" />
              {t("changeSeverity")}
            </Button>
          ) : null}
        </div>
        {severity ? (
          <>
            <div className="flex flex-wrap items-center gap-2">
              <SeverityBadge
                level={severity.level}
                overridden={severity.source === "override"}
              />
              <span className="text-sm text-muted-foreground">
                {severity.source === "override"
                  ? t("severityOverride")
                  : t("severityRules")}
              </span>
            </div>
            {severity.source === "override" && severity.reason ? (
              <p className="text-sm whitespace-pre-line">
                <span className="text-muted-foreground">
                  {t("reasonLabel")}:{" "}
                </span>
                {severity.reason}
              </p>
            ) : null}
          </>
        ) : (
          <p className="text-sm text-muted-foreground">{t("notScored")}</p>
        )}
      </div>
    </Card>
  );
}
