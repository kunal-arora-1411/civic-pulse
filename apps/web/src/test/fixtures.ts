import type {
  AdminUser,
  CurrentUser,
  Tenant,
  TokenResponse,
} from "@/lib/api/schemas";
import type {
  Category,
  IssueDetail,
  IssueListItem,
  Report,
} from "@/lib/api/schemas-phase1";

/** Builders for API payloads used across tests. Synthetic data only. */
export function makeUser(overrides: Partial<CurrentUser> = {}): CurrentUser {
  return {
    id: "00000000-0000-4000-8000-000000000005",
    tenant_id: "00000000-0000-4000-8000-0000000000aa",
    phone: "+919000000005",
    email: null,
    display_name: "Asha",
    locale: "en",
    preferences: {},
    mfa_enabled: false,
    is_staff: false,
    roles: [{ role: "citizen", department_id: null, jurisdiction_id: null }],
    permissions: ["report:create", "report:read_own"],
    ...overrides,
  };
}

export function makeAdmin(overrides: Partial<CurrentUser> = {}): CurrentUser {
  return makeUser({
    id: "00000000-0000-4000-8000-000000000001",
    phone: "+919000000001",
    display_name: "Meera Admin",
    is_staff: true,
    mfa_enabled: true,
    roles: [
      { role: "municipal_admin", department_id: null, jurisdiction_id: null },
    ],
    permissions: ["user:manage", "audit:read", "config:read", "config:manage"],
    ...overrides,
  });
}

export function makeAdminUser(overrides: Partial<AdminUser> = {}): AdminUser {
  return {
    ...makeUser(),
    is_active: true,
    created_at: "2026-11-01T09:30:00Z",
    ...overrides,
  };
}

export function makeTokenResponse(
  user: CurrentUser = makeUser(),
  accessToken = "access-1",
): TokenResponse {
  return {
    access_token: accessToken,
    token_type: "bearer",
    expires_in: 900,
    refresh_token: "refresh-1",
    user,
  };
}

export function makeTenant(overrides: Partial<Tenant> = {}): Tenant {
  return {
    id: "00000000-0000-4000-8000-0000000000aa",
    slug: "demo-city",
    name: "Demo City",
    default_locale: "en",
    supported_locales: ["en", "hi"],
    map: {
      center: [77.5946, 12.9716],
      zoom: 12,
      bounds: [77.5, 12.9, 77.7, 13.05],
    },
    ...overrides,
  };
}

export function makeCategory(overrides: Partial<Category> = {}): Category {
  return {
    id: "cat-pothole",
    code: "pothole",
    parent_id: null,
    name_i18n: { en: "Pothole / road damage", hi: "गड्ढा / सड़क क्षति" },
    description_i18n: { en: "Holes and broken road surface" },
    icon: "construction",
    evidence: { min_photos: 1, max_photos: 5 },
    fields: [],
    default_department_id: null,
    dedup: { radius_m: 30, window_days: 30 },
    sort_order: 10,
    is_active: true,
    ...overrides,
  };
}

const categorySummary = {
  id: "cat-pothole",
  code: "pothole",
  name_i18n: { en: "Pothole / road damage", hi: "गड्ढा / सड़क क्षति" },
  icon: "construction",
};

export function makeReport(overrides: Partial<Report> = {}): Report {
  return {
    id: "rep-1",
    reference: "R-26-000123",
    created_at: "2026-11-24T08:15:00+05:30",
    category: categorySummary,
    description: "Large pothole near the bus stop",
    details: { size: "large" },
    location: { lat: 12.9716, lng: 77.5946, accuracy_m: 12, source: "gps" },
    address_text: "MG Road, Shivajinagar",
    ward: { id: "ward-3", name: "Ward 3 (synthetic)" },
    media: [
      {
        id: "media-1",
        status: "ready",
        width: 1200,
        height: 1600,
        thumb_url: "http://storage.test/thumb-1.webp",
        display_url: "http://storage.test/display-1.webp",
        original_url: null,
        captured_at: null,
      },
    ],
    status: "accepted",
    issue: {
      id: "iss-1",
      reference: "CP-26-000123",
      status: "reported",
      timeline: [
        {
          at: "2026-11-24T08:15:01+05:30",
          type: "created",
          from_status: null,
          to_status: "reported",
          public_note: null,
        },
      ],
    },
    reporter: null,
    ...overrides,
  };
}

export function makeIssue(
  overrides: Partial<IssueListItem> = {},
): IssueListItem {
  return {
    id: "iss-1",
    reference: "CP-26-000123",
    status: "reported",
    category: categorySummary,
    location: { lat: 12.9716, lng: 77.5946 },
    address_text: "MG Road, Shivajinagar",
    ward: { id: "ward-3", name: "Ward 3 (synthetic)" },
    report_count: 1,
    unique_reporter_count: 1,
    severity: null,
    priority: null,
    thumb_url: null,
    created_at: "2026-11-20T10:00:00+05:30",
    updated_at: "2026-11-20T10:00:00+05:30",
    version: 3,
    ...overrides,
  };
}

export function makeIssueDetail(
  overrides: Partial<IssueDetail> = {},
): IssueDetail {
  const { issue: _issue, ...report } = makeReport({
    reporter: { id: "user-5", display_name: "Asha" },
  });
  return {
    ...makeIssue(),
    reports: [report],
    timeline: [
      {
        id: "ev-1",
        at: "2026-11-20T10:00:00+05:30",
        type: "created",
        from_status: null,
        to_status: "reported",
        reason: null,
        public_note: null,
        visibility: "public",
        actor: null,
      },
    ],
    allowed_transitions: [
      { to_status: "under_review", requires_reason: false },
      { to_status: "verified", requires_reason: false },
      { to_status: "rejected", requires_reason: true },
    ],
    ...overrides,
  };
}
