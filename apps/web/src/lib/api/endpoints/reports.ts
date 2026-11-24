import { apiRequest } from "../client";
import { type Paginated, paginated } from "../schemas";
import {
  type IssueStatus,
  type LocationSource,
  type MyReport,
  myReportSchema,
  type Report,
  type ReverseGeocode,
  reportSchema,
  reverseGeocodeSchema,
} from "../schemas-phase1";

export function reverseGeocode(
  point: { lat: number; lng: number },
  signal?: AbortSignal,
): Promise<ReverseGeocode> {
  return apiRequest({
    path: "/geo/reverse",
    query: { lat: point.lat, lng: point.lng },
    schema: reverseGeocodeSchema,
    signal,
  });
}

export type CreateReportBody = {
  category_id: string;
  description: string;
  location: {
    lat: number;
    lng: number;
    accuracy_m: number | null;
    source: LocationSource;
  };
  address_text?: string;
  details: Record<string, string | number | boolean>;
  media_ids: string[];
  client_created_at: string;
  /**
   * Phase 2: the classification whose suggestion the citizen was shown.
   * The server compares it with the chosen category to record whether
   * the suggestion was accepted or corrected (FR-021).
   */
  classification_id?: string;
};

/**
 * The key is required by the API. Generate it once per draft and send the
 * same key on every retry, so a request that reached the server before the
 * connection dropped can't create a second report.
 */
export function createReport(
  body: CreateReportBody,
  options: { idempotencyKey: string },
): Promise<Report> {
  return apiRequest({
    method: "POST",
    path: "/reports",
    body,
    schema: reportSchema,
    idempotencyKey: options.idempotencyKey,
  });
}

export function listMyReports(
  params: { limit?: number; offset?: number; status?: IssueStatus } = {},
  signal?: AbortSignal,
): Promise<Paginated<MyReport>> {
  return apiRequest({
    path: "/users/me/reports",
    query: params,
    schema: paginated(myReportSchema),
    signal,
  });
}

export function getReport(id: string, signal?: AbortSignal): Promise<Report> {
  return apiRequest({
    path: `/reports/${encodeURIComponent(id)}`,
    schema: reportSchema,
    signal,
  });
}
