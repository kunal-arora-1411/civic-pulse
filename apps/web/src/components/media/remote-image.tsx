"use client";

import { ImageOff } from "lucide-react";
import { type ComponentProps, useState } from "react";
import { cn } from "@/lib/utils";

/**
 * An image from object storage. These are short-lived signed URLs, so
 * next/image can't cache or optimise them; the API already serves small
 * WebP variants (thumb ≤ 400 px, display ≤ 1600 px). Images load lazily,
 * and a missing or expired one shows a neutral placeholder instead of a
 * broken-image icon.
 */
export function RemoteImage({
  src,
  alt,
  className,
  fallbackClassName,
  loading = "lazy",
  ...props
}: Omit<ComponentProps<"img">, "src"> & {
  src: string | null | undefined;
  alt: string;
  fallbackClassName?: string;
}) {
  const [failed, setFailed] = useState<string | null>(null);
  if (!src || failed === src) {
    return (
      <span
        role="img"
        aria-label={alt}
        className={cn(
          "grid place-items-center bg-muted text-muted-foreground",
          className,
          fallbackClassName,
        )}
      >
        <ImageOff aria-hidden="true" className="size-6 opacity-60" />
      </span>
    );
  }
  return (
    // biome-ignore lint/performance/noImgElement: signed storage URLs; see above
    <img
      src={src}
      alt={alt}
      loading={loading}
      decoding="async"
      onError={() => setFailed(src)}
      className={cn("bg-muted object-cover", className)}
      {...props}
    />
  );
}
