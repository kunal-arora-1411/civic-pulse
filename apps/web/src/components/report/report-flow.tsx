"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, ArrowRight, RotateCcw, Send } from "lucide-react";
import { useTranslations } from "next-intl";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { useDebouncedValue } from "@/hooks/use-debounced-value";
import {
  useCategories,
  useTenant,
  useTenantMapView,
} from "@/hooks/use-reference-data";
import { createReport, type Report, reverseGeocode } from "@/lib/api";
import {
  type DraftLocation,
  type DraftPhoto,
  hasProgress,
  loadDraft,
  newDraft,
  type ReportDraft,
  type ReportStep,
  randomId,
  saveDraft,
} from "@/lib/report/draft";
import {
  type SubmitErrorInfo,
  submitErrorInfo,
} from "@/lib/report/submit-errors";
import {
  buildReportBody,
  type GeoCheck,
  hasDetailsIssues,
  photoLimits,
  uploadState,
  validateDetails,
  validateLocation,
  validatePhotoCount,
} from "@/lib/report/validation";
import { DetailsStep } from "./details-step";
import { LocationStep } from "./location-step";
import { PhotosStep } from "./photos-step";
import { ReportDone } from "./report-done";
import { ReportProgress, STEP_KEYS } from "./report-progress";
import { ReviewStep } from "./review-step";
import { usePhotoUploads } from "./use-photo-uploads";

function stepFromUrl(): ReportStep | null {
  const value = Number(new URLSearchParams(window.location.search).get("step"));
  return value >= 1 && value <= 4 ? (value as ReportStep) : null;
}

/** ~1 m precision: nearby pin positions share a cached lookup. */
function geoKey(location: DraftLocation | null) {
  return location
    ? [Number(location.lat.toFixed(5)), Number(location.lng.toFixed(5))]
    : null;
}

/**
 * The four-step citizen report flow: photos → location → category and
 * details → review. Everything lives in one draft that's saved to
 * sessionStorage on every change, so Back, Continue, the browser's own
 * back button and even a reload keep what's been entered.
 *
 * Steps are mirrored into `?step=N` with history.pushState, which Next
 * integrates with its router, so the phone's back gesture moves between
 * steps instead of leaving the page.
 */
