import { HttpResponse, http } from "msw";
import type {
  PublicFeatureCollection,
  PublicIssueDetail,
  PublicIssueItem,
  Scorecard,
  SupportState,
} from "@/lib/api";
import { API } from "./msw";

/*
 * Builders and MSW handlers for community support and the public tracker
 * (docs/api/community-public.md). Synthetic data only.
 */

export const PUBLIC = `${API}/public/demo-city`;

const category = {
  id: "cat-pothole",
  code: "pothole",
  name_i18n: { en: "Pothole", hi: "गड्ढा" },
  icon: "construction",
};

export function makePublicIssue(
  overrides: Partial<PublicIssueItem> = {},
): PublicIssueItem {
  return {
    id: "iss-1",
    reference: "CP-26-000123",
    status: "in_progress",
    category,
    ward: { id: "ward-3", name: "Ward 3 (synthetic)" },
    location: { lat: 12.9716, lng: 77.5946, precision_m: 175 },
    report_count: 3,
    support_count: 5,
    thumb_url: "http://storage.test/public-thumb-1.webp",
    created_at: "2026-11-20T08:15:00+05:30",
    updated_at: "2026-11-23T10:00:00+05:30",
    resolved_at: null,
    age_days: 4.2,
    ...overrides,
  };
}

export function makePublicDetail(
  overrides: Partial<PublicIssueDetail> = {},
): PublicIssueDetail {
  return {
    ...makePublicIssue(),
    timeline: [
      {
        at: "2026-11-20T08:15:01+05:30",
        type: "created",
        from_status: null,
        to_status: "reported",
        public_note: null,
      },
    ],
    before_photos: [
      {
        thumb_url: "http://storage.test/before-thumb.webp",
        display_url: "http://storage.test/before.webp",
      },
    ],
    after_photos: [],
    merged_into: null,
    merged_into_id: null,
    ...overrides,
  };
}

export function makeFeatures(
  items: PublicIssueItem[] = [makePublicIssue()],
): PublicFeatureCollection {
  return {
    type: "FeatureCollection",
    truncated: false,
    features: items.map((item) => ({
      type: "Feature",
      geometry: {
        type: "Point",
        coordinates: [item.location.lng, item.location.lat],
      },
      properties: {
        id: item.id,
        reference: item.reference,
        status: item.status,
        category_code: item.category.code,
        report_count: item.report_count,
        support_count: item.support_count,
      },
    })),
  };
}

export function makeScorecard(): Scorecard {
  return {
    wards: [
      {
        ward: { id: "ward-1", name: "Ward 1 (synthetic)" },
        open_count: 4,
        resolved_count: 6,
        median_resolution_days: 3.5,
      },
      {
        ward: { id: "ward-3", name: "Ward 3 (synthetic)" },
        open_count: 2,
        resolved_count: 0,
        median_resolution_days: null,
      },
    ],
  };
}

/** The public tracker's endpoints, answering with the given issues. */
export function publicHandlers(items: PublicIssueItem[] = [makePublicIssue()]) {
  return [
    http.get(`${PUBLIC}/issues`, () =>
      HttpResponse.json({
        items,
        total: items.length,
        limit: 20,
        offset: 0,
      }),
    ),
    http.get(`${PUBLIC}/issues/geojson`, () =>
      HttpResponse.json(makeFeatures(items)),
    ),
    http.get(`${PUBLIC}/scorecard`, () => HttpResponse.json(makeScorecard())),
  ];
}

/**
 * Support endpoints backed by a little in-memory state, so a toggle sees
 * its own result. `fail` makes POST and DELETE refuse with that code.
 */
export function supportHandlers(
  initial: { count: number; supported: boolean },
  options: { fail?: { status: number; code: string } } = {},
) {
  const state = { ...initial };
  const body = (issueId: string): SupportState => ({
    issue_id: issueId,
    support_count: state.count,
    supported: state.supported,
  });
  const refuse = (fail: { status: number; code: string }) =>
    apiError(fail.status, fail.code);
  return [
    http.get(`${API}/issues/:id/support`, ({ params }) =>
      HttpResponse.json(body(String(params.id))),
    ),
    http.post(`${API}/issues/:id/support`, ({ params }) => {
      if (options.fail) return refuse(options.fail);
      if (!state.supported) state.count += 1;
      state.supported = true;
      return HttpResponse.json(body(String(params.id)));
    }),
    http.delete(`${API}/issues/:id/support`, ({ params }) => {
      if (options.fail) return refuse(options.fail);
      if (state.supported) state.count -= 1;
      state.supported = false;
      return HttpResponse.json(body(String(params.id)));
    }),
  ];
}

export function apiError(status: number, code: string) {
  return HttpResponse.json(
    { error: { code, message: "Refused", details: {} } },
    { status },
  );
}
