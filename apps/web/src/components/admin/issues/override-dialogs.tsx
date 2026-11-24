"use client";

import { useMutation } from "@tanstack/react-query";
import { Calculator } from "lucide-react";
import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";
import { PRIORITY_STYLE } from "@/components/issues/priority-badge";
import { Alert } from "@/components/ui/alert";
import { useToast } from "@/components/ui/toast";
import { useErrorMessage } from "@/hooks/use-error-message";
import {
  type IssueDetail,
  isApiError,
  PRIORITY_BANDS,
  type PriorityBand,
  SEVERITY_LEVELS,
  type SeverityLevel,
  setIssuePriority,
  setIssueSeverity,
} from "@/lib/api";
import {
  ChoiceList,
  type ChoiceOption,
  IssueDialog,
  ReasonField,
  useApplyIssue,
  useVersionConflict,
} from "./issue-dialog";

/** Back to what the rules computed. */
const RESET = "computed";

type DialogProps = {
  issue: IssueDetail;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onReload: () => Promise<unknown>;
};

/**
 * Set the priority band by hand, or go back to the computed one (FR-043).
 * A reason is required to override: it's shown on the issue and kept in
 * the audit log with who did it and when.
 */
export function PriorityDialog({
  issue,
  open,
  onOpenChange,
  onReload,
}: DialogProps) {
  const t = useTranslations("admin.issueDetail.priorityDialog");
  const tBand = useTranslations("priority.band");
  const errorMessage = useErrorMessage();
  const apply = useApplyIssue();
  const { toast } = useToast();
  const conflict = useVersionConflict(onReload);
  const priority = issue.priority;
  const [choice, setChoice] = useState<PriorityBand | typeof RESET | null>(
    null,
  );
  const [reason, setReason] = useState("");
  const [attempted, setAttempted] = useState(false);

  useEffect(() => {
    if (!open) return;
    setChoice(null);
    setReason("");
    setAttempted(false);
  }, [open]);

  const clearing = choice === RESET;
  const reasonMissing = !clearing && !reason.trim();

  const mutation = useMutation({
    mutationFn: () =>
      setIssuePriority(issue.id, {
        band: clearing ? null : (choice as PriorityBand),
        reason: reason.trim(),
        version: issue.version,
      }),
    onSuccess: (updated) => {
      apply(updated);
      toast({
        variant: "success",
        title: clearing
          ? t("cleared", { reference: issue.reference })
          : t("changed", {
              reference: issue.reference,
              band: tBand(choice as PriorityBand),
            }),
      });
      onOpenChange(false);
    },
    onError: (error) => conflict.check(error),
  });

  const submit = () => {
    setAttempted(true);
    if (!choice || reasonMissing) return;
    mutation.mutate();
  };

  const options: ChoiceOption<PriorityBand | typeof RESET>[] = [
    ...PRIORITY_BANDS.map((band) => ({
      value: band,
      label: tBand(band),
      icon: PRIORITY_STYLE[band].icon,
      hint: priority?.computed_band === band ? t("computedHint") : undefined,
    })),
    ...(priority?.overridden
      ? [
          {
            value: RESET as typeof RESET,
            label: t("useComputed", {
              band: tBand(priority.computed_band),
            }),
            icon: Calculator,
          },
        ]
      : []),
  ];

  const serverError =
    mutation.isError &&
    !conflict.conflict &&
    !isApiError(mutation.error, "reason_required")
      ? errorMessage(mutation.error)
      : null;

  return (
    <IssueDialog
      open={open}
      onOpenChange={onOpenChange}
      title={t("title", { reference: issue.reference })}
      description={
        priority
          ? t("description", {
              band: tBand(priority.band),
              computed: tBand(priority.computed_band),
            })
          : undefined
      }
      conflict={conflict}
      submitLabel={t("submit")}
      onSubmit={submit}
      pending={mutation.isPending}
    >
      <div className="grid gap-5">
        <ChoiceList
          legend={t("legend")}
          options={options}
          value={choice}
          onChange={setChoice}
          error={attempted && !choice ? t("chooseBand") : undefined}
        />
        <ReasonField
          value={reason}
          onChange={setReason}
          required={!clearing}
          error={
            (attempted && reasonMissing) ||
            isApiError(mutation.error, "reason_required")
              ? t("reasonRequired")
              : undefined
          }
        />
        {serverError ? (
          <Alert variant="destructive" live="assertive">
            {serverError}
          </Alert>
        ) : null}
      </div>
    </IssueDialog>
  );
}

/**
 * Override the rule-based severity, or clear the override (FR-038). The
 * priority is recomputed from it.
 */
export function SeverityDialog({
  issue,
  open,
  onOpenChange,
  onReload,
}: DialogProps) {
  const t = useTranslations("admin.issueDetail.severityDialog");
  const tLevel = useTranslations("severity.level");
  const errorMessage = useErrorMessage();
  const apply = useApplyIssue();
  const { toast } = useToast();
  const conflict = useVersionConflict(onReload);
  const severity = issue.severity;
  const [choice, setChoice] = useState<SeverityLevel | typeof RESET | null>(
    null,
  );
  const [reason, setReason] = useState("");
  const [attempted, setAttempted] = useState(false);

  useEffect(() => {
    if (!open) return;
    setChoice(null);
    setReason("");
    setAttempted(false);
  }, [open]);

  const clearing = choice === RESET;
  const reasonMissing = !clearing && !reason.trim();

  const mutation = useMutation({
    mutationFn: () =>
      setIssueSeverity(issue.id, {
        severity: clearing ? null : (choice as SeverityLevel),
        reason: reason.trim(),
        version: issue.version,
      }),
    onSuccess: (updated) => {
      apply(updated);
      toast({
        variant: "success",
        title: clearing
          ? t("cleared", { reference: issue.reference })
          : t("changed", {
              reference: issue.reference,
              level: tLevel(choice as SeverityLevel),
            }),
      });
      onOpenChange(false);
    },
    onError: (error) => conflict.check(error),
  });

  const submit = () => {
    setAttempted(true);
    if (!choice || reasonMissing) return;
    mutation.mutate();
  };

  const options: ChoiceOption<SeverityLevel | typeof RESET>[] = [
    ...[...SEVERITY_LEVELS].reverse().map((level) => ({
      value: level,
      label: tLevel(level),
      hint: severity?.level === level ? t("currentHint") : undefined,
    })),
    ...(severity?.source === "override"
      ? [
          {
            value: RESET as typeof RESET,
            label: t("useRules"),
            icon: Calculator,
          },
        ]
      : []),
  ];

  const serverError =
    mutation.isError &&
    !conflict.conflict &&
    !isApiError(mutation.error, "reason_required")
      ? errorMessage(mutation.error)
      : null;

  return (
    <IssueDialog
      open={open}
      onOpenChange={onOpenChange}
      title={t("title", { reference: issue.reference })}
      description={t("description")}
      conflict={conflict}
      submitLabel={t("submit")}
      onSubmit={submit}
      pending={mutation.isPending}
    >
      <div className="grid gap-5">
        <ChoiceList
          legend={t("legend")}
          options={options}
          value={choice}
          onChange={setChoice}
          error={attempted && !choice ? t("chooseLevel") : undefined}
        />
        <ReasonField
          value={reason}
          onChange={setReason}
          required={!clearing}
          error={
            (attempted && reasonMissing) ||
            isApiError(mutation.error, "reason_required")
              ? t("reasonRequired")
              : undefined
          }
        />
        {serverError ? (
          <Alert variant="destructive" live="assertive">
            {serverError}
          </Alert>
        ) : null}
      </div>
    </IssueDialog>
  );
}
