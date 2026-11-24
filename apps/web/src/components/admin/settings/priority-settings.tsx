"use client";

import { useFormatter, useTranslations } from "next-intl";
import { useId, useState } from "react";
import { PageHeader } from "@/components/admin/page-header";
import { PriorityBadge } from "@/components/issues/priority-badge";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import {
  getPriorityConfig,
  SEVERITY_LEVELS,
  type SeverityLevel,
  updatePriorityConfig,
} from "@/lib/api";
import { unit } from "@/lib/issues/signals";
import {
  computePriority,
  DEFAULT_PRIORITY_CONFIG,
  type ExampleIssue,
  type FormValues,
  fromPriorityForm,
  PRIORITY_WEIGHTS,
  validatePriority,
  weightTotal,
} from "@/lib/settings/config";
import { cn } from "@/lib/utils";
import {
  NumberField,
  SettingsFrame,
  SettingsSection,
  useSettingsForm,
} from "./settings-form";

const EXAMPLE: ExampleIssue = {
  severity: "high",
  uniqueReporters: 3,
  ageDays: 10,
  similarNearby: 1,
  nearPlace: true,
};

/**
 * Scores an example issue with the settings as typed, so the effect of a
 * change is visible before it's saved. Uses the same formula as the
 * backend (contract F).
 */
function Preview({ values }: { values: FormValues }) {
  const t = useTranslations("admin.settings.priority");
  const tLevel = useTranslations("severity.level");
  const format = useFormatter();
  const ids = { severity: useId(), place: useId() };
  const [example, setExample] = useState(EXAMPLE);
  const valid = Object.keys(validatePriority(values)).length === 0;
  const result = valid
    ? computePriority(fromPriorityForm(values), example)
    : null;
  const update = (patch: Partial<ExampleIssue>) =>
    setExample((current) => ({ ...current, ...patch }));
  const count = (value: string) => Math.max(0, Math.floor(Number(value) || 0));
  const points = (value: number) =>
    format.number(value, {
      minimumFractionDigits: 1,
      maximumFractionDigits: 1,
    });

  return (
    <SettingsSection
      title={t("previewTitle")}
      description={t("previewIntro")}
      className="lg:sticky lg:top-20"
    >
      <div className="grid grid-cols-2 gap-3">
        <div className="col-span-2 grid gap-1.5">
          <label htmlFor={ids.severity} className="text-sm font-semibold">
            {t("exampleSeverity")}
          </label>
          <Select
            id={ids.severity}
            value={example.severity}
            onChange={(event) =>
              update({ severity: event.target.value as SeverityLevel })
            }
          >
            {SEVERITY_LEVELS.map((level) => (
              <option key={level} value={level}>
                {tLevel(level)}
              </option>
            ))}
          </Select>
        </div>
        {(
          [
            ["uniqueReporters", t("exampleReporters")],
            ["ageDays", t("exampleAge")],
            ["similarNearby", t("exampleSimilar")],
          ] as const
        ).map(([key, label]) => (
          <Field key={key} label={label}>
            {(control) => (
              <Input
                {...control}
                type="number"
                min={0}
                step={1}
                value={String(example[key])}
                onChange={(event) =>
                  update({ [key]: count(event.target.value) })
                }
                className="tabular-nums"
              />
            )}
          </Field>
        ))}
        <label className="col-span-2 flex items-center gap-2 text-sm">
          <input
            id={ids.place}
            type="checkbox"
            checked={example.nearPlace}
            onChange={(event) => update({ nearPlace: event.target.checked })}
            className="size-4 accent-primary"
          />
          {t("examplePlace")}
        </label>
      </div>

      <output className="grid gap-3 rounded-lg border border-border bg-muted/50 p-4">
        {result ? (
          <>
            <span className="flex flex-wrap items-center gap-3">
              <PriorityBadge band={result.band} className="px-3 py-1 text-sm" />
              <span className="text-sm tabular-nums">
                {t("previewScore", { score: points(result.score) })}
              </span>
            </span>
            <span className="grid gap-2">
              {result.factors.map((factor) => (
                <span key={factor.factor} className="grid gap-1">
                  <span className="flex justify-between gap-3 text-sm">
                    <span>{t(`factor_${factor.factor}`)}</span>
                    <span className="font-mono tabular-nums">
                      +{points(factor.points)}
                    </span>
                  </span>
                  <span
                    aria-hidden="true"
                    className="block h-1.5 overflow-hidden rounded-full bg-muted"
                  >
                    <span
                      className="block h-full rounded-full bg-foreground/70"
                      style={{ width: `${unit(factor.normalized) * 100}%` }}
                    />
                  </span>
                </span>
              ))}
            </span>
          </>
        ) : (
          <span className="text-sm text-muted-foreground">
            {t("previewInvalid")}
          </span>
        )}
      </output>
    </SettingsSection>
  );
}

