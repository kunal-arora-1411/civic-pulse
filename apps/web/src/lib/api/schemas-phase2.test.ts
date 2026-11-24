import { describe, expect, it } from "vitest";
import {
  classificationSchema,
  issueDetailSchema,
  issueListItemSchema,
  myReportSchema,
  reportSchema,
  reviewTaskSchema,
} from "@/lib/api";
import { makeIssue, makeIssueDetail, makeReport } from "@/test/fixtures";

const signals = {
  distance_m: 18.4,
  radius_m: 30,
  geo: 0.54,
  visual: 0.91,
  same_photo: false,
  category: 1,
  time: 0.93,
  age_days: 2.1,
  weights: { geo: 0.4, visual: 0.4, category: 0.1, time: 0.1 },
  thresholds: { auto: 0.85, review: 0.6, visual_min: 0.8 },
  reason: null,
};

describe("Phase 2 schemas", () => {
  it("accepts a report whose matching is still pending, with no issue yet", () => {
    const parsed = reportSchema.parse({
      ...makeReport(),
      matching_status: "pending",
      issue: null,
    });
    expect(parsed.issue).toBeNull();
    expect(parsed.matching_status).toBe("pending");
  });

  it("still accepts a Phase 1 report without matching fields", () => {
    const parsed = reportSchema.parse(makeReport());
    expect(parsed.matching_status).toBeUndefined();
    expect(parsed.issue?.reference).toBe("CP-26-000123");
  });

  it("accepts my-reports items whose issue isn't known yet", () => {
    const parsed = myReportSchema.parse({
      id: "rep-1",
      reference: "R-26-000123",
      created_at: "2026-11-24T02:45:00Z",
      category: { id: "c", code: "pothole", name_i18n: { en: "Pothole" } },
      issue: null,
      matching_status: "review",
    });
    expect(parsed.issue).toBeNull();
  });

  it("parses severity and priority objects on issues", () => {
    const parsed = issueListItemSchema.parse({
      ...makeIssue(),
      severity: { level: "high", source: "rule" },
      priority: {
        score: 67.5,
        band: "high",
        computed_band: "high",
        overridden: false,
        override_reason: null,
      },
    });
    expect(parsed.priority?.band).toBe("high");
    expect(parsed.severity?.level).toBe("high");
  });

  it("parses priority factors, match decisions and related issues on the detail", () => {
    const base = makeIssueDetail();
    const parsed = issueDetailSchema.parse({
      ...base,
      priority: {
        score: 67.5,
        band: "critical",
        computed_band: "high",
        overridden: true,
        override_reason: "Next to the school gate",
        factors: [
          {
            factor: "severity",
            value: "high",
            normalized: 0.75,
            points: 30,
            explanation_key: "priority.severity",
          },
        ],
      },
      reports: base.reports.map((report) => ({
        ...report,
        matching_status: "linked",
        match: {
          match_decision_id: "md-1",
          decision: "auto_linked",
          score: 0.9,
          signals,
        },
        match_decisions: [
          {
            id: "md-1",
            candidate_issue: { id: "iss-1", reference: "CP-26-000123" },
            rank: 1,
            score: 0.9,
            signals,
            decision: "auto_linked",
            decided_by: null,
            decided_at: "2026-11-24T02:45:00Z",
            feedback: null,
          },
        ],
      })),
      related: [{ issue: makeIssue({ id: "iss-2" }), note: "Same junction" }],
    });
    expect(parsed.priority?.factors?.[0].points).toBe(30);
    expect(parsed.reports[0].match_decisions[0].signals.visual).toBe(0.91);
    expect(parsed.related[0].note).toBe("Same junction");
  });

  it("defaults a pending classification's flags and suggestions", () => {
    expect(classificationSchema.parse({ id: "c1", status: "pending" })).toEqual(
      {
        id: "c1",
        status: "pending",
        suggestions: [],
        not_civic: false,
        needs_manual: false,
      },
    );
  });

  it("parses a review task with a null visual signal", () => {
    const { issue: _issue, ...report } = makeReport();
    const parsed = reviewTaskSchema.parse({
      id: "rt-1",
      created_at: "2026-11-24T02:45:00Z",
      report: { ...report, view: "staff", matching_status: "review" },
      candidates: [
        {
          match_decision_id: "md-2",
          score: 0.62,
          signals: { ...signals, visual: null, reason: "ai_unavailable" },
          issue: makeIssue(),
        },
      ],
    });
    expect(parsed.candidates[0].signals.visual).toBeNull();
    expect(parsed.status).toBe("open");
  });
});
