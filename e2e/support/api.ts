import { createHash, randomInt, randomUUID } from "node:crypto";
import type { APIRequestContext, APIResponse } from "@playwright/test";
import { API_URL, DEV_OTP, TENANT } from "./env";

/*
 * A thin client for arranging test data and checking results through the
 * API directly. The UI is what the tests exercise; this is for the parts
 * of a scenario that aren't under test (a report that already exists, a
 * second account), and for assertions the UI can't make, such as "exactly
 * one report was created".
 */

export type Session = {
  phone: string;
  accessToken: string;
  refreshToken: string;
  user: { id: string; display_name: string | null };
};

export type Category = { id: string; code: string };

export type MatchingStatus = "pending" | "linked" | "review" | "new_issue";

export type Signals = {
  distance_m: number;
  radius_m: number;
  visual: number | null;
  same_photo: boolean;
  thresholds: { auto: number; review: number; visual_min: number };
  reason: string | null;
};

export type MatchDecision = {
  id: string;
  candidate_issue_id: string;
  rank: number;
  score: number;
  signals: Signals;
  decision:
    | "auto_linked"
    | "sent_to_review"
    | "rejected_candidate"
    | "chosen_by_reviewer"
    | "not_chosen";
};

export type Report = {
  id: string;
  reference: string;
  view: "owner" | "staff";
  matching_status?: MatchingStatus;
  media: { id: string; status: "processing" | "ready" | "failed" }[];
  issue: {
    id: string;
    reference: string;
    status: string;
    report_count?: number;
    unique_reporter_count?: number;
    timeline?: Record<string, unknown>[];
  };
  /** Staff view only. */
  match_decisions?: MatchDecision[];
};

/** A report that may still be waiting for matching or review. */
export type PendingReport = Omit<Report, "issue"> & {
  issue: Report["issue"] | null;
};

export type Issue = {
  id: string;
  reference: string;
  status: string;
  version: number;
  report_count: number;
  unique_reporter_count: number;
  merged_into?: { id: string; reference: string } | null;
  reports: { id: string; reference: string }[];
};

export type ReviewTask = {
  id: string;
  status: "open" | "resolved";
  report: { id: string; reference: string };
  candidates: {
    match_decision_id: string;
    score: number;
    signals: Signals;
    issue: { id: string; reference: string };
  }[];
};

type ReportInput = {
  categoryCode: string;
  lat: number;
  lng: number;
  description: string;
  photo?: Buffer;
};

export type ApiErrorBody = {
  error: { code: string; message: string; details: Record<string, unknown> };
};

/**
 * A new citizen number for each test. Unknown numbers become citizen
 * accounts on first sign-in, so tests never share an account, its report
 * list or its OTP rate limits.
 */
export function freshCitizenPhone(): string {
  return `+9198${String(randomInt(0, 100_000_000)).padStart(8, "0")}`;
}

const url = (path: string) => `${API_URL}/api/v1${path}`;

async function expectOk(response: APIResponse, what: string) {
  if (!response.ok()) {
    throw new Error(
      `${what} failed: ${response.status()} ${await response.text()}`,
    );
  }
  return response;
}

export class Api {
  constructor(private readonly request: APIRequestContext) {}

  private bearer(session: Session) {
    return { Authorization: `Bearer ${session.accessToken}` };
  }

