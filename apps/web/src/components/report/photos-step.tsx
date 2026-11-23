"use client";

import {
  Camera,
  CircleAlert,
  CircleCheck,
  ImageIcon,
  ImagePlus,
  RotateCcw,
  X,
} from "lucide-react";
import { useTranslations } from "next-intl";
import { type ChangeEvent, useId, useRef, useState } from "react";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { useErrorMessage } from "@/hooks/use-error-message";
import type { PhotoIssue, PhotoLimits } from "@/lib/report/validation";
import { cn } from "@/lib/utils";
import type { LivePhoto } from "./use-photo-uploads";

function PhotoTile({
  photo,
  number,
  onRemove,
  onRetry,
}: {
  photo: LivePhoto;
  number: number;
  onRemove: () => void;
  onRetry: () => void;
}) {
  const t = useTranslations("report.photos");
  const errorMessage = useErrorMessage();
  const percent = Math.round(photo.progress * 100);
  const busy = photo.status !== "done" && photo.status !== "error";
  const statusText =
    photo.status === "uploading"
      ? t("status.uploading", { percent })
      : t(`status.${photo.status}`);

  return (
    <li className="grid gap-1.5">
      <div
        className={cn(
          "relative aspect-square overflow-hidden rounded-xl border bg-muted",
          photo.status === "error" ? "border-destructive" : "border-border",
        )}
      >
        {photo.previewUrl ? (
          // biome-ignore lint/performance/noImgElement: a local object/data URL; next/image can't optimise it
          <img
            src={photo.previewUrl}
            alt={t("photoAlt", { number })}
            className={cn(
              "size-full object-cover transition-opacity",
              busy && "opacity-70",
            )}
          />
        ) : (
          <div className="grid size-full place-items-center text-muted-foreground">
            <ImageIcon aria-hidden="true" className="size-8" />
            <span className="sr-only">{t("photoAlt", { number })}</span>
          </div>
        )}
        <Button
          variant="secondary"
          size="icon-sm"
          onClick={onRemove}
          aria-label={t("remove", { number })}
          className="absolute end-1.5 top-1.5 rounded-full bg-card/90 shadow-card backdrop-blur"
        >
          <X aria-hidden="true" />
        </Button>
        {busy ? (
          <div className="absolute inset-x-2 bottom-2">
            <div
              role="progressbar"
              aria-label={t("progressLabel", { number })}
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={photo.status === "uploading" ? percent : undefined}
              aria-valuetext={statusText}
              className="h-1.5 overflow-hidden rounded-full bg-card/80"
            >
              <div
                className={cn(
                  "h-full rounded-full bg-primary transition-[width] duration-200",
                  photo.status !== "uploading" &&
                    "w-1/3 motion-safe:animate-pulse",
                )}
                style={
                  photo.status === "uploading"
                    ? { width: `${Math.max(4, percent)}%` }
                    : undefined
                }
              />
            </div>
          </div>
        ) : null}
      </div>
      <p
        className={cn(
          "flex items-center gap-1 text-xs font-medium",
          photo.status === "error"
            ? "text-destructive-soft-foreground"
            : "text-muted-foreground",
        )}
      >
        {photo.status === "done" ? (
          <CircleCheck aria-hidden="true" className="size-3.5 text-primary" />
        ) : photo.status === "error" ? (
          <CircleAlert aria-hidden="true" className="size-3.5" />
        ) : null}
        {statusText}
      </p>
      {photo.status === "error" ? (
        <>
          <p className="text-xs text-destructive-soft-foreground">
            {errorMessage(photo.error)}
          </p>
          <Button
            variant="outline"
            size="sm"
            onClick={onRetry}
            aria-label={t("retryLabel", { number })}
          >
            <RotateCcw aria-hidden="true" />
            {t("retry")}
          </Button>
        </>
      ) : null}
    </li>
  );
}

