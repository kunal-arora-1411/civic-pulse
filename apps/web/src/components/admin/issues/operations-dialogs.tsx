"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Globe, Lock, UsersRound } from "lucide-react";
import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";
import { Alert } from "@/components/ui/alert";
import { Field } from "@/components/ui/field";
import { inputClasses } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/components/ui/toast";
import { useErrorMessage } from "@/hooks/use-error-message";
import {
  addIssueNote,
  approveClosure,
  assignIssue,
  getEligibleTeams,
  type IssueDetail,
  isApiError,
  rejectClosure,
  staffReopenIssue,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import {
  ChoiceList,
  IssueDialog,
  ReasonField,
  useApplyIssue,
  useVersionConflict,
} from "./issue-dialog";

const NOTE_MAX = 2000;
/** The select value for "the team, no person yet". */
const TEAM_ONLY = "";

type DialogProps = {
  issue: IssueDetail;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onReload: () => Promise<unknown>;
};

/** Statuses an issue can be (re)assigned from (contract §2). */
export const ASSIGNABLE_STATUSES = [
  "verified",
  "reopened",
  "assigned",
  "in_progress",
] as const;

export function isAssignable(issue: IssueDetail) {
  return (ASSIGNABLE_STATUSES as readonly string[]).includes(issue.status);
}

function NoteArea({
  label,
  help,
  value,
  onChange,
  required,
  error,
}: {
  label: string;
  help?: string;
  value: string;
  onChange: (value: string) => void;
  required?: boolean;
  error?: string;
}) {
  return (
    <Field label={label} description={help} required={required} error={error}>
      {(control) => (
        <textarea
          {...control}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          rows={3}
          maxLength={NOTE_MAX}
          className={cn(inputClasses, "h-auto py-2")}
        />
      )}
    </Field>
  );
}

// ---------------------------------------------------------------- assign

/**
 * Assign the issue to a team and, optionally, one of its members (FR-062).
 * Only eligible teams are offered: active, handling the category and
 * covering the ward, the most local first. With an open assignment this
 * is a reassignment, which needs a reason and cancels the old work order.
 */
export function AssignDialog({
  issue,
  open,
  onOpenChange,
  onReload,
}: DialogProps) {
  const t = useTranslations("admin.issueDetail.assignDialog");
  const errorMessage = useErrorMessage();
  const apply = useApplyIssue();
  const { toast } = useToast();
  const conflict = useVersionConflict(onReload);
  const current = issue.operations?.assignment ?? null;
  const reassigning = Boolean(current);
  const [teamId, setTeamId] = useState<string | null>(null);
  const [assigneeId, setAssigneeId] = useState<string>(TEAM_ONLY);
  const [note, setNote] = useState("");
  const [reason, setReason] = useState("");
  const [attempted, setAttempted] = useState(false);

  const teams = useQuery({
    queryKey: ["issues", "eligible-teams", issue.id],
    queryFn: ({ signal }) => getEligibleTeams(issue.id, signal),
    enabled: open,
  });

  useEffect(() => {
    if (!open) return;
    setTeamId(null);
    setAssigneeId(TEAM_ONLY);
    setNote("");
    setReason("");
    setAttempted(false);
  }, [open]);

  // One eligible team: pick it, which is nearly always the case.
  useEffect(() => {
    if (open && teamId === null && teams.data?.length === 1) {
      setTeamId(teams.data[0].team.id);
    }
  }, [open, teamId, teams.data]);

  const team = teams.data?.find((item) => item.team.id === teamId);
  const reasonMissing = reassigning && !reason.trim();

  const mutation = useMutation({
    mutationFn: () =>
      assignIssue(issue.id, {
        team_id: teamId as string,
        assignee_id: assigneeId || null,
        note: note.trim() || undefined,
        reason: reassigning ? reason.trim() : undefined,
        version: issue.version,
      }),
    onSuccess: (updated) => {
      apply(updated);
      const assignee = team?.members.find(
        (member) => member.user.id === assigneeId,
      )?.user.display_name;
      toast({
        variant: "success",
        title: assignee
          ? t("assigned", { reference: issue.reference, name: assignee })
          : t("assigned", {
              reference: issue.reference,
              name: team?.team.name ?? "",
            }),
      });
      onOpenChange(false);
    },
    onError: (error) => conflict.check(error),
  });

  const submit = () => {
    setAttempted(true);
    if (!teamId || reasonMissing) return;
    mutation.mutate();
  };

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
      title={
        reassigning
          ? t("reassignTitle", { reference: issue.reference })
          : t("title", { reference: issue.reference })
      }
      description={
        current
          ? t("currently", {
              team: current.team.name,
              assignee: current.assignee?.display_name ?? t("teamOnly"),
            })
          : t("description")
      }
      conflict={conflict}
      submitLabel={reassigning ? t("reassign") : t("submit")}
      onSubmit={submit}
      pending={mutation.isPending}
    >
      <div className="grid gap-5">
        {teams.isPending ? (
          <div className="grid gap-2" aria-busy="true">
            <span className="sr-only">{t("loadingTeams")}</span>
            <Skeleton className="h-11" />
            <Skeleton className="h-11" />
          </div>
        ) : teams.isError ? (
          <Alert variant="destructive" live="assertive">
            {errorMessage(teams.error)}
          </Alert>
        ) : teams.data.length === 0 ? (
          <Alert variant="warning" title={t("noTeamsTitle")}>
            {t("noTeamsBody")}
          </Alert>
        ) : (
          <>
            <ChoiceList
              legend={t("team")}
              options={teams.data.map((item) => ({
                value: item.team.id,
                label: item.team.name,
                icon: UsersRound,
                hint: item.department.name,
              }))}
              value={teamId}
              onChange={(value) => {
                setTeamId(value);
                setAssigneeId(TEAM_ONLY);
              }}
              error={attempted && !teamId ? t("chooseTeam") : undefined}
            />
            {team ? (
              <Field label={t("assignee")} description={t("assigneeHelp")}>
                {(control) => (
                  <Select
                    {...control}
                    value={assigneeId}
                    onChange={(event) => setAssigneeId(event.target.value)}
                  >
                    <option value={TEAM_ONLY}>{t("teamOnly")}</option>
                    {team.members.map((member) => (
                      <option key={member.user.id} value={member.user.id}>
                        {member.user.display_name ?? t("unnamed")}
                        {member.team_role === "lead" ? ` (${t("lead")})` : ""}
                      </option>
                    ))}
                  </Select>
                )}
              </Field>
            ) : null}
          </>
        )}

        <NoteArea
          label={t("note")}
          help={t("noteHelp")}
          value={note}
          onChange={setNote}
        />
        {reassigning ? (
          <ReasonField
            value={reason}
            onChange={setReason}
            error={
              (attempted && reasonMissing) ||
              isApiError(mutation.error, "reason_required")
                ? t("reasonRequired")
                : undefined
            }
          />
        ) : null}

        {serverError ? (
          <Alert variant="destructive" live="assertive">
            {serverError}
          </Alert>
        ) : null}
      </div>
    </IssueDialog>
  );
}

