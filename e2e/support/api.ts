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

export type Report = {
  id: string;
  reference: string;
  view: "owner" | "staff";
  matching_status?: "pending" | "linked" | "review" | "new_issue";
  media: { id: string; status: "processing" | "ready" | "failed" }[];
  issue: {
    id: string;
    reference: string;
    status: string;
    timeline?: Record<string, unknown>[];
  };
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
    // seeded account signs in again straight after a previous run. Wait
    // exactly as long as the API says, once.
    if (challenge.status() === 429) {
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

  async categoryId(code: string): Promise<string> {
    const category = (await this.categories()).find((c) => c.code === code);
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

  async createReport(
    session: Session,
    input: {
      categoryCode: string;
      lat: number;
      lng: number;
      description: string;
      photo?: Buffer;
    },
  ): Promise<Report> {
    const mediaIds = input.photo
      ? [await this.uploadPhoto(session, input.photo)]
      : [];
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
          media_ids: mediaIds,
          client_created_at: new Date().toISOString(),
        },
      }),
      "Creating a report",
    );
    const created = (await response.json()) as Report;
    return this.waitForIssue(session, created.id);
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

  /** A raw call, for asserting on refusals. */
  raw(
    session: Session,
    method: "GET" | "PATCH",
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