export function PhotosStep({
  photos,
  limits,
  issue,
  onAdd,
  onRemove,
  onRetry,
}: {
  photos: LivePhoto[];
  limits: PhotoLimits;
  /** Shown once the citizen has tried to continue. */
  issue: PhotoIssue | null;
  onAdd: (files: File[]) => void;
  onRemove: (id: string) => void;
  onRetry: (id: string) => void;
}) {
  const t = useTranslations("report.photos");
  const cameraRef = useRef<HTMLInputElement>(null);
  const galleryRef = useRef<HTMLInputElement>(null);
  const [skipped, setSkipped] = useState(0);
  const ids = { camera: useId(), gallery: useId(), status: useId() };
  const remaining = Math.max(0, limits.max - photos.length);
  const full = remaining === 0;

  const handleFiles = (event: ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.target.files ?? []);
    // Reset so picking the same file again still fires a change.
    event.target.value = "";
    if (files.length === 0) return;
    setSkipped(Math.max(0, files.length - remaining));
    onAdd(files.slice(0, remaining));
  };

  const uploaded = photos.filter((photo) => photo.status === "done").length;

  return (
    <div className="grid gap-5">
      <p className="text-muted-foreground">{t("hint", { max: limits.max })}</p>

      <div className="grid gap-3 sm:grid-cols-2">
        <input
          ref={cameraRef}
          id={ids.camera}
          type="file"
          accept="image/*"
          capture="environment"
          className="sr-only"
          tabIndex={-1}
          aria-hidden="true"
          onChange={handleFiles}
        />
        <input
          ref={galleryRef}
          id={ids.gallery}
          type="file"
          accept="image/jpeg,image/png,image/webp,image/heic,image/heif"
          multiple
          className="sr-only"
          tabIndex={-1}
          aria-hidden="true"
          onChange={handleFiles}
        />
        <Button
          size="lg"
          className="h-16 text-base [&_svg]:size-6"
          disabled={full}
          onClick={() => cameraRef.current?.click()}
        >
          <Camera aria-hidden="true" />
          {t("takePhoto")}
        </Button>
        <Button
          size="lg"
          variant="outline"
          className="h-16 text-base [&_svg]:size-6"
          disabled={full}
          onClick={() => galleryRef.current?.click()}
        >
          <ImagePlus aria-hidden="true" />
          {t("choose")}
        </Button>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
        <p className="font-semibold">
          {t("count", { count: photos.length, max: limits.max })}
        </p>
        <p id={ids.status} aria-live="polite" className="text-muted-foreground">
          {photos.length > 0
            ? t("uploadedCount", { uploaded, total: photos.length })
            : ""}
        </p>
      </div>

      {full ? (
        <Alert variant="info">{t("limitReached", { max: limits.max })}</Alert>
      ) : null}
      {skipped > 0 ? (
        <Alert variant="warning" live="polite">
          {t("skipped", { count: skipped, max: limits.max })}
        </Alert>
      ) : null}
      {issue ? (
        <Alert variant="destructive" live="assertive">
          {issue === "too_few"
            ? t("tooFew", { min: limits.min })
            : t("tooMany", {
                extra: photos.length - limits.max,
                max: limits.max,
              })}
        </Alert>
      ) : null}

      {photos.length > 0 ? (
        <ul
          aria-label={t("listLabel")}
          className="grid grid-cols-2 gap-3 sm:grid-cols-3"
        >
          {photos.map((photo, index) => (
            <PhotoTile
              key={photo.id}
              photo={photo}
              number={index + 1}
              onRemove={() => onRemove(photo.id)}
              onRetry={() => onRetry(photo.id)}
            />
          ))}
        </ul>
      ) : (
        <div className="grid justify-items-center gap-2 rounded-xl border-2 border-dashed border-border px-6 py-10 text-center text-muted-foreground">
          <Camera aria-hidden="true" className="size-8" />
          <p>{t("empty")}</p>
        </div>
      )}

      <p className="text-sm text-muted-foreground">{t("tip")}</p>
    </div>
  );
}
