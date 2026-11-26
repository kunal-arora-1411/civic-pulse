import { mediaCompleteUpload, mediaCreateUpload } from "@civicpulse/api-client";
import { call } from "../generated-client";
import {
  type MediaAsset,
  mediaAssetSchema,
  type UploadContentType,
  type UploadTicket,
  uploadTicketSchema,
} from "../schemas-phase1";

export type CreateUploadBody = {
  purpose: "report_evidence";
  content_type: UploadContentType;
  size_bytes: number;
  checksum_sha256: string;
};

/**
 * Step 1 of an upload: ask for a pre-signed URL. The bytes then go straight
 * to object storage (see lib/upload), never through the API.
 */
export function createUpload(
  body: CreateUploadBody,
  signal?: AbortSignal,
): Promise<UploadTicket> {
  return call(uploadTicketSchema, (o) => mediaCreateUpload(body, o), {
    signal,
  });
}

/** Step 3: the server checks size, checksum and the real content type. */
export function completeUpload(
  uploadId: string,
  signal?: AbortSignal,
): Promise<MediaAsset> {
  return call(mediaAssetSchema, (o) => mediaCompleteUpload(uploadId, o), {
    signal,
  });
}