/**
 * Priority rules (contract F, FR-039 to FR-041): how much each factor
 * counts, how severity levels and counts turn into points, and where the
 * bands start, with a live preview alongside.
 */
export function PrioritySettings() {
  const t = useTranslations("admin.settings.priority");
  const tErr = useTranslations("admin.settings.errors");
  const tLevel = useTranslations("severity.level");
  const tBand = useTranslations("priority.band");
  const form = useSettingsForm({
    queryKey: ["admin", "priority-config"],
    load: getPriorityConfig,
    save: updatePriorityConfig,
    validate: validatePriority,
    fromValues: fromPriorityForm,
    defaults: DEFAULT_PRIORITY_CONFIG,
  });
  const error = (path: string) =>
    form.errors[path] ? tErr(form.errors[path] as "number") : undefined;
  const total = form.values ? weightTotal(form.values, PRIORITY_WEIGHTS) : 0;
  const d = DEFAULT_PRIORITY_CONFIG;

  return (
    <div className="motion-safe:animate-rise">
      <PageHeader
        section="priority"
        title={t("title")}
        description={t("description")}
      />
      <SettingsFrame form={form} savedMessage={t("saved")}>
        <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_20rem] lg:items-start">
          <div className="grid gap-6">
            <SettingsSection
              title={t("weightsTitle")}
              description={t("weightsIntro")}
            >
              <div className="grid gap-5 sm:grid-cols-2">
                {PRIORITY_WEIGHTS.map((key) => (
                  <NumberField
                    key={key}
                    form={form}
                    path={`weights.${key}`}
                    label={t(`factor_${key}`)}
                    help={t(`weight_${key}_help`)}
                    defaultValue={d.weights[key]}
                    step="1"
                    suffix={t("pointsSuffix")}
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
                {t("weightsTotal", { total: Math.round(total * 10) / 10 })}
                {form.errors.weights ? ` · ${tErr("weightsSumHundred")}` : ""}
              </p>
            </SettingsSection>

            <SettingsSection
              title={t("severityTitle")}
              description={t("severityIntro")}
            >
              <div className="grid gap-5 sm:grid-cols-2">
                {SEVERITY_LEVELS.map((level) => (
                  <NumberField
                    key={level}
                    form={form}
                    path={`severity_points.${level}`}
                    label={tLevel(level)}
                    defaultValue={d.severity_points[level]}
                    errorText={error(`severity_points.${level}`)}
                  />
                ))}
              </div>
            </SettingsSection>

            <SettingsSection
              title={t("scalingTitle")}
              description={t("scalingIntro")}
            >
              <div className="grid gap-5 sm:grid-cols-2">
                <NumberField
                  form={form}
                  path="reporters_saturation"
                  label={t("reportersSaturation")}
                  help={t("reportersSaturationHelp")}
                  defaultValue={d.reporters_saturation}
                  step="1"
                  errorText={error("reporters_saturation")}
                />
                <NumberField
                  form={form}
                  path="age_saturation_days"
                  label={t("ageSaturation")}
                  help={t("ageSaturationHelp")}
                  defaultValue={d.age_saturation_days}
                  step="1"
                  suffix={t("daysSuffix")}
                  errorText={error("age_saturation_days")}
                />
                <NumberField
                  form={form}
                  path="recurrence.radius_m"
                  label={t("recurrenceRadius")}
                  help={t("recurrenceRadiusHelp")}
                  defaultValue={d.recurrence.radius_m}
                  step="1"
                  suffix="m"
                  errorText={error("recurrence.radius_m")}
                />
                <NumberField
                  form={form}
                  path="recurrence.lookback_days"
                  label={t("recurrenceLookback")}
                  help={t("recurrenceLookbackHelp")}
                  defaultValue={d.recurrence.lookback_days}
                  step="1"
                  suffix={t("daysSuffix")}
                  errorText={error("recurrence.lookback_days")}
                />
                <NumberField
                  form={form}
                  path="recurrence.saturation"
                  label={t("recurrenceSaturation")}
                  help={t("recurrenceSaturationHelp")}
                  defaultValue={d.recurrence.saturation}
                  step="1"
                  errorText={error("recurrence.saturation")}
                />
              </div>
            </SettingsSection>

            <SettingsSection
              title={t("bandsTitle")}
              description={t("bandsIntro")}
            >
              <div className="grid gap-5 sm:grid-cols-3">
                {(["critical", "high", "medium"] as const).map((band) => (
                  <NumberField
                    key={band}
                    form={form}
                    path={`bands.${band}`}
                    label={t("bandFrom", { band: tBand(band) })}
                    defaultValue={d.bands[band]}
                    step="1"
                    errorText={error(`bands.${band}`)}
                  />
                ))}
              </div>
              <p className="text-sm text-muted-foreground">
                {t("bandsLow", { band: tBand("low") })}
              </p>
            </SettingsSection>
          </div>
          {form.values ? <Preview values={form.values} /> : null}
        </div>
      </SettingsFrame>
    </div>
  );
}
