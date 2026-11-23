"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Globe, RefreshCw } from "lucide-react";
import { useTranslations } from "next-intl";
import { useEffect, useId, useState } from "react";
import { STATUS_STYLE } from "@/components/issues/status-badge";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Field } from "@/components/ui/field";
import { inputClasses } from "@/components/ui/input";
import { useToast } from "@/components/ui/toast";
import { useErrorMessage } from "@/hooks/use-error-message";
import {
  changeIssueStatus,
  type IssueDetail,
  type IssueStatus,
  isApiError,
} from "@/lib/api";
import { cn } from "@/lib/utils";

const NOTE_MAX = 1000;

type Conflict = "version" | "transition" | null;

/**
 * Move an issue to one of the statuses the API says this user may pick.
 *
 * The request carries the version the user was looking at. If someone
 * else changed the issue in the meantime the API answers 409, and rather
 * than retrying with the new version (which would silently overwrite
 * their change) the dialog says so and offers to reload. What the user
 * typed is kept, so they can re-apply it after checking.
 */
export function StatusDialog({
  issue,
  open,
  onOpenChange,
  onReload,
}: {
  issue: IssueDetail;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Fetch the latest issue; resolves when it's in. */
  onReload: () => Promise<unknown>;
}) {
  const t = useTranslations("admin.issueDetail.statusDialog");
  const tStatus = useTranslations("issueStatus");
  const errorMessage = useErrorMessage();
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const ids = { group: useId(), groupError: useId() };

  const [target, setTarget] = useState<IssueStatus | null>(null);
  const [reason, setReason] = useState("");
  const [note, setNote] = useState("");
  const [attempted, setAttempted] = useState(false);
  const [conflict, setConflict] = useState<Conflict>(null);
  const [reloading, setReloading] = useState(false);

  // Start clean each time the dialog opens.
  useEffect(() => {
    if (!open) return;
    setTarget(null);
    setReason("");
    setNote("");
    setAttempted(false);
    setConflict(null);
  }, [open]);

  const transition = issue.allowed_transitions.find(
    (option) => option.to_status === target,
  );
  const reasonMissing = Boolean(transition?.requires_reason && !reason.trim());

  const mutation = useMutation({
    mutationFn: () =>
      changeIssueStatus(issue.id, {
        to_status: target as IssueStatus,
        reason: reason.trim() || undefined,
        public_note: note.trim() || undefined,
        version: issue.version,
      }),
    onSuccess: (updated) => {
      queryClient.setQueryData(["issues", "detail", issue.id], updated);
      queryClient.invalidateQueries({ queryKey: ["issues", "list"] });
      queryClient.invalidateQueries({ queryKey: ["issues", "geojson"] });
      toast({
        variant: "success",
        title: t("changed", {
          reference: issue.reference,
          status: tStatus(updated.status),
        }),
      });
      onOpenChange(false);
    },
    onError: (error) => {
      if (isApiError(error, "version_conflict")) setConflict("version");
      else if (isApiError(error, "invalid_transition"))
        setConflict("transition");
    },
  });

  const submit = () => {
    setAttempted(true);
    if (!target || reasonMissing) return;
    mutation.mutate();
  };

  const reload = async () => {
    setReloading(true);
    try {
      await onReload();
      setConflict(null);
      mutation.reset();
      // The allowed targets may have changed with the new status.
      setTarget(null);
    } finally {
      setReloading(false);
    }
  };

  const serverError =
    mutation.isError &&
    !conflict &&
    !isApiError(mutation.error, "reason_required")
      ? errorMessage(mutation.error)
      : null;
  const reasonError =
    (attempted && reasonMissing) ||
    (mutation.isError && isApiError(mutation.error, "reason_required"))
      ? t("reasonRequired")
      : undefined;

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={t("title", { reference: issue.reference })}
      description={t("description", { status: tStatus(issue.status) })}
      closeLabel={t("close")}
      footer={
        conflict ? (
          <>
            <Button variant="outline" onClick={() => onOpenChange(false)}>
              {t("cancel")}
            </Button>
            <Button onClick={reload} loading={reloading}>
              <RefreshCw aria-hidden="true" />
              {t("reload")}
            </Button>
          </>
        ) : (
          <>
            <Button variant="outline" onClick={() => onOpenChange(false)}>
              {t("cancel")}
            </Button>
            <Button onClick={submit} loading={mutation.isPending}>
              {t("submit")}
            </Button>
          </>
        )
      }
    >
      {conflict ? (
        <Alert
          variant="warning"
          live="assertive"
          title={
            conflict === "version"
              ? t("conflictTitle")
              : t("transitionGoneTitle")
          }
        >
          {conflict === "version" ? t("conflictBody") : t("transitionGoneBody")}
        </Alert>
      ) : (
        <div className="grid gap-5">
          {issue.allowed_transitions.length === 0 ? (
            <Alert variant="info">{t("noTransitions")}</Alert>
          ) : (
            <fieldset
              className="grid gap-2"
              aria-describedby={
                attempted && !target ? ids.groupError : undefined
              }
            >
              <legend className="mb-1 text-sm font-semibold">
                {t("newStatus")}
              </legend>
              {issue.allowed_transitions.map((option) => {
                const { icon: Icon } = STATUS_STYLE[option.to_status];
                const checked = target === option.to_status;
                return (
                  <label
                    key={option.to_status}
                    className={cn(
                      "flex cursor-pointer items-center gap-3 rounded-lg border px-3 py-2.5 has-focus-visible:ring-3 has-focus-visible:ring-ring/30",
                      checked
                        ? "border-primary bg-primary-soft"
                        : "border-input hover:bg-muted",
                    )}
                  >
                    <input
                      type="radio"
                      name={ids.group}
                      value={option.to_status}
                      checked={checked}
                      onChange={() => setTarget(option.to_status)}
                      className="size-4 accent-primary"
                    />
                    <Icon aria-hidden="true" className="size-4" />
                    <span className="font-semibold">
                      {tStatus(option.to_status)}
                    </span>
                    {option.requires_reason ? (
                      <span className="ms-auto text-xs text-muted-foreground">
                        {t("needsReason")}
                      </span>
                    ) : null}
                  </label>
                );
              })}
              {attempted && !target ? (
                <p
                  id={ids.groupError}
                  className="text-sm font-medium text-destructive-soft-foreground"
                >
                  {t("chooseStatus")}
                </p>
              ) : null}
            </fieldset>
          )}

          <Field
            label={
              transition?.requires_reason ? t("reason") : t("reasonOptional")
            }
            description={t("reasonHelp")}
            required={transition?.requires_reason}
            error={reasonError}
          >
            {(control) => (
              <textarea
                {...control}
                value={reason}
                onChange={(event) => setReason(event.target.value)}
                rows={3}
                maxLength={NOTE_MAX}
                className={cn(inputClasses, "h-auto py-2")}
              />
            )}
          </Field>

          <Field
            label={
              <span className="inline-flex items-center gap-1.5">
                <Globe aria-hidden="true" className="size-4" />
                {t("publicNote")}
              </span>
            }
            description={t("publicNoteHelp")}
          >
            {(control) => (
              <textarea
                {...control}
                value={note}
                onChange={(event) => setNote(event.target.value)}
                rows={2}
                maxLength={NOTE_MAX}
                className={cn(inputClasses, "h-auto py-2")}
              />
            )}
          </Field>

          {serverError ? (
            <Alert variant="destructive" live="assertive">
              {serverError}
            </Alert>
          ) : null}
        </div>
      )}
    </Dialog>
  );
}
