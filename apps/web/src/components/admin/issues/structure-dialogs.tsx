"use client";

import { useMutation } from "@tanstack/react-query";
import { ArrowLeft, Combine, Split } from "lucide-react";
import { useFormatter, useTranslations } from "next-intl";
import { useEffect, useId, useState } from "react";
import { CategoryIcon } from "@/components/issues/category-icon";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { useToast } from "@/components/ui/toast";
import { useErrorMessage } from "@/hooks/use-error-message";
import { useCategories, useLocalized } from "@/hooks/use-reference-data";
import {
  changeIssueCategory,
  type IssueDetail,
  type IssueListItem,
  isApiError,
  mergeIssues,
  splitIssue,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import {
  ChoiceList,
  IssueDialog,
  ReasonField,
  useApplyIssue,
  useVersionConflict,
} from "./issue-dialog";
import { IssuePicker } from "./issue-picker";

type DialogProps = {
  issue: IssueDetail;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onReload: () => Promise<unknown>;
};

function ServerError({ message }: { message: string | null }) {
  return message ? (
    <Alert variant="destructive" live="assertive">
      {message}
    </Alert>
  ) : null;
}

/**
 * Correct the category (FR-021). The backend records the correction on
 * the issue's reports, so it also becomes a label for evaluating the
 * classifier, and recomputes severity and priority.
 */
export function CategoryDialog({
  issue,
  open,
  onOpenChange,
  onReload,
}: DialogProps) {
  const t = useTranslations("admin.issueDetail.categoryDialog");
  const localized = useLocalized();
  const errorMessage = useErrorMessage();
  const apply = useApplyIssue();
  const { toast } = useToast();
  const conflict = useVersionConflict(onReload);
  const categories = useCategories();
  const [choice, setChoice] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  const [attempted, setAttempted] = useState(false);

  useEffect(() => {
    if (!open) return;
    setChoice(null);
    setReason("");
    setAttempted(false);
  }, [open]);

  const options = (categories.data ?? []).filter(
    (category) => category.id !== issue.category.id,
  );
  const chosen = options.find((category) => category.id === choice);

  const mutation = useMutation({
    mutationFn: () =>
      changeIssueCategory(issue.id, {
        category_id: choice as string,
        reason: reason.trim(),
        version: issue.version,
      }),
    onSuccess: (updated) => {
      apply(updated);
      toast({
        variant: "success",
        title: t("changed", {
          reference: issue.reference,
          category: localized(updated.category.name_i18n),
        }),
      });
      onOpenChange(false);
    },
    onError: (error) => conflict.check(error),
  });

  const submit = () => {
    setAttempted(true);
    if (!chosen || !reason.trim()) return;
    mutation.mutate();
  };

  return (
    <IssueDialog
      open={open}
      onOpenChange={onOpenChange}
      title={t("title", { reference: issue.reference })}
      description={t("description", {
        category: localized(issue.category.name_i18n),
      })}
      conflict={conflict}
      submitLabel={t("submit")}
      onSubmit={submit}
      pending={mutation.isPending}
    >
      <div className="grid gap-5">
        <ChoiceList
          legend={t("legend")}
          value={choice}
          onChange={setChoice}
          error={attempted && !chosen ? t("chooseCategory") : undefined}
          options={options.map((category) => ({
            value: category.id,
            label: (
              <span className="inline-flex items-center gap-2">
                <CategoryIcon icon={category.icon} className="size-4" />
                {localized(category.name_i18n)}
              </span>
            ),
          }))}
        />
        <ReasonField
          value={reason}
          onChange={setReason}
          error={
            (attempted && !reason.trim()) ||
            isApiError(mutation.error, "reason_required")
              ? t("reasonRequired")
              : undefined
          }
        />
        <ServerError
          message={
            mutation.isError &&
            !conflict.conflict &&
            !isApiError(mutation.error, "reason_required")
              ? errorMessage(mutation.error)
              : null
          }
        />
      </div>
    </IssueDialog>
  );
}

/**
 * Merge other issues into this one (FR-033). This issue survives; the
 * others keep their reference and history but redirect here, and their
 * reports move over. It's weighty and only undone by splitting reports
 * back out, so the dialog previews the result and asks for confirmation
 * on a second step before anything is sent.
 */
export function MergeDialog({
  issue,
  open,
  onOpenChange,
  onReload,
}: DialogProps) {
  const t = useTranslations("admin.issueDetail.mergeDialog");
  const errorMessage = useErrorMessage();
  const apply = useApplyIssue();
  const { toast } = useToast();
  const conflict = useVersionConflict(onReload);
  const [sources, setSources] = useState<IssueListItem[]>([]);
  const [reason, setReason] = useState("");
  const [attempted, setAttempted] = useState(false);
  const [confirming, setConfirming] = useState(false);

  useEffect(() => {
    if (!open) return;
    setSources([]);
    setReason("");
    setAttempted(false);
    setConfirming(false);
  }, [open]);

  const moved = sources.reduce((sum, item) => sum + item.report_count, 0);
  const total = issue.report_count + moved;
  const references = sources.map((item) => item.reference).join(", ");

  const mutation = useMutation({
    mutationFn: () =>
      mergeIssues(issue.id, {
        source_issue_ids: sources.map((item) => item.id),
        reason: reason.trim(),
        version: issue.version,
      }),
    onSuccess: (updated) => {
      apply(updated);
      toast({
        variant: "success",
        title: t("merged", {
          count: sources.length,
          reference: issue.reference,
        }),
      });
      onOpenChange(false);
    },
    onError: (error) => {
      conflict.check(error);
      // Back to the form, where the problem can be fixed.
      if (!isApiError(error, "version_conflict")) setConfirming(false);
    },
  });

  const next = () => {
    setAttempted(true);
    if (sources.length === 0 || !reason.trim()) return;
    setConfirming(true);
  };

  const serverError =
    mutation.isError && !conflict.conflict
      ? isApiError(mutation.error, "invalid_merge")
        ? t("invalidMerge")
        : errorMessage(mutation.error)
      : null;

  return (
    <IssueDialog
      wide
      open={open}
      onOpenChange={onOpenChange}
      title={
        confirming
          ? t("confirmTitle", {
              count: sources.length,
              reference: issue.reference,
            })
          : t("title", { reference: issue.reference })
      }
      description={
        confirming
          ? undefined
          : t("description", { reference: issue.reference })
      }
      conflict={conflict}
      submitLabel={
        confirming ? (
          <>
            <Combine aria-hidden="true" />
            {t("confirm", { count: sources.length })}
          </>
        ) : (
          t("next")
        )
      }
      submitVariant={confirming ? "destructive" : "primary"}
      onSubmit={confirming ? () => mutation.mutate() : next}
      pending={mutation.isPending}
      secondary={
        confirming ? (
          <Button
            variant="outline"
            onClick={() => setConfirming(false)}
            disabled={mutation.isPending}
          >
            <ArrowLeft aria-hidden="true" className="rtl:rotate-180" />
            {t("back")}
          </Button>
        ) : undefined
      }
    >
      {confirming ? (
        <div className="grid gap-4">
          <Alert variant="warning" live="polite" title={t("confirmLead")}>
            <ul className="mt-1 list-disc ps-5">
              <li>
                {t("confirmMoves", { count: moved, sources: references })}
              </li>
              <li>
                {t("confirmTotal", { total, reference: issue.reference })}
              </li>
              <li>{t("confirmRedirect", { sources: references })}</li>
              <li>{t("confirmCitizens")}</li>
              <li>{t("confirmUndo")}</li>
            </ul>
          </Alert>
          <p className="text-sm">
            <span className="font-semibold">{t("reasonLabel")}: </span>
            {reason.trim()}
          </p>
          <ServerError message={serverError} />
        </div>
      ) : (
        <div className="grid gap-5">
          <IssuePicker
            multiple
            label={t("pickLabel")}
            excludeIds={[issue.id]}
            selected={sources}
            onChange={setSources}
            error={
              attempted && sources.length === 0 ? t("pickRequired") : undefined
            }
          />
          {sources.length > 0 ? (
            <output className="rounded-lg border border-border bg-muted/60 p-3 text-sm">
              {t("preview", {
                reference: issue.reference,
                total,
                moved,
                count: sources.length,
              })}
            </output>
          ) : null}
          <ReasonField
            value={reason}
            onChange={setReason}
            error={
              attempted && !reason.trim() ? t("reasonRequired") : undefined
            }
          />
          <ServerError message={serverError} />
        </div>
      )}
    </IssueDialog>
  );
}

type SplitTargetChoice = "new" | "existing";

/**
 * Move some of this issue's reports to a new issue or another existing
 * one (FR-034). At least one report has to stay: the dialog says so as
 * soon as every report is ticked, and won't send it.
 */
export function SplitDialog({
  issue,
  open,
  onOpenChange,
  onReload,
}: DialogProps) {
  const t = useTranslations("admin.issueDetail.splitDialog");
  const format = useFormatter();
  const errorMessage = useErrorMessage();
  const apply = useApplyIssue();
  const { toast } = useToast();
  const conflict = useVersionConflict(onReload);
  const errorId = useId();
  const [picked, setPicked] = useState<string[]>([]);
  const [target, setTarget] = useState<SplitTargetChoice>("new");
  const [existing, setExisting] = useState<IssueListItem[]>([]);
  const [reason, setReason] = useState("");
  const [attempted, setAttempted] = useState(false);

  useEffect(() => {
    if (!open) return;
    setPicked([]);
    setTarget("new");
    setExisting([]);
    setReason("");
    setAttempted(false);
  }, [open]);

  const emptying = picked.length > 0 && picked.length >= issue.reports.length;
  const noneSelected = picked.length === 0;
  const targetMissing = target === "existing" && existing.length === 0;

  const mutation = useMutation({
    mutationFn: () =>
      splitIssue(issue.id, {
        report_ids: picked,
        target:
          target === "new" ? { new_issue: true } : { issue_id: existing[0].id },
        reason: reason.trim(),
        version: issue.version,
      }),
    onSuccess: ({ source, target: moved }) => {
      apply(source);
      apply(moved);
      toast({
        variant: "success",
        title: t("split", {
          count: picked.length,
          reference: moved.reference,
        }),
      });
      onOpenChange(false);
    },
    onError: (error) => conflict.check(error),
  });

  const submit = () => {
    setAttempted(true);
    if (noneSelected || emptying || targetMissing || !reason.trim()) return;
    mutation.mutate();
  };

  const serverError =
    mutation.isError && !conflict.conflict
      ? isApiError(mutation.error, "cannot_empty_issue")
        ? t("keepOne")
        : errorMessage(mutation.error)
      : null;

  return (
    <IssueDialog
      wide
      open={open}
      onOpenChange={onOpenChange}
      title={t("title", { reference: issue.reference })}
      description={t("description")}
      conflict={conflict}
      submitLabel={
        <>
          <Split aria-hidden="true" />
          {t("submit", { count: picked.length })}
        </>
      }
      onSubmit={submit}
      pending={mutation.isPending}
    >
      <div className="grid gap-5">
        <fieldset
          className="grid gap-2"
          aria-describedby={
            emptying || (attempted && noneSelected) ? errorId : undefined
          }
        >
          <legend className="mb-1 text-sm font-semibold">
            {t("reportsLegend")}
          </legend>
          {issue.reports.map((report) => {
            const checked = picked.includes(report.id);
            return (
              <label
                key={report.id}
                className={cn(
                  "flex cursor-pointer items-start gap-3 rounded-lg border px-3 py-2.5 has-focus-visible:ring-3 has-focus-visible:ring-ring/30",
                  checked
                    ? "border-primary bg-primary-soft"
                    : "border-input hover:bg-muted",
                )}
              >
                <input
                  type="checkbox"
                  checked={checked}
                  onChange={() =>
                    setPicked((current) =>
                      checked
                        ? current.filter((id) => id !== report.id)
                        : [...current, report.id],
                    )
                  }
                  className="mt-0.5 size-4 shrink-0 cursor-pointer accent-primary"
                />
                <span className="grid min-w-0 gap-0.5">
                  <span className="font-mono text-sm font-semibold">
                    {report.reference}
                  </span>
                  <span className="text-xs text-muted-foreground">
                    {report.reporter?.display_name || t("anonymous")} ·{" "}
                    {format.dateTime(new Date(report.created_at), {
                      dateStyle: "medium",
                    })}
                  </span>
                  {report.description ? (
                    <span className="line-clamp-2 text-sm">
                      {report.description}
                    </span>
                  ) : null}
                </span>
              </label>
            );
          })}
          {emptying || (attempted && noneSelected) ? (
            <p
              id={errorId}
              role={emptying ? "alert" : undefined}
              className="text-sm font-medium text-destructive-soft-foreground"
            >
              {emptying ? t("keepOne") : t("pickReports")}
            </p>
          ) : null}
        </fieldset>

        <ChoiceList
          legend={t("targetLegend")}
          value={target}
          onChange={setTarget}
          options={[
            { value: "new", label: t("targetNew") },
            { value: "existing", label: t("targetExisting") },
          ]}
        />
        {target === "existing" ? (
          <IssuePicker
            label={t("pickTarget")}
            excludeIds={[issue.id]}
            selected={existing}
            onChange={setExisting}
            error={attempted && targetMissing ? t("targetRequired") : undefined}
          />
        ) : null}

        <ReasonField
          value={reason}
          onChange={setReason}
          error={attempted && !reason.trim() ? t("reasonRequired") : undefined}
        />
        <ServerError message={serverError} />
      </div>
    </IssueDialog>
  );
}
