"use client";

import { RotateCcw } from "lucide-react";
import { useTranslations } from "next-intl";
import {
  useFilterCategories,
  useWards,
} from "@/components/admin/issues/issue-filters";
import { Button } from "@/components/ui/button";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { MultiSelect } from "@/components/ui/multi-select";
import { Select } from "@/components/ui/select";
import { useLocalized } from "@/hooks/use-reference-data";
import {
  type AnalyticsFilters,
  activeFilterCount,
  DEFAULT_FILTERS,
  isRangeInvalid,
  RANGE_PRESETS,
  type RangePreset,
  resolvePeriod,
} from "@/lib/analytics/filters";
import { ISSUE_STATUSES, type IssueStatus } from "@/lib/api";

/** One row of filters above every chart; each change is a URL change. */
export function AnalyticsFiltersBar({
  filters,
  onChange,
}: {
  filters: AnalyticsFilters;
  onChange: (changes: Partial<AnalyticsFilters>) => void;
}) {
  const t = useTranslations("admin.analytics.filters");
  const tStatus = useTranslations("issueStatus");
  const localized = useLocalized();
  const categories = useFilterCategories();
  const wards = useWards();
  const invalid = isRangeInvalid(filters);

  const choosePreset = (range: RangePreset) => {
    if (range === "custom") {
      // Start the custom range from what was on screen.
      const period = resolvePeriod(filters);
      onChange({ range, from: period.from, to: period.to });
    } else {
      onChange({ range, from: "", to: "" });
    }
  };

  return (
    <search
      aria-label={t("label")}
      className="mb-6 flex flex-wrap items-end gap-3 rounded-xl border border-border bg-card p-4 shadow-card"
    >
      <Field label={t("period")} className="w-full sm:w-48">
        {(control) => (
          <Select
            {...control}
            value={filters.range}
            onChange={(event) =>
              choosePreset(event.target.value as RangePreset)
            }
          >
            {RANGE_PRESETS.map((range) => (
              <option key={range} value={range}>
                {t(`presets.${range}`)}
              </option>
            ))}
          </Select>
        )}
      </Field>
      {filters.range === "custom" ? (
        <>
          <Field label={t("from")} className="w-[calc(50%-0.375rem)] sm:w-40">
            {(control) => (
              <Input
                {...control}
                type="date"
                value={filters.from}
                max={filters.to || undefined}
                onChange={(event) => onChange({ from: event.target.value })}
              />
            )}
          </Field>
          <Field
            label={t("to")}
            className="w-[calc(50%-0.375rem)] sm:w-40"
            error={invalid ? t("rangeInvalid") : undefined}
          >
            {(control) => (
              <Input
                {...control}
                type="date"
                value={filters.to}
                min={filters.from || undefined}
                onChange={(event) => onChange({ to: event.target.value })}
              />
            )}
          </Field>
        </>
      ) : null}
      <Field label={t("category")} className="w-full sm:w-52">
        {(control) => (
          <Select
            {...control}
            value={filters.category}
            onChange={(event) => onChange({ category: event.target.value })}
          >
            <option value="">{t("allCategories")}</option>
            {(categories.data ?? []).map((category) => (
              <option key={category.id} value={category.id}>
                {localized(category.name_i18n)}
              </option>
            ))}
          </Select>
        )}
      </Field>
      <Field label={t("ward")} className="w-full sm:w-52">
        {(control) => (
          <Select
            {...control}
            value={filters.ward}
            onChange={(event) => onChange({ ward: event.target.value })}
          >
            <option value="">{t("allWards")}</option>
            {(wards.data ?? []).map((ward) => (
              <option key={ward.id} value={ward.id}>
                {ward.name}
              </option>
            ))}
          </Select>
        )}
      </Field>
      <MultiSelect
        className="w-full sm:w-52"
        label={t("status")}
        allLabel={t("allStatuses")}
        selectedLabel={(count) => t("selected", { count })}
        value={filters.status}
        onChange={(status) => onChange({ status: status as IssueStatus[] })}
        options={ISSUE_STATUSES.map((status) => ({
          value: status,
          label: tStatus(status),
        }))}
      />
      {activeFilterCount(filters) > 0 ? (
        <Button
          variant="ghost"
          onClick={() =>
            onChange({ ...DEFAULT_FILTERS, interval: filters.interval })
          }
        >
          <RotateCcw aria-hidden="true" />
          {t("reset")}
        </Button>
      ) : null}
    </search>
  );
}
