"use client";

import { useTranslations } from "next-intl";
import { PageHeader } from "@/components/admin/page-header";
import { getMatchingConfig, updateMatchingConfig } from "@/lib/api";
import {
  DEFAULT_MATCHING_CONFIG,
  fromMatchingForm,
  MATCHING_WEIGHTS,
  validateMatching,
  weightTotal,
} from "@/lib/settings/config";
import { cn } from "@/lib/utils";
import {
  NumberField,
  SettingsFrame,
  SettingsSection,
  useSettingsForm,
} from "./settings-form";

/**
 * How duplicate matching decides (contract D.2, G): whether it may link
 * on its own, how much each signal counts, and the scores that send a
 * report to review or link it automatically. Each setting says in plain
 * words what moving it does.
 */
export function MatchingSettings() {
  const t = useTranslations("admin.settings.matching");
  const tErr = useTranslations("admin.settings.errors");
  const form = useSettingsForm({
    queryKey: ["admin", "matching-config"],
    load: getMatchingConfig,
    save: updateMatchingConfig,
    validate: validateMatching,
    fromValues: fromMatchingForm,
    defaults: DEFAULT_MATCHING_CONFIG,
  });
  const error = (path: string) =>
    form.errors[path] ? tErr(form.errors[path] as "number") : undefined;
  const total = form.values ? weightTotal(form.values, MATCHING_WEIGHTS) : 0;
  const d = DEFAULT_MATCHING_CONFIG;

  return (
    <div className="motion-safe:animate-rise">
      <PageHeader title={t("title")} description={t("description")} />
      <SettingsFrame form={form} savedMessage={t("saved")}>
        <SettingsSection title={t("autoTitle")}>
          <label className="flex cursor-pointer items-start gap-3">
            <input
              type="checkbox"
              checked={form.values?.auto_link_enabled === "true"}
              onChange={(event) =>
                form.setValue("auto_link_enabled", String(event.target.checked))
              }
              disabled={!form.canManage}
              className="mt-1 size-4 accent-primary"
            />
            <span className="grid gap-0.5">
              <span className="font-semibold">{t("autoLabel")}</span>
              <span className="text-sm text-muted-foreground">
                {t("autoHelp")}
              </span>
            </span>
          </label>
        </SettingsSection>

        <SettingsSection
          title={t("thresholdsTitle")}
          description={t("thresholdsIntro")}
        >
          <div className="grid gap-5 sm:grid-cols-2">
            <NumberField
              form={form}
              path="thresholds.auto"
              label={t("auto")}
              help={t("autoThresholdHelp")}
              defaultValue={d.thresholds.auto}
              errorText={error("thresholds.auto")}
            />
            <NumberField
              form={form}
              path="thresholds.review"
              label={t("review")}
              help={t("reviewHelp")}
              defaultValue={d.thresholds.review}
              errorText={error("thresholds.review")}
            />
            <NumberField
              form={form}
              path="thresholds.visual_min"
              label={t("visualMin")}
              help={t("visualMinHelp")}
              defaultValue={d.thresholds.visual_min}
              errorText={error("thresholds.visual_min")}
            />
            <NumberField
              form={form}
              path="fallback_review_threshold"
              label={t("fallback")}
              help={t("fallbackHelp")}
              defaultValue={d.fallback_review_threshold}
              errorText={error("fallback_review_threshold")}
            />
          </div>
        </SettingsSection>

        <SettingsSection
          title={t("weightsTitle")}
          description={t("weightsIntro")}
        >
          <div className="grid gap-5 sm:grid-cols-2">
            {MATCHING_WEIGHTS.map((key) => (
              <NumberField
                key={key}
                form={form}
                path={`weights.${key}`}
                label={t(`weight_${key}`)}
                help={t(`weight_${key}_help`)}
                defaultValue={d.weights[key]}
                errorText={error(`weights.${key}`)}
              />
            ))}
          </div>
          <p
            className={cn(
              "text-sm font-semibold tabular-nums",
              form.errors.weights && "text-destructive-soft-foreground",
            )}
          >
            {t("weightsTotal", { total: total.toFixed(2) })}
            {form.errors.weights ? ` · ${tErr("weightsSumOne")}` : ""}
          </p>
        </SettingsSection>

        <SettingsSection title={t("classificationTitle")}>
          <NumberField
            form={form}
            path="classification_threshold"
            label={t("classification")}
            help={t("classificationHelp")}
            defaultValue={d.classification_threshold}
            errorText={error("classification_threshold")}
          />
        </SettingsSection>
      </SettingsFrame>
    </div>
  );
}
