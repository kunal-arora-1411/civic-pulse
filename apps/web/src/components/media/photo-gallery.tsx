"use client";

import { ChevronLeft, ChevronRight, ExternalLink } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import type { Media } from "@/lib/api";
import { cn } from "@/lib/utils";
import { RemoteImage } from "./remote-image";

/**
 * Thumbnails that open a lightbox. The lightbox is the native-<dialog>
 * Dialog (focus trap, Escape, focus returns to the thumbnail), with
 * previous/next buttons and the arrow keys, and a "Photo 2 of 3" title so
 * screen reader users know where they are.
 */
export function PhotoGallery({
  media,
  label,
  showOriginal = false,
  className,
}: {
  media: Media[];
  /** Describes the photos, e.g. "Photos of R-26-000123". */
  label: string;
  /** Staff can open the untouched original (with its metadata). */
  showOriginal?: boolean;
  className?: string;
}) {
  const t = useTranslations("gallery");
  const [index, setIndex] = useState<number | null>(null);
  if (media.length === 0) {
    return <p className="text-sm text-muted-foreground">{t("none")}</p>;
  }
  const current = index === null ? null : media[index];
  const step = (delta: number) =>
    setIndex((value) =>
      value === null ? value : (value + delta + media.length) % media.length,
    );

  return (
    <>
      <ul
        aria-label={label}
        className={cn("grid grid-cols-3 gap-2 sm:grid-cols-4", className)}
      >
        {media.map((item, i) => (
          <li key={item.id}>
            <button
              type="button"
              onClick={() => setIndex(i)}
              className="group block aspect-square w-full overflow-hidden rounded-lg border border-border"
              aria-label={t("open", { number: i + 1, total: media.length })}
            >
              <RemoteImage
                src={item.thumb_url ?? item.display_url}
                alt=""
                className="size-full transition-transform group-hover:scale-[1.03]"
              />
            </button>
          </li>
        ))}
      </ul>

      <Dialog
        open={current !== null}
        onOpenChange={(open) => {
          if (!open) setIndex(null);
        }}
        title={
          index === null
            ? ""
            : t("position", { number: index + 1, total: media.length })
        }
        closeLabel={t("close")}
        className="max-w-4xl"
      >
        {current ? (
          // biome-ignore lint/a11y/noStaticElementInteractions: arrow keys are a shortcut; the buttons below do the same
          <div
            className="grid gap-3 pb-2"
            onKeyDown={(event) => {
              if (event.key === "ArrowRight") step(1);
              if (event.key === "ArrowLeft") step(-1);
            }}
          >
            <div className="grid place-items-center overflow-hidden rounded-lg bg-muted">
              <RemoteImage
                key={current.id}
                src={current.display_url ?? current.thumb_url}
                alt={t("position", {
                  number: (index ?? 0) + 1,
                  total: media.length,
                })}
                loading="eager"
                className="max-h-[65dvh] w-auto max-w-full object-contain"
                fallbackClassName="aspect-[4/3] w-full"
              />
            </div>
            <div className="flex items-center justify-between gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={() => step(-1)}
                disabled={media.length < 2}
              >
                <ChevronLeft aria-hidden="true" className="rtl:rotate-180" />
                {t("previous")}
              </Button>
              {showOriginal && current.original_url ? (
                <a
                  href={current.original_url}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center gap-1 text-sm font-semibold text-primary underline-offset-4 hover:underline"
                >
                  {t("original")}
                  <ExternalLink aria-hidden="true" className="size-3.5" />
                </a>
              ) : null}
              <Button
                variant="outline"
                size="sm"
                onClick={() => step(1)}
                disabled={media.length < 2}
              >
                {t("next")}
                <ChevronRight aria-hidden="true" className="rtl:rotate-180" />
              </Button>
            </div>
          </div>
        ) : null}
      </Dialog>
    </>
  );
}