export function ReportFlow() {
  const t = useTranslations("report");
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState<ReportDraft>(() => loadDraft());
  const [resumed, setResumed] = useState(() => hasProgress(draft));
  const [furthest, setFurthest] = useState<ReportStep>(draft.step);
  const [attempted, setAttempted] = useState<ReadonlySet<ReportStep>>(
    () => new Set(),
  );
  const [submitError, setSubmitError] = useState<SubmitErrorInfo | null>(null);
  const [done, setDone] = useState<Report | null>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const moveFocus = useRef(false);
  const furthestRef = useRef(furthest);
  furthestRef.current = furthest;

  useEffect(() => saveDraft(draft), [draft]);

  const categoriesQuery = useCategories();
  const categories = categoriesQuery.data ?? [];
  const category = categories.find((c) => c.id === draft.categoryId) ?? null;
  const tenant = useTenant();
  const mapView = useTenantMapView();

  const onPhotosChange = useCallback(
    (photos: DraftPhoto[]) => setDraft((current) => ({ ...current, photos })),
    [],
  );
  const uploads = usePhotoUploads(draft.photos, onPhotosChange);

  // Reverse geocode the pin, debounced so dragging doesn't fire a request
  // per frame.
  const settled = useDebouncedValue(draft.location, 500);
  const settledKey = geoKey(settled);
  const geoQuery = useQuery({
    queryKey: ["geo", "reverse", settledKey],
    queryFn: ({ signal }) =>
      reverseGeocode(
        { lat: settledKey?.[0] ?? 0, lng: settledKey?.[1] ?? 0 },
        signal,
      ),
    enabled: settledKey !== null,
    staleTime: Number.POSITIVE_INFINITY,
    retry: 1,
  });
  const geoStale =
    JSON.stringify(geoKey(draft.location)) !== JSON.stringify(settledKey);
  const geo: GeoCheck =
    !draft.location || geoStale || geoQuery.isPending
      ? { status: "pending" }
      : geoQuery.isError
        ? { status: "unavailable" }
        : { status: "done", inJurisdiction: geoQuery.data.in_jurisdiction };

  useEffect(() => {
    if (geoStale || !geoQuery.data) return;
    const addressText = geoQuery.data.address_text;
    const wardName = geoQuery.data.ward?.name ?? null;
    setDraft((current) =>
      current.addressText === addressText && current.wardName === wardName
        ? current
        : { ...current, addressText, wardName },
    );
  }, [geoQuery.data, geoStale]);

  // ---- validation

  const limits = photoLimits(category, categories);
  const photoIssue = validatePhotoCount(uploads.photos.length, limits);
  const locationIssue = validateLocation(draft.location, geo);
  const detailsIssues = useMemo(
    () => validateDetails(category, draft, uploads.photos.length),
    [category, draft, uploads.photos.length],
  );
  const uploadsState = uploadState(uploads.photos);

  // ---- navigation

  const goTo = useCallback((next: ReportStep, history = true) => {
    setDraft((current) => ({ ...current, step: next }));
    setFurthest((current) => (next > current ? next : current));
    setResumed(false);
    moveFocus.current = true;
    if (history) window.history.pushState(null, "", `?step=${next}`);
  }, []);

  // biome-ignore lint/correctness/useExhaustiveDependencies: sync the URL once on arrival
  useEffect(() => {
    window.history.replaceState(null, "", `?step=${draft.step}`);
    const onPopState = () => {
      const step = stepFromUrl();
      if (step && step <= furthestRef.current) goTo(step, false);
    };
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);

  // Move focus to the new step's heading after a step change, so screen
  // reader and keyboard users start at the top of what changed.
  // biome-ignore lint/correctness/useExhaustiveDependencies: runs when the step (or the done screen) changes
  useEffect(() => {
    if (!moveFocus.current) return;
    moveFocus.current = false;
    headingRef.current?.focus();
    headingRef.current?.scrollIntoView({ block: "nearest" });
  }, [draft.step, done]);

  // ---- submit

  const mutation = useMutation({
    mutationFn: ({ key }: { key: string }) => {
      if (!category) throw new Error("No category");
      const mediaIds = uploads.photos.flatMap((photo) =>
        photo.mediaId ? [photo.mediaId] : [],
      );
      return createReport(buildReportBody(draft, category, mediaIds), {
        idempotencyKey: key,
      });
    },
    onSuccess: (report) => {
      // The submitted draft is finished with. A new draft (with a new
      // idempotency key) replaces it, so "report another" can't replay.
      uploads.reset();
      setDraft(newDraft());
      setFurthest(1);
      setAttempted(new Set());
      setResumed(false);
      setDone(report);
      moveFocus.current = true;
      queryClient.invalidateQueries({ queryKey: ["reports", "mine"] });
    },
    onError: (error) => setSubmitError(submitErrorInfo(error)),
  });

  const submit = (key: string = draft.idempotencyKey) => {
    // Re-check every step: the citizen may have edited an earlier one
    // from the review page.
    if (photoIssue) return goTo(1);
    if (locationIssue) return goTo(2);
    if (hasDetailsIssues(detailsIssues) || !category) return goTo(3);
    if (uploadsState !== "ready") return;
    setSubmitError(null);
    mutation.mutate({ key });
  };

  const submitAsNew = () => {
    const key = randomId();
    setDraft((current) => ({ ...current, idempotencyKey: key }));
    submit(key);
  };

  const continueFrom = () => {
    const step = draft.step;
    setAttempted((current) => new Set(current).add(step));
    if (step === 1 && photoIssue) return;
    if (step === 2 && locationIssue) return;
    if (step === 3 && hasDetailsIssues(detailsIssues)) return;
    if (step === 4) return submit();
    goTo((step + 1) as ReportStep);
  };

  const startOver = () => {
    uploads.reset();
    setDraft(newDraft());
    setFurthest(1);
    setAttempted(new Set());
    setSubmitError(null);
    setResumed(false);
    moveFocus.current = true;
    window.history.replaceState(null, "", "?step=1");
  };

  if (done) {
    return (
      <ReportDone
        report={done}
        onAnother={() => {
          setDone(null);
          moveFocus.current = true;
          window.history.replaceState(null, "", "?step=1");
        }}
      />
    );
  }

  const step = draft.step;
  const showErrors = attempted.has(step);

  return (
    <div className="grid gap-6">
      <ReportProgress
        step={step}
        furthest={furthest}
        onSelect={(target) => goTo(target)}
      />

      {resumed ? (
        <Alert variant="info" live="polite">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p>{t("resumed")}</p>
            <Button variant="outline" size="sm" onClick={startOver}>
              <RotateCcw aria-hidden="true" />
              {t("startOver")}
            </Button>
          </div>
        </Alert>
      ) : null}

      <section aria-labelledby="report-step-heading" className="grid gap-4">
        <h2
          id="report-step-heading"
          ref={headingRef}
          tabIndex={-1}
          className="text-xl font-semibold outline-none sm:text-2xl"
        >
          {t(`${STEP_KEYS[step]}.title`)}
        </h2>

        {step === 1 ? (
          <PhotosStep
            photos={uploads.photos}
            limits={limits}
            issue={showErrors ? photoIssue : null}
            onAdd={uploads.add}
            onRemove={uploads.remove}
            onRetry={uploads.retry}
          />
        ) : step === 2 ? (
          <LocationStep
            location={draft.location}
            onChange={(location) =>
              setDraft((current) => ({ ...current, location }))
            }
            geo={geo}
            geoData={geoStale ? undefined : geoQuery.data}
            mapView={mapView}
            cityName={tenant.data?.name ?? null}
            issue={
              showErrors || locationIssue === "out_of_jurisdiction"
                ? locationIssue
                : null
            }
          />
        ) : step === 3 ? (
          <DetailsStep
            categories={categories}
            categoriesState={categoriesQuery.status}
            draft={draft}
            photoCount={uploads.photos.length}
            issues={showErrors ? detailsIssues : null}
            onCategory={(next) =>
              setDraft((current) => ({
                ...current,
                categoryId: next.id,
                // Keep answers to fields the new category also has.
                details: Object.fromEntries(
                  Object.entries(current.details).filter(([key]) =>
                    next.fields.some((field) => field.key === key),
                  ),
                ),
              }))
            }
            onDetail={(key, value) =>
              setDraft((current) => {
                const details = { ...current.details };
                if (value === undefined) delete details[key];
                else details[key] = value;
                return { ...current, details };
              })
            }
            onDescription={(description) =>
              setDraft((current) => ({ ...current, description }))
            }
            onEditPhotos={() => goTo(1)}
            onRetryCategories={() => categoriesQuery.refetch()}
          />
        ) : (
          <ReviewStep
            draft={draft}
            photos={uploads.photos}
            category={category}
            uploads={uploadsState}
            submitting={mutation.isPending}
            error={submitError}
            onEdit={(target) => goTo(target)}
            onSubmit={() => submit()}
            onSubmitAsNew={submitAsNew}
          />
        )}
      </section>

      <div className="sticky bottom-0 z-20 -mx-4 flex gap-3 border-t border-border bg-background/95 px-4 py-3 backdrop-blur sm:static sm:mx-0 sm:border-0 sm:bg-transparent sm:px-0 sm:backdrop-blur-none">
        {step > 1 ? (
          <Button
            variant="outline"
            size="lg"
            onClick={() => goTo((step - 1) as ReportStep)}
          >
            <ArrowLeft aria-hidden="true" className="rtl:rotate-180" />
            {t("back")}
          </Button>
        ) : null}
        <Button
          size="lg"
          className="flex-1 sm:ms-auto sm:flex-none sm:px-8"
          onClick={continueFrom}
          loading={step === 4 && mutation.isPending}
          disabled={step === 4 && uploadsState !== "ready"}
        >
          {step === 4 ? (
            <>
              {mutation.isPending ? t("review.submitting") : t("review.submit")}
              {mutation.isPending ? null : <Send aria-hidden="true" />}
            </>
          ) : (
            <>
              {t("next")}
              <ArrowRight aria-hidden="true" className="rtl:rotate-180" />
            </>
          )}
        </Button>
      </div>
    </div>
  );
}
