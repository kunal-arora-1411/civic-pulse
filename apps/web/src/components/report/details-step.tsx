"use client";

import { Check, ImagePlus } from "lucide-react";
import { useTranslations } from "next-intl";
import { useId } from "react";
import { CategoryIcon } from "@/components/issues/category-icon";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Field } from "@/components/ui/field";
import { Input, inputClasses } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { useLocalized } from "@/hooks/use-reference-data";
import type { Category, CategoryField } from "@/lib/api";
import type { ReportDraft } from "@/lib/report/draft";
import {
  DESCRIPTION_MAX,
  DESCRIPTION_MIN_WITHOUT_PHOTO,
  type DetailsIssues,
  type FieldIssue,
} from "@/lib/report/validation";
import { cn } from "@/lib/utils";

function DetailField({
  field,
  value,
  issue,
  onChange,
}: {
  field: CategoryField;
  value: string | boolean | undefined;
  issue: FieldIssue | undefined;
  onChange: (value: string | boolean | undefined) => void;
}) {
  const t = useTranslations("report.details");
  const localized = useLocalized();
  const label = (
    <>
      {localized(field.label_i18n)}
      {field.required ? null : (
        <span className="ms-1 font-normal text-muted-foreground">
          ({t("optional")})
        </span>
      )}
    </>
  );
  const error = issue ? t(`field_${issue}`) : undefined;
  const groupId = useId();

  if (field.type === "boolean") {
    return (
      <fieldset
        className="grid gap-2"
        aria-describedby={error ? `${groupId}-error` : undefined}
      >
        <legend className="mb-1.5 text-sm font-semibold">
          {label}
          {field.required ? (
            <span aria-hidden="true" className="ms-0.5 text-destructive">
              *
            </span>
          ) : null}
        </legend>
        <div className="flex gap-2">
          {[true, false].map((option) => (
            <label
              key={String(option)}
              className={cn(
                "flex h-11 flex-1 cursor-pointer items-center justify-center gap-2 rounded-lg border px-4 font-semibold has-checked:border-primary has-checked:bg-primary-soft has-checked:text-primary-soft-foreground has-focus-visible:ring-3 has-focus-visible:ring-ring/30",
                issue ? "border-destructive" : "border-input",
              )}
            >
              <input
                type="radio"
                name={`${groupId}-${field.key}`}
                className="sr-only"
                checked={value === option}
                onChange={() => onChange(option)}
                required={field.required}
              />
              {option ? t("yes") : t("no")}
            </label>
          ))}
        </div>
        {error ? (
          <p
            id={`${groupId}-error`}
            className="text-sm font-medium text-destructive-soft-foreground"
          >
            {error}
          </p>
        ) : null}
      </fieldset>
    );
  }

  return (
    <Field label={label} required={field.required} error={error}>
      {(control) =>
        field.type === "select" ? (
          <Select
            {...control}
            value={typeof value === "string" ? value : ""}
            onChange={(event) => onChange(event.target.value || undefined)}
          >
            <option value="">{t("selectPlaceholder")}</option>
            {(field.options ?? []).map((option) => (
              <option key={option.value} value={option.value}>
                {localized(option.label_i18n)}
              </option>
            ))}
          </Select>
        ) : (
          <Input
            {...control}
            type="text"
            inputMode={field.type === "number" ? "decimal" : undefined}
            value={typeof value === "string" ? value : ""}
            onChange={(event) => onChange(event.target.value)}
            maxLength={field.type === "number" ? 20 : 200}
          />
        )
      }
    </Field>
  );
}

