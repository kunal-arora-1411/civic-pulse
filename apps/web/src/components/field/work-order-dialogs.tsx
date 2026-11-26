"use client";

import { LocateFixed } from "lucide-react";
import { useTranslations } from "next-intl";
import { useEffect, useId, useState } from "react";
import { PhotosStep } from "@/components/report/photos-step";
import { usePhotoUploads } from "@/components/report/use-photo-uploads";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Dialog } from "@/components/ui/dialog";
import { Field } from "@/components/ui/field";
import { inputClasses } from "@/components/ui/input";
import { useErrorMessage } from "@/hooks/use-error-message";
import {
  declineWorkOrder,
  isApiError,
  type MediaPhase,
  postProgress,
  requestClosure,
  type WorkOrder,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import {
  useWorkOrderAction,
  type WorkOrderConflict,
} from "./use-work-order-action";

const NOTE_MAX = 2000;
const MAX_PHOTOS = 5;

type DialogProps = {
  order: WorkOrder;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onDone: (message: string) => void;
  onConflict: (conflict: WorkOrderConflict) => void;
};

/** Errors handled by closing the dialog and showing the reconcile banner. */
function isConflict(error: unknown) {
  return (
    isApiError(error, "version_conflict") ||
    isApiError(error, "invalid_work_order_action")
  );
}

function noop() {}

/** Evidence photos for one phase, uploaded as `work_evidence`. */
function useEvidence(phase: MediaPhase, open: boolean) {
  const uploads = usePhotoUploads([], noop, {
    purpose: "work_evidence",
    phase,
  });
  const { reset } = uploads;
  // Start clean every time the dialog opens.
  useEffect(() => {
    if (open) reset();
  }, [open, reset]);
  const mediaIds = uploads.photos
    .filter((photo) => photo.status === "done" && photo.mediaId)
    .map((photo) => photo.mediaId as string);
  const busy = uploads.photos.some(
    (photo) => photo.status !== "done" && photo.status !== "error",
  );
  const failed = uploads.photos.some((photo) => photo.status === "error");
  return { ...uploads, mediaIds, busy, failed };
}

function currentPosition(): Promise<{ lat: number; lng: number }> {
  return new Promise((resolve, reject) => {
    if (!("geolocation" in navigator)) {
      reject(new Error("unavailable"));
      return;
    }
    navigator.geolocation.getCurrentPosition(
      (position) =>
        resolve({
          lat: position.coords.latitude,
          lng: position.coords.longitude,
        }),
      reject,
      { enableHighAccuracy: true, timeout: 15_000, maximumAge: 60_000 },
    );
  });
}

// ------------------------------------------------------------------ decline

export function DeclineDialog({
  order,
  open,
  onOpenChange,
  onDone,
  onConflict,
}: DialogProps) {
  const t = useTranslations("field.decline");
  const errorMessage = useErrorMessage();
  const [reason, setReason] = useState("");
  const [attempted, setAttempted] = useState(false);
  useEffect(() => {
    if (!open) return;
    setReason("");
    setAttempted(false);
  }, [open]);

  const mutation = useWorkOrderAction(
    order.id,
    (text: string) => declineWorkOrder(order.id, order.version, text),
    {
      onSuccess: () => {
        onOpenChange(false);
        onDone(t("done"));
      },
      onConflict: (conflict) => {
        onOpenChange(false);
        onConflict(conflict);
      },
    },
  );
  const missing = !reason.trim();
  const submit = () => {
    setAttempted(true);
    if (missing) return;
    mutation.mutate(reason.trim());
  };
  const serverError =
    mutation.isError && !isConflict(mutation.error)
      ? errorMessage(mutation.error)
      : null;

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={t("title", { reference: order.issue.reference })}
      description={t("description")}
      closeLabel={t("close")}
      footer={
        <>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t("cancel")}
          </Button>
          <Button
            variant="destructive"
            onClick={submit}
            loading={mutation.isPending}
          >
            {t("submit")}
          </Button>
        </>
      }
    >
      <div className="grid gap-4">
        <Field
          label={t("reason")}
          description={t("reasonHelp")}
          required
          error={attempted && missing ? t("reasonRequired") : undefined}
        >
          {(control) => (
            <textarea
              {...control}
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              rows={3}
              maxLength={NOTE_MAX}
              className={cn(inputClasses, "h-auto py-2")}
            />
          )}
        </Field>
        {serverError ? (
          <Alert variant="destructive" live="assertive">
            {serverError}
          </Alert>
        ) : null}
      </div>
    </Dialog>
  );
}

// ----------------------------------------------------------------- progress

