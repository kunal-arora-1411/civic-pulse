import {
  ALLOWED_UPLOAD_TYPES,
  ApiError,
  completeUpload,
  createUpload,
  type MediaAsset,
  type UploadContentType,
  type UploadTicket,
} from "@/lib/api";

/*
 * The photo upload pipeline: compress in the browser, then
 * create upload → PUT to the pre-signed URL → complete.
 *
 * Every failure surfaces as an ApiError so the UI can map one set of codes
 * to messages, whether the problem came from the API, from object storage
 * or from the device itself.
 */

/** The contract's default limit; the ticket's `max_size_bytes` wins. */
export const MAX_UPLOAD_BYTES = 10 * 1024 * 1024;

export const COMPRESSION = {
  maxWidthOrHeight: 1600,
  initialQuality: 0.8,
  /** Compression keeps iterating until the photo is under this size. */
  maxSizeMB: 1.5,
  fileType: "image/jpeg",
} as const;

export type PreparedImage = { blob: Blob; contentType: UploadContentType };

function isAllowedType(type: string): type is UploadContentType {
  return (ALLOWED_UPLOAD_TYPES as readonly string[]).includes(type);
}

/**
 * Shrink a camera photo (often 4–8 MB) to roughly 1600 px at quality 0.8,
 * usually a few hundred kB, which matters on a 3G connection.
 *
 * Two choices worth knowing about:
 * - The web worker is off. The library's worker loads its script from a
 *   public CDN, which we don't want to depend on (or leak visits to).
 *   Compressing one photo on the main thread takes well under a second on
 *   a mid-range phone.
 * - EXIF is preserved. The server reads the capture time from it and
 *   strips all metadata from the copies anyone else sees (contract §3).
 */
export async function prepareImage(
  file: File,
  signal?: AbortSignal,
): Promise<PreparedImage> {
  if (!file.type.startsWith("image/")) {
    throw new ApiError({
      status: 0,
      code: "unsupported_media_type",
      message: `Not an image: ${file.type || "unknown type"}`,
    });
  }
  const { default: imageCompression } = await import(
    "browser-image-compression"
  );
  let compressed: Blob;
  try {
    compressed = await imageCompression(file, {
      ...COMPRESSION,
      useWebWorker: false,
      preserveExif: true,
      signal,
    });
  } catch (error) {
    if (signal?.aborted) throw signal.reason ?? error;
    // The browser couldn't decode it (HEIC on most non-Apple browsers, a
    // corrupt file). Send the original if the API accepts its type.
    if (isAllowedType(file.type)) return { blob: file, contentType: file.type };
    throw new ApiError({
      status: 0,
      code: "unsupported_media_type",
      message: "The browser couldn't read this image.",
      cause: error,
    });
  }
  const contentType = isAllowedType(compressed.type)
    ? compressed.type
    : COMPRESSION.fileType;
  return { blob: compressed, contentType };
}

export async function sha256Hex(blob: Blob): Promise<string> {
  const digest = await crypto.subtle.digest(
    "SHA-256",
    await blob.arrayBuffer(),
  );
  return Array.from(new Uint8Array(digest), (byte) =>
    byte.toString(16).padStart(2, "0"),
  ).join("");
}

/**
 * PUT the bytes to object storage. XMLHttpRequest rather than fetch,
 * because fetch still can't report upload progress.
 */
export function putToStorage(
  ticket: Pick<UploadTicket, "url" | "method" | "headers">,
  blob: Blob,
  options: { onProgress?: (fraction: number) => void; signal?: AbortSignal },
): Promise<void> {
  const { onProgress, signal } = options;
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(signal.reason ?? new DOMException("Aborted", "AbortError"));
      return;
    }
    const xhr = new XMLHttpRequest();
    xhr.open(ticket.method || "PUT", ticket.url);
    for (const [name, value] of Object.entries(ticket.headers ?? {})) {
      xhr.setRequestHeader(name, value);
    }
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable && event.total > 0) {
        onProgress?.(Math.min(1, event.loaded / event.total));
      }
    };
    const fail = (message: string, status = xhr.status) =>
      reject(
        new ApiError({
          // A 403 from storage almost always means the signed URL expired.
          status,
          code: "upload_failed",
          message,
        }),
      );
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        onProgress?.(1);
        resolve();
      } else {
        fail(`Storage rejected the upload (${xhr.status}).`);
      }
    };
    xhr.onerror = () => fail("The upload didn't reach storage.", 0);
    xhr.ontimeout = () => fail("The upload timed out.", 0);
    xhr.onabort = () => reject(new DOMException("Aborted", "AbortError"));
    signal?.addEventListener("abort", () => xhr.abort(), { once: true });
    xhr.send(blob);
  });
}

export type UploadStage = "preparing" | "uploading" | "verifying";

export type UploadCallbacks = {
  onStage?: (stage: UploadStage) => void;
  /** Fraction of bytes sent to storage, 0–1. */
  onProgress?: (fraction: number) => void;
  signal?: AbortSignal;
};

/**
 * Upload an already-compressed image and return the verified media asset.
 *
 * Retrying runs all three steps again with a fresh ticket. Signed URLs
 * expire after ten minutes, so reusing an old one after a long stall would
 * just fail at storage; the abandoned upload is cleaned up server-side.
 */
export async function uploadImage(
  image: PreparedImage,
  { onStage, onProgress, signal }: UploadCallbacks = {},
): Promise<MediaAsset> {
  if (image.blob.size > MAX_UPLOAD_BYTES) {
    throw new ApiError({
      status: 0,
      code: "file_too_large",
      message: "The photo is larger than the upload limit.",
    });
  }
  onStage?.("preparing");
  const checksum = await sha256Hex(image.blob);
  const ticket = await createUpload(
    {
      purpose: "report_evidence",
      content_type: image.contentType,
      size_bytes: image.blob.size,
      checksum_sha256: checksum,
    },
    signal,
  );
  if (image.blob.size > ticket.max_size_bytes) {
    throw new ApiError({
      status: 0,
      code: "file_too_large",
      message: "The photo is larger than the upload limit.",
    });
  }
  onStage?.("uploading");
  onProgress?.(0);
  await putToStorage(ticket, image.blob, { onProgress, signal });
  onStage?.("verifying");
  return completeUpload(ticket.upload_id, signal);
}
