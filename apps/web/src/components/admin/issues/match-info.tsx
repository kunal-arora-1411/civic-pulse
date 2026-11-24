"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Bot,
  ChevronDown,
  CirclePlus,
  ThumbsDown,
  ThumbsUp,
  UserCheck,
} from "lucide-react";
import { useFormatter, useTranslations } from "next-intl";
import { useState } from "react";
import { SignalBreakdown } from "@/components/admin/review/signal-breakdown";
import { Button } from "@/components/ui/button";
import { useErrorMessage } from "@/hooks/use-error-message";
import {
  type IssueDetail,
  type MatchDecision,
  type MatchFeedback,
  type StaffReport,
  sendMatchFeedback,
} from "@/lib/api";

/** The decision that put this report on this issue, if one did. */
export function placingDecision(
  report: StaffReport,
  issueId: string,
): MatchDecision | null {
  return (
    report.match_decisions.find(
      (decision) =>
        decision.candidate_issue.id === issueId &&
        (decision.decision === "auto_linked" ||
          decision.decision === "chosen_by_reviewer"),
    ) ?? null
  );
}

/**
 * How a report got onto this issue: linked automatically, linked by a
 * reviewer, or the report that started it, with the reasoning behind a
 * disclosure. Automatic links can be marked right or wrong (FR-035), so
 * the auto-link threshold can be judged on real outcomes.
 */
export function MatchInfo({
  report,
  issue,
  canGiveFeedback,
}: {
  report: StaffReport;
  issue: IssueDetail;
  canGiveFeedback: boolean;
}) {
  const t = useTranslations("admin.issueDetail.match");
  const format = useFormatter();
  const errorMessage = useErrorMessage();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [given, setGiven] = useState<MatchFeedback | null>(null);
  const decision = placingDecision(report, issue.id);
  const n2 = (value: number) =>
    format.number(value, {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    });

  const feedback = useMutation({
    mutationFn: (correct: boolean) =>
      sendMatchFeedback((decision as MatchDecision).id, { correct }),
    onSuccess: (_, correct) => {
      setGiven(correct ? "correct" : "incorrect");
      queryClient.invalidateQueries({
        queryKey: ["issues", "detail", issue.id],
      });
    },
  });

  if (!decision) {
    if (report.matching_status !== "new_issue") return null;
    const best = report.match_decisions[0];
    return (
      <div className="flex items-start gap-2 rounded-lg bg-muted/60 px-3 py-2 text-sm">
        <CirclePlus aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
        <p>
          {t("started")}
          {best ? (
            <span className="text-muted-foreground">
              {" "}
              {t("startedBest", {
                reference: best.candidate_issue.reference,
                score: n2(best.score),
              })}
            </span>
          ) : null}
        </p>
      </div>
    );
  }

  const auto = decision.decision === "auto_linked";
  const recorded = given ?? decision.feedback ?? null;
  const Icon = auto ? Bot : UserCheck;

  return (
    <div className="grid gap-2 rounded-lg bg-muted/60 px-3 py-2 text-sm">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="flex items-center gap-2">
          <Icon aria-hidden="true" className="size-4 shrink-0" />
          <span>
            {auto
              ? t("auto", { score: n2(decision.score) })
              : t("reviewed", {
                  name: decision.decided_by?.display_name ?? t("someone"),
                  score: n2(decision.score),
                })}
          </span>
        </p>
        <Button
          variant="ghost"
          size="sm"
          aria-expanded={open}
          onClick={() => setOpen((value) => !value)}
        >
          {open ? t("hideWhy") : t("showWhy")}
          <ChevronDown
            aria-hidden="true"
            className={
              open ? "rotate-180 transition-transform" : "transition-transform"
            }
          />
        </Button>
      </div>

      {open ? (
        <div className="rounded-lg border border-border bg-card p-3">
          <SignalBreakdown signals={decision.signals} score={decision.score} />
        </div>
      ) : null}

      {auto && canGiveFeedback ? (
        recorded ? (
          <output className="flex items-center gap-1.5 font-medium">
            {recorded === "correct" ? (
              <ThumbsUp aria-hidden="true" className="size-4" />
            ) : (
              <ThumbsDown aria-hidden="true" className="size-4" />
            )}
            {recorded === "correct" ? t("markedCorrect") : t("markedIncorrect")}
          </output>
        ) : (
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-muted-foreground">{t("feedbackAsk")}</span>
            <Button
              variant="outline"
              size="sm"
              loading={feedback.isPending && feedback.variables === true}
              disabled={feedback.isPending}
              onClick={() => feedback.mutate(true)}
            >
              <ThumbsUp aria-hidden="true" />
              {t("correct")}
            </Button>
            <Button
              variant="outline"
              size="sm"
              loading={feedback.isPending && feedback.variables === false}
              disabled={feedback.isPending}
              onClick={() => feedback.mutate(false)}
            >
              <ThumbsDown aria-hidden="true" />
              {t("incorrect")}
            </Button>
            {feedback.isError ? (
              <p
                role="alert"
                className="basis-full text-destructive-soft-foreground"
              >
                {errorMessage(feedback.error)}
              </p>
            ) : null}
          </div>
        )
      ) : null}
      {recorded === "incorrect" ? (
        <p className="text-muted-foreground">{t("incorrectHint")}</p>
      ) : null}
    </div>
  );
}
