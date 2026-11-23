"use client";

import { ImageIcon, LogIn, Pencil, RotateCcw, Send } from "lucide-react";
import { useTranslations } from "next-intl";
import type { ReactNode } from "react";
import { CategoryIcon } from "@/components/issues/category-icon";
import { PinMap } from "@/components/map/lazy-maps";
import { Alert } from "@/components/ui/alert";
import { Button, buttonVariants } from "@/components/ui/button";
import { useLocalized } from "@/hooks/use-reference-data";
import { Link } from "@/i18n/navigation";
import type { Category } from "@/lib/api";
import type { ReportDraft, ReportStep } from "@/lib/report/draft";
import type { SubmitErrorInfo } from "@/lib/report/submit-errors";
import type { UploadState } from "@/lib/report/validation";
import type { LivePhoto } from "./use-photo-uploads";

function Section({
  title,
  step,
  onEdit,
  children,
}: {
  title: string;
  step: ReportStep;
  onEdit: (step: ReportStep) => void;
  children: ReactNode;
}) {
  const t = useTranslations("report.review");
  return (
    <section className="grid gap-3 border-b border-border py-5 first:pt-0 last:border-0">
      <div className="flex items-center justify-between gap-3">
        <h3 className="font-semibold">{title}</h3>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => onEdit(step)}
          aria-label={t("changeSection", { section: title })}
        >
          <Pencil aria-hidden="true" />
          {t("change")}
        </Button>
      </div>
      {children}
    </section>
  );
}

function formatDetail(
  value: string | boolean,
  yes: string,
  no: string,
): string {
  if (typeof value === "boolean") return value ? yes : no;
  return value;
}