export function DetailsStep({
  categories,
  categoriesState,
  draft,
  photoCount,
  issues,
  onCategory,
  onDetail,
  onDescription,
  onEditPhotos,
  onRetryCategories,
}: {
  categories: Category[];
  categoriesState: "pending" | "error" | "success";
  draft: ReportDraft;
  photoCount: number;
  /** Null until the citizen has tried to continue. */
  issues: DetailsIssues | null;
  onCategory: (category: Category) => void;
  onDetail: (key: string, value: string | boolean | undefined) => void;
  onDescription: (value: string) => void;
  onEditPhotos: () => void;
  onRetryCategories: () => void;
}) {
  const t = useTranslations("report.details");
  const localized = useLocalized();
  const ids = { legend: useId(), categoryError: useId() };
  const selected = categories.find((c) => c.id === draft.categoryId) ?? null;
  const length = draft.description.length;
  const nearLimit = length > DESCRIPTION_MAX - 200;

  return (
    <div className="grid gap-8">
      <fieldset
        className="grid gap-3"
        aria-describedby={issues?.category ? ids.categoryError : undefined}
      >
        <legend id={ids.legend} className="mb-1 font-semibold">
          {t("categoryLegend")}
        </legend>
        {categoriesState === "pending" ? (
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
            <output className="sr-only">{t("loadingCategories")}</output>
            {Array.from({ length: 6 }, (_, index) => (
              // biome-ignore lint/suspicious/noArrayIndexKey: static placeholders
              <Skeleton key={index} className="h-28 rounded-xl" />
            ))}
          </div>
        ) : categoriesState === "error" ? (
          <Alert variant="destructive" title={t("categoriesError")}>
            <Button
              variant="outline"
              size="sm"
              className="mt-2"
              onClick={onRetryCategories}
            >
              {t("retry")}
            </Button>
          </Alert>
        ) : (
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
            {categories.map((category) => {
              const checked = category.id === draft.categoryId;
              return (
                <label
                  key={category.id}
                  className={cn(
                    "relative flex min-h-28 cursor-pointer flex-col items-start justify-between gap-3 rounded-xl border-2 bg-card p-4 transition-[border-color,box-shadow,background-color]",
                    "hover:border-primary/50 has-focus-visible:ring-3 has-focus-visible:ring-ring/40",
                    checked
                      ? "border-primary bg-primary-soft shadow-card"
                      : "border-border",
                    issues?.category && "border-destructive/60",
                  )}
                >
                  <input
                    type="radio"
                    name="category"
                    value={category.id}
                    checked={checked}
                    onChange={() => onCategory(category)}
                    className="sr-only"
                  />
                  <span
                    className={cn(
                      "grid size-11 place-items-center rounded-xl",
                      checked
                        ? "bg-primary text-primary-foreground"
                        : "bg-secondary text-secondary-foreground",
                    )}
                  >
                    <CategoryIcon icon={category.icon} className="size-6" />
                  </span>
                  <span className="text-[0.9375rem] leading-snug font-semibold">
                    {localized(category.name_i18n)}
                  </span>
                  {checked ? (
                    <Check
                      aria-hidden="true"
                      className="absolute end-3 top-3 size-5 text-primary"
                    />
                  ) : null}
                </label>
              );
            })}
          </div>
        )}
        {issues?.category ? (
          <p
            id={ids.categoryError}
            role="alert"
            className="text-sm font-medium text-destructive-soft-foreground"
          >
            {t("categoryRequired")}
          </p>
        ) : null}
      </fieldset>

      {selected && issues?.photos ? (
        <Alert variant="destructive" live="assertive">
          <p>
            {issues.photos === "too_few"
              ? t("photosTooFew", {
                  category: localized(selected.name_i18n),
                  min: selected.evidence.min_photos,
                  count: photoCount,
                })
              : t("photosTooMany", {
                  category: localized(selected.name_i18n),
                  max: selected.evidence.max_photos,
                  count: photoCount,
                })}
          </p>
          <Button
            variant="outline"
            size="sm"
            className="mt-2"
            onClick={onEditPhotos}
          >
            <ImagePlus aria-hidden="true" />
            {t("editPhotos")}
          </Button>
        </Alert>
      ) : null}

      {selected && selected.fields.length > 0 ? (
        <section className="grid gap-4" aria-labelledby={`${ids.legend}-f`}>
          <h3 id={`${ids.legend}-f`} className="font-semibold">
            {t("fieldsTitle")}
          </h3>
          {selected.fields.map((field) => (
            <DetailField
              key={field.key}
              field={field}
              value={draft.details[field.key]}
              issue={issues?.fields[field.key]}
              onChange={(value) => onDetail(field.key, value)}
            />
          ))}
        </section>
      ) : null}

      <Field
        label={t("descriptionLabel")}
        description={t("descriptionHint")}
        error={
          issues?.description === "too_long"
            ? t("descriptionTooLong", { max: DESCRIPTION_MAX })
            : issues?.description === "too_short"
              ? t("descriptionTooShort", { min: DESCRIPTION_MIN_WITHOUT_PHOTO })
              : undefined
        }
      >
        {(control) => (
          <div className="grid gap-1">
            <textarea
              {...control}
              value={draft.description}
              onChange={(event) => onDescription(event.target.value)}
              rows={4}
              maxLength={DESCRIPTION_MAX + 200}
              className={cn(
                inputClasses,
                "h-auto min-h-28 py-2 leading-relaxed",
              )}
            />
            <p
              className={cn(
                "justify-self-end text-xs tabular-nums",
                length > DESCRIPTION_MAX
                  ? "font-semibold text-destructive-soft-foreground"
                  : "text-muted-foreground",
              )}
              aria-live={nearLimit ? "polite" : "off"}
            >
              <span className="sr-only">{t("descriptionCountLabel")} </span>
              {t("descriptionCount", { count: length, max: DESCRIPTION_MAX })}
            </p>
          </div>
        )}
      </Field>
    </div>
  );
}