export function ProgressDialog({
  order,
  open,
  onOpenChange,
  onDone,
  onConflict,
}: DialogProps) {
  const t = useTranslations("field.progress");
  const errorMessage = useErrorMessage();
  const ids = { phase: useId(), location: useId() };
  // Before work starts, photos record the "before" scene.
  const [phase, setPhase] = useState<MediaPhase>(
    order.state === "accepted" ? "before" : "after",
  );
  const [note, setNote] = useState("");
  const [shareLocation, setShareLocation] = useState(false);
  const [locating, setLocating] = useState(false);
  const [locationFailed, setLocationFailed] = useState(false);
  const [attempted, setAttempted] = useState(false);
  const evidence = useEvidence(phase, open);

  useEffect(() => {
    if (!open) return;
    setPhase(order.state === "accepted" ? "before" : "after");
    setNote("");
    setShareLocation(false);
    setLocationFailed(false);
    setAttempted(false);
  }, [open, order.state]);

  const mutation = useWorkOrderAction(
    order.id,
    (body: Parameters<typeof postProgress>[1]) => postProgress(order.id, body),
    {
      onSuccess: () => {
        onOpenChange(false);
        onDone(t("done"));
      },
      onConflict: (conflict) => {
        onOpenChange(false);
        onConflict(conflict);
      },
    },
  );

  const empty = !note.trim() && evidence.mediaIds.length === 0;
  const submit = async () => {
    setAttempted(true);
    if (empty || evidence.busy) return;
    let location: { lat: number; lng: number } | null = null;
    if (shareLocation) {
      setLocating(true);
      try {
        location = await currentPosition();
        setLocationFailed(false);
      } catch {
        // Send the update anyway; the location is optional.
        setLocationFailed(true);
      } finally {
        setLocating(false);
      }
    }
    mutation.mutate({
      version: order.version,
      note: note.trim() || undefined,
      location,
      media_ids: evidence.mediaIds,
    });
  };
  const serverError =
    mutation.isError && !isConflict(mutation.error)
      ? errorMessage(mutation.error)
      : null;

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={t("title", { reference: order.issue.reference })}
      description={t("description")}
      closeLabel={t("close")}
      footer={
        <>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t("cancel")}
          </Button>
          <Button
            onClick={submit}
            loading={mutation.isPending || locating}
            disabled={evidence.busy}
          >
            {evidence.busy ? t("waitingForPhotos") : t("submit")}
          </Button>
        </>
      }
    >
      <div className="grid gap-5">
        <Field label={t("note")} description={t("noteHelp")}>
          {(control) => (
            <textarea
              {...control}
              value={note}
              onChange={(event) => setNote(event.target.value)}
              rows={3}
              maxLength={NOTE_MAX}
              className={cn(inputClasses, "h-auto py-2")}
            />
          )}
        </Field>

        <fieldset className="grid gap-2">
          <legend className="mb-1 text-sm font-semibold">
            {t("phaseLegend")}
          </legend>
          <div className="flex flex-wrap gap-4">
            {(["before", "after"] as const).map((value) => (
              <label
                key={value}
                className="flex cursor-pointer items-center gap-2 text-sm"
              >
                <input
                  type="radio"
                  name={ids.phase}
                  value={value}
                  checked={phase === value}
                  // The phase is part of each upload; lock it once photos
                  // are on their way.
                  disabled={evidence.photos.length > 0}
                  onChange={() => setPhase(value)}
                  className="size-4 accent-primary"
                />
                {t(`phase.${value}`)}
              </label>
            ))}
          </div>
        </fieldset>

        <PhotosStep
          photos={evidence.photos}
          limits={{ min: 0, max: MAX_PHOTOS }}
          issue={null}
          hint={t("photosHint", { max: MAX_PHOTOS })}
          onAdd={evidence.add}
          onRemove={evidence.remove}
          onRetry={evidence.retry}
        />

        <div className="flex items-center gap-2 text-sm">
          <Checkbox
            id={ids.location}
            checked={shareLocation}
            onChange={(event) => setShareLocation(event.target.checked)}
          />
          <label
            htmlFor={ids.location}
            className="flex cursor-pointer items-center gap-2"
          >
            <LocateFixed aria-hidden="true" className="size-4" />
            {t("shareLocation")}
          </label>
        </div>
        {locationFailed ? (
          <Alert variant="warning">{t("locationFailed")}</Alert>
        ) : null}

        {attempted && empty ? (
          <Alert variant="warning" live="assertive">
            {t("empty")}
          </Alert>
        ) : null}
        {serverError ? (
          <Alert variant="destructive" live="assertive">
            {serverError}
          </Alert>
        ) : null}
      </div>
    </Dialog>
  );
}

// ------------------------------------------------------------------ closure