export function ReviewStep({
  draft,
  photos,
  category,
  uploads,
  submitting,
  error,
  onEdit,
  onSubmit,
  onSubmitAsNew,
}: {
  draft: ReportDraft;
  photos: LivePhoto[];
  category: Category | null;
  uploads: UploadState;
  submitting: boolean;
  error: SubmitErrorInfo | null;
  onEdit: (step: ReportStep) => void;
  onSubmit: () => void;
  onSubmitAsNew: () => void;
}) {
  const t = useTranslations("report");
  const localized = useLocalized();
  const location = draft.location;
  const detailEntries = (category?.fields ?? []).flatMap((field) => {
    const value = draft.details[field.key];
    if (value === undefined || value === "") return [];
    const option = field.options?.find((o) => o.value === value);
    return [
      {
        key: field.key,
        label: localized(field.label_i18n),
        value: option
          ? localized(option.label_i18n)
          : formatDetail(value, t("details.yes"), t("details.no")),
      },
    ];
  });

  return (
    <div className="grid gap-6">
      <p className="text-muted-foreground">{t("review.hint")}</p>

      <div className="rounded-xl border border-border bg-card p-5 shadow-card">
        <Section title={t("review.photos")} step={1} onEdit={onEdit}>
          <ul className="flex flex-wrap gap-2">
            {photos.map((photo, index) => (
              <li
                key={photo.id}
                className="size-16 overflow-hidden rounded-lg border border-border bg-muted"
              >
                {photo.previewUrl ? (
                  // biome-ignore lint/performance/noImgElement: local object/data URL
                  <img
                    src={photo.previewUrl}
                    alt={t("photos.photoAlt", { number: index + 1 })}
                    className="size-full object-cover"
                  />
                ) : (
                  <ImageIcon
                    aria-label={t("photos.photoAlt", { number: index + 1 })}
                    className="m-auto mt-4 size-6 text-muted-foreground"
                  />
                )}
              </li>
            ))}
          </ul>
        </Section>

        <Section title={t("review.location")} step={2} onEdit={onEdit}>
          {location ? (
            <div className="grid gap-3 sm:grid-cols-[10rem_1fr]">
              <div className="h-32 overflow-hidden rounded-lg border border-border">
                <PinMap
                  center={location}
                  zoom={16}
                  pin={location}
                  static
                  label={t("review.mapLabel")}
                  pinLabel={t("location.pinLabel")}
                />
              </div>
              <dl className="grid content-start gap-1 text-sm">
                <dt className="sr-only">{t("location.address")}</dt>
                <dd className="font-medium">
                  {draft.addressText || t("location.noAddressShort")}
                </dd>
                {draft.wardName ? (
                  <>
                    <dt className="sr-only">{t("location.ward")}</dt>
                    <dd className="text-muted-foreground">{draft.wardName}</dd>
                  </>
                ) : null}
                <dt className="sr-only">{t("review.source")}</dt>
                <dd className="text-muted-foreground">
                  {t(`location.source.${location.source}`)}
                  {location.accuracyM
                    ? ` · ${t("review.accuracy", { meters: location.accuracyM })}`
                    : ""}
                </dd>
              </dl>
            </div>
          ) : null}
        </Section>

        <Section title={t("review.category")} step={3} onEdit={onEdit}>
          {category ? (
            <div className="grid gap-3">
              <p className="flex items-center gap-2 font-medium">
                <CategoryIcon
                  icon={category.icon}
                  className="size-5 text-primary"
                />
                {localized(category.name_i18n)}
              </p>
              {detailEntries.length > 0 ? (
                <dl className="grid gap-x-4 gap-y-1 text-sm sm:grid-cols-[auto_1fr]">
                  {detailEntries.map((entry) => (
                    <div key={entry.key} className="contents">
                      <dt className="text-muted-foreground">{entry.label}</dt>
                      <dd className="font-medium">{entry.value}</dd>
                    </div>
                  ))}
                </dl>
              ) : null}
              <div className="grid gap-1 text-sm">
                <p className="text-muted-foreground">
                  {t("review.description")}
                </p>
                <p className="whitespace-pre-line">
                  {draft.description.trim() || t("review.noDescription")}
                </p>
              </div>
            </div>
          ) : null}
        </Section>
      </div>

      {uploads === "uploading" ? (
        <Alert variant="info" live="polite">
          {t("review.waitingUploads")}
        </Alert>
      ) : uploads === "failed" ? (
        <Alert variant="destructive" live="assertive">
          <p>{t("review.uploadsFailed")}</p>
          <Button
            variant="outline"
            size="sm"
            className="mt-2"
            onClick={() => onEdit(1)}
          >
            {t("review.goToPhotos")}
          </Button>
        </Alert>
      ) : null}

      {error ? (
        <Alert
          variant="destructive"
          live="assertive"
          title={t("review.errorTitle")}
        >
          <p>
            {error.key === "rate_limited" && error.retryAfter
              ? t("submitErrors.rate_limited_wait", {
                  seconds: error.retryAfter,
                })
              : t(`submitErrors.${error.key}`)}
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            {error.retryable ? (
              <Button
                variant="outline"
                size="sm"
                onClick={onSubmit}
                loading={submitting}
              >
                <RotateCcw aria-hidden="true" />
                {t("review.tryAgain")}
              </Button>
            ) : null}
            {error.step ? (
              <Button
                variant="outline"
                size="sm"
                onClick={() => onEdit(error.step as ReportStep)}
              >
                <Pencil aria-hidden="true" />
                {t("review.fixStep", {
                  step: t(
                    `steps.${(["photos", "location", "details", "review"] as const)[error.step - 1]}`,
                  ),
                })}
              </Button>
            ) : null}
            {error.key === "idempotency_key_reused" ? (
              <>
                <Link
                  href="/reports"
                  className={buttonVariants({ variant: "outline", size: "sm" })}
                >
                  {t("review.checkMyReports")}
                </Link>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={onSubmitAsNew}
                  loading={submitting}
                >
                  <Send aria-hidden="true" />
                  {t("review.sendAsNew")}
                </Button>
              </>
            ) : null}
            {error.key === "signed_out" ? (
              <Link
                href={`/login?next=${encodeURIComponent("/report")}`}
                className={buttonVariants({ variant: "outline", size: "sm" })}
              >
                <LogIn aria-hidden="true" />
                {t("review.signIn")}
              </Link>
            ) : null}
          </div>
        </Alert>
      ) : null}
    </div>
  );
}
