"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { UploadPurpose } from "@/lib/api";
import { type DraftPhoto, randomId } from "@/lib/report/draft";
import type { PhotoStatus } from "@/lib/report/validation";
import {
  type PreparedImage,
  prepareImage,
  uploadImage,
} from "@/lib/upload/upload";

export type LivePhoto = {
  id: string;
  status: PhotoStatus;
  /** Bytes sent to storage, 0–1. */
  progress: number;
  mediaId: string | null;
  /** Object URL of the compressed image, or the saved thumbnail. */
  previewUrl: string | null;
  thumbDataUrl: string | null;
  error: unknown;
};

type Internal = {
  prepared?: PreparedImage;
  file?: File;
  controller?: AbortController;
  objectUrl?: string;
};

const THUMB_SIZE = 240;

/**
 * A small JPEG data URL so the thumbnail survives a reload of the draft.
 * Best effort: without canvas support the tile shows a placeholder.
 */
async function makeThumb(blob: Blob): Promise<string | null> {
  try {
    const bitmap = await createImageBitmap(blob);
    const scale = Math.min(
      1,
      THUMB_SIZE / Math.max(bitmap.width, bitmap.height),
    );
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(bitmap.width * scale);
    canvas.height = Math.round(bitmap.height * scale);
    const context = canvas.getContext("2d");
    if (!context) return null;
    context.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
    bitmap.close();
    return canvas.toDataURL("image/jpeg", 0.7);
  } catch {
    return null;
  }
}

function fromDraft(photo: DraftPhoto): LivePhoto {
  return {
    id: photo.id,
    status: "done",
    progress: 1,
    mediaId: photo.mediaId,
    previewUrl: photo.thumbDataUrl,
    thumbDataUrl: photo.thumbDataUrl,
    error: null,
  };
}

/**
 * Photos in the report flow. Each one starts compressing and uploading
 * the moment it's added, so by the time the citizen reaches the review
 * step the uploads have usually finished. Finished photos are handed to
 * `onChange` to be kept in the draft.
 */
export function usePhotoUploads(
  initial: readonly DraftPhoto[],
  onChange: (photos: DraftPhoto[]) => void,
  /** What the photos are for; report photos unless given. */
  purpose?: UploadPurpose,
) {
  const [photos, setPhotos] = useState<LivePhoto[]>(() =>
    initial.map(fromDraft),
  );
  const internals = useRef(new Map<string, Internal>());
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;
  const purposeRef = useRef(purpose);
  purposeRef.current = purpose;

  const patch = useCallback((id: string, changes: Partial<LivePhoto>) => {
    setPhotos((current) =>
      current.map((photo) =>
        photo.id === id ? { ...photo, ...changes } : photo,
      ),
    );
  }, []);

  // Keep the draft in step with the finished uploads.
  const doneKey = photos
    .filter((photo) => photo.status === "done")
    .map((photo) => `${photo.id}:${photo.thumbDataUrl ? 1 : 0}`)
    .join(",");
  // biome-ignore lint/correctness/useExhaustiveDependencies: doneKey summarises the photos that matter
  useEffect(() => {
    onChangeRef.current(
      photos
        .filter((photo) => photo.status === "done" && photo.mediaId)
        .map((photo) => ({
          id: photo.id,
          mediaId: photo.mediaId as string,
          thumbDataUrl: photo.thumbDataUrl,
        })),
    );
  }, [doneKey]);

  const run = useCallback(
    async (id: string) => {
      const internal = internals.current.get(id);
      if (!internal) return;
      internal.controller?.abort();
      const controller = new AbortController();
      internal.controller = controller;
      const { signal } = controller;
      patch(id, { status: "preparing", progress: 0, error: null });
      try {
        if (!internal.prepared && internal.file) {
          internal.prepared = await prepareImage(internal.file, signal);
          internal.file = undefined;
          const objectUrl = URL.createObjectURL(internal.prepared.blob);
          if (internal.objectUrl) URL.revokeObjectURL(internal.objectUrl);
          internal.objectUrl = objectUrl;
          patch(id, { previewUrl: objectUrl });
          makeThumb(internal.prepared.blob).then((thumb) => {
            if (thumb) patch(id, { thumbDataUrl: thumb });
          });
        }
        const prepared = internal.prepared;
        if (!prepared) return;
        const asset = await uploadImage(prepared, {
          signal,
          purpose: purposeRef.current,
          onStage: (stage) => patch(id, { status: stage }),
          onProgress: (progress) => patch(id, { progress }),
        });
        patch(id, { status: "done", progress: 1, mediaId: asset.id });
      } catch (error) {
        if (signal.aborted) return;
        patch(id, { status: "error", error });
      }
    },
    [patch],
  );

  const add = useCallback(
    (files: readonly File[]) => {
      const added: LivePhoto[] = files.map((file) => {
        const id = randomId();
        internals.current.set(id, { file });
        return {
          id,
          status: "preparing",
          progress: 0,
          mediaId: null,
          previewUrl: null,
          thumbDataUrl: null,
          error: null,
        };
      });
      setPhotos((current) => [...current, ...added]);
      for (const photo of added) void run(photo.id);
    },
    [run],
  );

  const retry = useCallback((id: string) => void run(id), [run]);

  const remove = useCallback((id: string) => {
    const internal = internals.current.get(id);
    internal?.controller?.abort();
    if (internal?.objectUrl) URL.revokeObjectURL(internal.objectUrl);
    internals.current.delete(id);
    setPhotos((current) => current.filter((photo) => photo.id !== id));
  }, []);

  /** Start over, e.g. after a successful submission. */
  const reset = useCallback(() => {
    for (const internal of internals.current.values()) {
      internal.controller?.abort();
      if (internal.objectUrl) URL.revokeObjectURL(internal.objectUrl);
    }
    internals.current.clear();
    setPhotos([]);
  }, []);

  // Deliberately no abort-on-unmount cleanup. With Cache Components the
  // route stays mounted inside <Activity> when the citizen navigates away,
  // and effects are torn down while it's hidden. Aborting there would
  // leave photos stuck half-uploaded when they come back, so the uploads
  // finish in the background instead.

  return { photos, add, remove, retry, reset };
}
