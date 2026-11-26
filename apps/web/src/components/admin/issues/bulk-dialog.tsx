"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CircleAlert, CircleCheck } from "lucide-react";
import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Field } from "@/components/ui/field";
import { inputClasses } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { useErrorMessage } from "@/hooks/use-error-message";
import {
  ApiError,
  type BulkOutcome,
  bulkIssueAction,
  type IssueStatus,
  listTeams,
} from "@/lib/api";
import { cn } from "@/lib/utils";

/** Statuses staff may pick; the API refuses any that don't fit an issue. */
export const BULK_STATUSES: readonly IssueStatus[] = [
  "under_review",
  "verified",
  "rejected",
  "closed",
];

export type BulkSelection = {
  id: string;
  reference: string;
  version: number;
};

/**
 * One bulk action over the selected issues: choose, confirm, then a
 * result for every issue. Each issue goes through the same checks as on
 * its own page, so the summary says which were refused and why.
 */
export function BulkDialog({
  action,
  selection: liveSelection,
  onOpenChange,
  onDone,
}: {
  action: "status" | "assign" | null;
  selection: BulkSelection[];
  onOpenChange: (open: boolean) => void;
  /** Called after the batch ran, to clear the selection. */
  onDone: () => void;
}) {
  const t = useTranslations("admin.issues.bulk");
  const tStatus = useTranslations("issueStatus");
  const errorMessage = useErrorMessage();
  const queryClient = useQueryClient();
  const open = action !== null;
  const [step, setStep] = useState<"choose" | "confirm">("choose");
  const [toStatus, setToStatus] = useState<IssueStatus | "">("");
  const [teamId, setTeamId] = useState("");
  const [assigneeId, setAssigneeId] = useState("");
  const [reason, setReason] = useState("");
  const [outcome, setOutcome] = useState<BulkOutcome | null>(null);
  const [attempted, setAttempted] = useState(false);
  // Fixed when the dialog opens: the page clears its selection once the
  // batch has run, but the results still need the references.
  const [selection, setSelection] = useState<BulkSelection[]>([]);

  // biome-ignore lint/correctness/useExhaustiveDependencies: snapshot on open only
  useEffect(() => {
    if (!open) return;
    setSelection(liveSelection);
    setStep("choose");
    setToStatus("");
    setTeamId("");
    setAssigneeId("");
    setReason("");
    setOutcome(null);
    setAttempted(false);
  }, [open]);

  const teams = useQuery({
    queryKey: ["admin", "teams", "list", "active"],
    queryFn: ({ signal }) => listTeams({ is_active: true, limit: 100 }, signal),
    enabled: action === "assign",
  });
  const team = teams.data?.items.find((item) => item.id === teamId);

  const mutation = useMutation({
    mutationFn: () =>
      bulkIssueAction({
        action: action as "status" | "assign",
        items: selection.map((item) => ({
          issue_id: item.id,
          version: item.version,
        })),
        to_status: action === "status" ? (toStatus as IssueStatus) : null,
        team_id: action === "assign" ? teamId : null,
        assignee_id: action === "assign" && assigneeId ? assigneeId : null,
        reason: reason.trim() || null,
      }),
    onSuccess: (result) => {
      setOutcome(result);
      queryClient.invalidateQueries({ queryKey: ["issues"] });
      onDone();
    },
  });

  const missingChoice = action === "status" ? !toStatus : !teamId;
  const next = () => {
    setAttempted(true);
    if (missingChoice) return;
    setStep("confirm");
  };
  const target =
    action === "status"
      ? toStatus
        ? tStatus(toStatus)
        : ""
      : (team?.name ?? "");
  const references = new Map(
    selection.map((item) => [item.id, item.reference]),
  );

  const footer = outcome ? (
    <Button onClick={() => onOpenChange(false)}>{t("done")}</Button>
  ) : step === "confirm" ? (
    <>
      <Button variant="outline" onClick={() => setStep("choose")}>
        {t("back")}
      </Button>
      <Button onClick={() => mutation.mutate()} loading={mutation.isPending}>
        {t("confirm", { count: selection.length })}
      </Button>
    </>
  ) : (
    <>
      <Button variant="outline" onClick={() => onOpenChange(false)}>
        {t("cancel")}
      </Button>
      <Button onClick={next}>{t("next")}</Button>
    </>
  );

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={
        action === "assign"
          ? t("assignTitle", { count: selection.length })
          : t("statusTitle", { count: selection.length })
      }
      closeLabel={t("close")}
      footer={footer}
    >
      {outcome ? (
        <div className="grid gap-3">
          <Alert variant={outcome.failed ? "warning" : "success"} live="polite">
            {t("summary", {
              succeeded: outcome.succeeded,
              failed: outcome.failed,
            })}
          </Alert>
          <ul className="grid gap-1.5 text-sm" aria-label={t("resultsLabel")}>
            {outcome.results.map((result) => (
              <li key={result.issue_id} className="flex items-start gap-2">
                {result.ok ? (
                  <CircleCheck
                    aria-hidden="true"
                    className="mt-0.5 size-4 shrink-0 text-primary"
                  />
                ) : (
                  <CircleAlert
                    aria-hidden="true"
                    className="mt-0.5 size-4 shrink-0 text-destructive-soft-foreground"
                  />
                )}
                <span>
                  <span className="font-mono">
                    {references.get(result.issue_id) ?? result.issue_id}
                  </span>
                  {": "}
                  {result.ok
                    ? t("itemDone")
                    : errorMessage(
                        new ApiError({
                          status: 0,
                          code: result.error ?? "unknown",
                          message: "",
                        }),
                      )}
                </span>
              </li>
            ))}
          </ul>
        </div>
      ) : step === "confirm" ? (
        <div className="grid gap-3">
          <p>
            {action === "assign"
              ? t("confirmAssign", { count: selection.length, target })
              : t("confirmStatus", { count: selection.length, target })}
          </p>
          <p className="text-sm text-muted-foreground">{t("confirmHelp")}</p>
          <p className="font-mono text-xs text-muted-foreground">
            {selection.map((item) => item.reference).join(", ")}
          </p>
          {mutation.isError ? (
            <Alert variant="destructive" live="assertive">
              {errorMessage(mutation.error)}
            </Alert>
          ) : null}
        </div>
      ) : (
        <div className="grid gap-4">
          {action === "status" ? (
            <Field
              label={t("status")}
              required
              error={attempted && missingChoice ? t("chooseStatus") : undefined}
            >
              {(control) => (
                <Select
                  {...control}
                  value={toStatus}
                  onChange={(event) =>
                    setToStatus(event.target.value as IssueStatus)
                  }
                >
                  <option value="">{t("chooseStatusOption")}</option>
                  {BULK_STATUSES.map((status) => (
                    <option key={status} value={status}>
                      {tStatus(status)}
                    </option>
                  ))}
                </Select>
              )}
            </Field>
          ) : (
            <>
              <Field
                label={t("team")}
                required
                error={attempted && missingChoice ? t("chooseTeam") : undefined}
              >
                {(control) => (
                  <Select
                    {...control}
                    value={teamId}
                    onChange={(event) => {
                      setTeamId(event.target.value);
                      setAssigneeId("");
                    }}
                  >
                    <option value="">{t("chooseTeamOption")}</option>
                    {teams.data?.items.map((item) => (
                      <option key={item.id} value={item.id}>
                        {item.name}
                      </option>
                    ))}
                  </Select>
                )}
              </Field>
              {team ? (
                <Field label={t("assignee")}>
                  {(control) => (
                    <Select
                      {...control}
                      value={assigneeId}
                      onChange={(event) => setAssigneeId(event.target.value)}
                    >
                      <option value="">{t("teamOnly")}</option>
                      {team.members.map((member) => (
                        <option key={member.user.id} value={member.user.id}>
                          {member.user.display_name ?? member.user.id}
                        </option>
                      ))}
                    </Select>
                  )}
                </Field>
              ) : null}
              {teams.isError ? (
                <Alert variant="destructive">{errorMessage(teams.error)}</Alert>
              ) : null}
            </>
          )}
          <Field label={t("reason")} description={t("reasonHelp")}>
            {(control) => (
              <textarea
                {...control}
                value={reason}
                onChange={(event) => setReason(event.target.value)}
                rows={3}
                maxLength={2000}
                className={cn(inputClasses, "h-auto py-2")}
              />
            )}
          </Field>
        </div>
      )}
    </Dialog>
  );
}