// --------------------------------------------------------------- closure

/** Approve the field worker's closure request: the issue is resolved. */
export function ApproveClosureDialog({
  issue,
  open,
  onOpenChange,
  onReload,
}: DialogProps) {
  const t = useTranslations("admin.issueDetail.approveDialog");
  const errorMessage = useErrorMessage();
  const apply = useApplyIssue();
  const { toast } = useToast();
  const conflict = useVersionConflict(onReload);
  const [note, setNote] = useState("");
  useEffect(() => {
    if (open) setNote("");
  }, [open]);

  const mutation = useMutation({
    mutationFn: () =>
      approveClosure(issue.id, {
        version: issue.version,
        public_note: note.trim() || undefined,
      }),
    onSuccess: (updated) => {
      apply(updated);
      toast({
        variant: "success",
        title: t("approved", { reference: issue.reference }),
      });
      onOpenChange(false);
    },
    onError: (error) => conflict.check(error),
  });
  const serverError =
    mutation.isError && !conflict.conflict
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
      onSubmit={() => mutation.mutate()}
      pending={mutation.isPending}
    >
      <div className="grid gap-5">
        <NoteArea
          label={t("publicNote")}
          help={t("publicNoteHelp")}
          value={note}
          onChange={setNote}
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

/** Send the work back to the field worker, with a reason they'll see. */
export function RejectClosureDialog({
  issue,
  open,
  onOpenChange,
  onReload,
}: DialogProps) {
  const t = useTranslations("admin.issueDetail.rejectClosureDialog");
  const errorMessage = useErrorMessage();
  const apply = useApplyIssue();
  const { toast } = useToast();
  const conflict = useVersionConflict(onReload);
  const [reason, setReason] = useState("");
  const [attempted, setAttempted] = useState(false);
  useEffect(() => {
    if (!open) return;
    setReason("");
    setAttempted(false);
  }, [open]);

  const mutation = useMutation({
    mutationFn: () =>
      rejectClosure(issue.id, {
        version: issue.version,
        reason: reason.trim(),
      }),
    onSuccess: (updated) => {
      apply(updated);
      toast({
        variant: "success",
        title: t("rejected", { reference: issue.reference }),
      });
      onOpenChange(false);
    },
    onError: (error) => conflict.check(error),
  });
  const missing = !reason.trim();
  const submit = () => {
    setAttempted(true);
    if (missing) return;
    mutation.mutate();
  };
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
      submitVariant="destructive"
      onSubmit={submit}
      pending={mutation.isPending}
    >
      <div className="grid gap-5">
        <ReasonField
          value={reason}
          onChange={setReason}
          help={t("reasonHelp")}
          error={
            (attempted && missing) ||
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

// ------------------------------------------------------------------ note

/**
 * Add a note to the issue (FR-067). Internal notes stay with staff;
 * public ones appear on the citizen timeline. The choice is explicit,
 * with no default, so nothing goes public by accident.
 */
export function NoteDialog({
  issue,
  open,
  onOpenChange,
  onReload,
}: DialogProps) {
  const t = useTranslations("admin.issueDetail.noteDialog");
  const errorMessage = useErrorMessage();
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const conflict = useVersionConflict(onReload);
  const [body, setBody] = useState("");
  const [visibility, setVisibility] = useState<"internal" | "public" | null>(
    null,
  );
  const [attempted, setAttempted] = useState(false);
  useEffect(() => {
    if (!open) return;
    setBody("");
    setVisibility(null);
    setAttempted(false);
  }, [open]);

  const mutation = useMutation({
    mutationFn: () =>
      addIssueNote(issue.id, {
        body: body.trim(),
        visibility: visibility as "internal" | "public",
      }),
    onSuccess: async () => {
      // Notes don't return the issue; fetch it for the new timeline entry.
      await queryClient.invalidateQueries({
        queryKey: ["issues", "detail", issue.id],
      });
      toast({ variant: "success", title: t("added") });
      onOpenChange(false);
    },
  });
  const missing = !body.trim();
  const submit = () => {
    setAttempted(true);
    if (missing || !visibility) return;
    mutation.mutate();
  };

  return (
    <IssueDialog
      open={open}
      onOpenChange={onOpenChange}
      title={t("title", { reference: issue.reference })}
      conflict={conflict}
      submitLabel={t("submit")}
      onSubmit={submit}
      pending={mutation.isPending}
    >
      <div className="grid gap-5">
        <NoteArea
          label={t("body")}
          value={body}
          onChange={setBody}
          required
          error={attempted && missing ? t("bodyRequired") : undefined}
        />
        <ChoiceList
          legend={t("visibility")}
          options={[
            {
              value: "internal",
              label: t("internal"),
              icon: Lock,
              hint: t("internalHint"),
            },
            {
              value: "public",
              label: t("public"),
              icon: Globe,
              hint: t("publicHint"),
            },
          ]}
          value={visibility}
          onChange={setVisibility}
          error={attempted && !visibility ? t("chooseVisibility") : undefined}
        />
        {mutation.isError ? (
          <Alert variant="destructive" live="assertive">
            {errorMessage(mutation.error)}
          </Alert>
        ) : null}
      </div>
    </IssueDialog>
  );
}

// ---------------------------------------------------------------- reopen

/** Reopen a resolved or closed issue; it goes back to be assigned. */
export function ReopenDialog({
  issue,
  open,
  onOpenChange,
  onReload,
}: DialogProps) {
  const t = useTranslations("admin.issueDetail.reopenDialog");
  const errorMessage = useErrorMessage();
  const apply = useApplyIssue();
  const { toast } = useToast();
  const conflict = useVersionConflict(onReload);
  const [reason, setReason] = useState("");
  const [attempted, setAttempted] = useState(false);
  useEffect(() => {
    if (!open) return;
    setReason("");
    setAttempted(false);
  }, [open]);

  const mutation = useMutation({
    mutationFn: () => staffReopenIssue(issue.id, { reason: reason.trim() }),
    onSuccess: (updated) => {
      apply(updated);
      toast({
        variant: "success",
        title: t("reopened", { reference: issue.reference }),
      });
      onOpenChange(false);
    },
  });
  const missing = !reason.trim();
  const submit = () => {
    setAttempted(true);
    if (missing) return;
    mutation.mutate();
  };

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
        <ReasonField
          value={reason}
          onChange={setReason}
          error={
            (attempted && missing) ||
            isApiError(mutation.error, "reason_required")
              ? t("reasonRequired")
              : undefined
          }
        />
        {mutation.isError && !isApiError(mutation.error, "reason_required") ? (
          <Alert variant="destructive" live="assertive">
            {errorMessage(mutation.error)}
          </Alert>
        ) : null}
      </div>
    </IssueDialog>
  );
}