/** A readable label for a category's closure reason code. */
function useReasonLabel() {
  const t = useTranslations("field.closure.reasonCodes");
  return (code: string) => {
    // Codes are configured per category; only the common ones have text.
    const key = code as Parameters<typeof t>[0];
    return t.has(key) ? t(key) : code.replaceAll("_", " ");
  };
}

export function ClosureDialog({
  order,
  open,
  onOpenChange,
  onDone,
  onConflict,
}: DialogProps) {
  const t = useTranslations("field.closure");
  const errorMessage = useErrorMessage();
  const reasonLabel = useReasonLabel();
  const ids = { reasons: useId() };
  const [note, setNote] = useState("");
  /** Offered after the API says a photo or one of these codes is needed. */
  const [allowedCodes, setAllowedCodes] = useState<string[] | null>(null);
  const [reasonCode, setReasonCode] = useState<string | null>(null);
  const evidence = useEvidence("after", open);
  const hasAfter = order.evidence.some((item) => item.phase === "after");

  useEffect(() => {
    if (!open) return;
    setNote("");
    setAllowedCodes(null);
    setReasonCode(null);
  }, [open]);

  const mutation = useWorkOrderAction(
    order.id,
    (body: Parameters<typeof requestClosure>[1]) =>
      requestClosure(order.id, body),
    {
      onSuccess: () => {
        onOpenChange(false);
        onDone(t("done"));
      },
      onConflict: (conflict) => {
        onOpenChange(false);
        onConflict(conflict);
      },
    },
  );

  // The field view doesn't list the category's reason codes; the API
  // names them when it refuses a closure without an after photo.
  useEffect(() => {
    const error = mutation.error;
    if (!isApiError(error, "evidence_required")) return;
    const codes = error.details.allowed_reason_codes;
    setAllowedCodes(
      Array.isArray(codes)
        ? codes.filter((code): code is string => typeof code === "string")
        : [],
    );
  }, [mutation.error]);

  const submit = () => {
    if (evidence.busy) return;
    mutation.mutate({
      version: order.version,
      media_ids: evidence.mediaIds,
      reason_code:
        evidence.mediaIds.length === 0 ? (reasonCode ?? undefined) : undefined,
      note: note.trim() || undefined,
    });
  };
  const evidenceMissing = isApiError(mutation.error, "evidence_required");
  const serverError =
    mutation.isError && !isConflict(mutation.error) && !evidenceMissing
      ? errorMessage(mutation.error)
      : null;

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={t("title", { reference: order.issue.reference })}
      description={t("description")}
      closeLabel={t("close")}
      footer={
        <>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t("cancel")}
          </Button>
          <Button
            onClick={submit}
            loading={mutation.isPending}
            disabled={evidence.busy}
          >
            {evidence.busy ? t("waitingForPhotos") : t("submit")}
          </Button>
        </>
      }
    >
      <div className="grid gap-5">
        {hasAfter ? <Alert variant="info">{t("hasAfter")}</Alert> : null}
        <PhotosStep
          photos={evidence.photos}
          limits={{ min: 0, max: MAX_PHOTOS }}
          issue={null}
          hint={t("photosHint", { max: MAX_PHOTOS })}
          onAdd={evidence.add}
          onRemove={evidence.remove}
          onRetry={evidence.retry}
        />

        {allowedCodes !== null && evidence.mediaIds.length === 0 ? (
          allowedCodes.length > 0 ? (
            <fieldset className="grid gap-2">
              <legend className="mb-1 text-sm font-semibold">
                {t("reasonLegend")}
              </legend>
              <p className="text-sm text-muted-foreground">{t("reasonHelp")}</p>
              {allowedCodes.map((code) => (
                <label
                  key={code}
                  className="flex cursor-pointer items-center gap-2 text-sm"
                >
                  <input
                    type="radio"
                    name={ids.reasons}
                    value={code}
                    checked={reasonCode === code}
                    onChange={() => setReasonCode(code)}
                    className="size-4 accent-primary"
                  />
                  {reasonLabel(code)}
                </label>
              ))}
            </fieldset>
          ) : (
            <Alert variant="warning" live="assertive">
              {t("photoRequired")}
            </Alert>
          )
        ) : null}

        <Field label={t("note")} description={t("noteHelp")}>
          {(control) => (
            <textarea
              {...control}
              value={note}
              onChange={(event) => setNote(event.target.value)}
              rows={3}
              maxLength={NOTE_MAX}
              className={cn(inputClasses, "h-auto py-2")}
            />
          )}
        </Field>

        {serverError ? (
          <Alert variant="destructive" live="assertive">
            {serverError}
          </Alert>
        ) : null}
      </div>
    </Dialog>
  );
}