  /** Phone OTP sign-in with the development code. */
  async login(phone: string): Promise<Session> {
    let challenge = await this.request.post(url("/auth/otp/request"), {
      headers: { "X-Tenant": TENANT },
      data: { phone },
    });
    // The per-phone resend cooldown (30 s) can still be running when a
    // seeded account signed in moments ago, here or in a parallel test.
    // Wait exactly as long as the API says, a few times at most.
    for (
      let attempt = 0;
      attempt < 3 && challenge.status() === 429;
      attempt++
    ) {
      const body = (await challenge.json()) as ApiErrorBody;
      const wait = Number(body.error.details.retry_after ?? 0);
      if (body.error.code !== "rate_limited" || wait > 35) {
        throw new Error(
          `OTP request for ${phone} was rate limited for ${wait} s. See "Running the e2e suite" in the README.`,
        );
      }
      await new Promise((resolve) => setTimeout(resolve, wait * 1000 + 250));
      challenge = await this.request.post(url("/auth/otp/request"), {
        headers: { "X-Tenant": TENANT },
        data: { phone },
      });
    }
    await expectOk(challenge, `OTP request for ${phone}`);
    const { challenge_id } = (await challenge.json()) as {
      challenge_id: string;
    };
    const verified = await expectOk(
      await this.request.post(url("/auth/otp/verify"), {
        data: { challenge_id, code: DEV_OTP },
      }),
      `OTP verify for ${phone}`,
    );
    const body = (await verified.json()) as {
      access_token?: string;
      refresh_token?: string;
      user?: Session["user"];
      mfa_required?: boolean;
    };
    if (!body.access_token || !body.refresh_token || !body.user) {
      throw new Error(
        `Sign-in for ${phone} needs MFA; run the stack with REQUIRE_STAFF_MFA=false.`,
      );
    }
    return {
      phone,
      accessToken: body.access_token,
      refreshToken: body.refresh_token,
      user: body.user,
    };
  }

  async categories(): Promise<Category[]> {
    const response = await expectOk(
      await this.request.get(url("/categories"), {
        headers: { "X-Tenant": TENANT },
      }),
      "Listing categories",
    );
    return (await response.json()) as Category[];
  }

  private categoryList?: Promise<Category[]>;

  async categoryId(code: string): Promise<string> {
    this.categoryList ??= this.categories();
    const category = (await this.categoryList).find((c) => c.code === code);
    if (!category) throw new Error(`No category "${code}"`);
    return category.id;
  }

  /** The three-step upload: ticket, PUT to storage, complete. */
  async uploadPhoto(session: Session, bytes: Buffer): Promise<string> {
    const ticketResponse = await expectOk(
      await this.request.post(url("/media/uploads"), {
        headers: this.bearer(session),
        data: {
          purpose: "report_evidence",
          content_type: "image/jpeg",
          size_bytes: bytes.length,
          checksum_sha256: createHash("sha256").update(bytes).digest("hex"),
        },
      }),
      "Creating an upload",
    );
    const ticket = (await ticketResponse.json()) as {
      upload_id: string;
      url: string;
      headers: Record<string, string>;
    };
    await expectOk(
      await this.request.put(ticket.url, {
        headers: ticket.headers,
        data: bytes,
      }),
      "Uploading to storage",
    );
    const completed = await expectOk(
      await this.request.post(
        url(`/media/uploads/${ticket.upload_id}/complete`),
        { headers: this.bearer(session) },
      ),
      "Completing the upload",
    );
    return ((await completed.json()) as { id: string }).id;
  }

  async createReport(session: Session, input: ReportInput): Promise<Report> {
    const created = await this.submitReport(session, input);
    return this.waitForIssue(session, created.id);
  }

  /** Sends a report and returns at once, before matching has run. */
  async submitReport(
    session: Session,
    input: ReportInput,
  ): Promise<PendingReport> {
    const mediaIds = input.photo
      ? [await this.uploadPhoto(session, input.photo)]
      : [];
    return this.postReport(session, { ...input, mediaIds });
  }

  /** `POST /reports` with photos that are already uploaded. */
  async postReport(
    session: Session,
    input: Omit<ReportInput, "photo"> & { mediaIds: string[] },
  ): Promise<PendingReport> {
    const response = await expectOk(
      await this.request.post(url("/reports"), {
        headers: { ...this.bearer(session), "Idempotency-Key": randomUUID() },
        data: {
          category_id: await this.categoryId(input.categoryCode),
          description: input.description,
          location: {
            lat: input.lat,
            lng: input.lng,
            accuracy_m: 8,
            source: "gps",
          },
          details: {},
          media_ids: input.mediaIds,
          client_created_at: new Date().toISOString(),
        },
      }),
      "Creating a report",
    );
    return (await response.json()) as PendingReport;
  }

  /**
   * Waits until matching has decided (linked, new issue or sent to
   * review), whichever it is.
   */
  async waitForMatching(
    session: Session,
    id: string,
    timeoutMs = 90_000,
  ): Promise<PendingReport> {
    const deadline = Date.now() + timeoutMs;
    for (;;) {
      const report = await this.getReport(session, id);
      if (report.matching_status !== "pending") return report;
      if (Date.now() > deadline) {
        throw new Error(
          `Report ${id} was still being matched after ${timeoutMs} ms`,
        );
      }
      await new Promise((resolve) => setTimeout(resolve, 500));
    }
  }

