import { apiRequest } from "../client";
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
  return apiRequest({
    method: "POST",
    path: "/media/uploads",
    body,
    schema: uploadTicketSchema,
    signal,
  });
}

/** Step 3: the server checks size, checksum and the real content type. */
export function completeUpload(
  uploadId: string,
  signal?: AbortSignal,
): Promise<MediaAsset> {
  return apiRequest({
    method: "POST",
    path: `/media/uploads/${encodeURIComponent(uploadId)}/complete`,
    schema: mediaAssetSchema,
    signal,
  });
}