  /**
   * Reports are matched asynchronously (Phase 2): `issue` is null until the
   * AI worker links the report or opens a new issue for it.
   */
  async waitForIssue(
    session: Session,
    id: string,
    timeoutMs = 60_000,
  ): Promise<Report> {
    const deadline = Date.now() + timeoutMs;
    for (;;) {
      const report = await this.getReport(session, id);
      if (report.issue) return report;
      if (Date.now() > deadline) {
        throw new Error(
          `Report ${id} still has no issue after ${timeoutMs} ms (matching_status: ${report.matching_status})`,
        );
      }
      await new Promise((resolve) => setTimeout(resolve, 500));
    }
  }

  async getReport(session: Session, id: string): Promise<Report> {
    const response = await expectOk(
      await this.request.get(url(`/reports/${id}`), {
        headers: this.bearer(session),
      }),
      "Reading a report",
    );
    return (await response.json()) as Report;
  }

  /** Staff: the issue detail. */
  async getIssue(session: Session, id: string): Promise<Issue> {
    const response = await expectOk(
      await this.request.get(url(`/issues/${id}`), {
        headers: this.bearer(session),
      }),
      "Reading an issue",
    );
    return (await response.json()) as Issue;
  }

  /** Staff: the open review task for a report, if there is one. */
  async reviewTaskFor(
    session: Session,
    reportId: string,
  ): Promise<ReviewTask | undefined> {
    const response = await expectOk(
      await this.request.get(url("/review-tasks"), {
        headers: this.bearer(session),
        params: { status: "open", limit: 100 },
      }),
      "Listing review tasks",
    );
    const page = (await response.json()) as { items: ReviewTask[] };
    return page.items.find((task) => task.report.id === reportId);
  }

  async resolveReview(
    session: Session,
    taskId: string,
    action: { action: "link"; issue_id: string } | { action: "new_issue" },
  ): Promise<void> {
    await expectOk(
      await this.request.post(url(`/review-tasks/${taskId}/resolve`), {
        headers: this.bearer(session),
        data: action,
      }),
      "Resolving a review task",
    );
  }

  /** Staff: the AI models the API has registered, newest first. */
  async aiModels(session: Session) {
    const response = await expectOk(
      await this.request.get(url("/admin/ai/models"), {
        headers: this.bearer(session),
      }),
      "Listing AI models",
    );
    return (
      (await response.json()) as {
        items: { model_id: string; task: string; active: boolean }[];
      }
    ).items;
  }

  /** Municipal admin: a new staff account in the tenant. */
  async createStaff(
    session: Session,
    role: "operator" | "municipal_admin" | "supervisor" | "field_worker",
    displayName: string,
  ): Promise<string> {
    const phone = freshCitizenPhone().replace(/^\+9198/, "+9197");
    await expectOk(
      await this.request.post(url("/admin/users"), {
        headers: { ...this.bearer(session), "Idempotency-Key": randomUUID() },
        data: { phone, display_name: displayName, roles: [{ role }] },
      }),
      `Creating a ${role}`,
    );
    return phone;
  }

  async myReports(session: Session) {
    const response = await expectOk(
      await this.request.get(url("/users/me/reports"), {
        headers: this.bearer(session),
        params: { limit: 100 },
      }),
      "Listing my reports",
    );
    return (await response.json()) as {
      total: number;
      items: { id: string; reference: string }[];
    };
  }

  /** A JSON call that must succeed, for arranging staff-side steps. */
  async send<T>(
    session: Session,
    method: "GET" | "POST" | "PATCH",
    path: string,
    data?: unknown,
  ): Promise<T> {
    const response = await expectOk(
      await this.raw(session, method, path, data),
      `${method} ${path}`,
    );
    return (await response.json()) as T;
  }

  /** A raw call, for asserting on refusals. */
  raw(
    session: Session,
    method: "GET" | "POST" | "PATCH",
    path: string,
    data?: unknown,
  ): Promise<APIResponse> {
    return this.request.fetch(url(path), {
      method,
      headers: this.bearer(session),
      data,
    });
  }
}
