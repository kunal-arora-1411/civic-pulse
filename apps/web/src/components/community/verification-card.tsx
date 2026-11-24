"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CircleCheck, CircleX, RotateCcw } from "lucide-react";
import { useFormatter, useTranslations } from "next-intl";
import { useId, useState } from "react";
import { PhotoGallery } from "@/components/media/photo-gallery";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import { Field } from "@/components/ui/field";
import { inputClasses } from "@/components/ui/input";
import { useToast } from "@/components/ui/toast";
import { useErrorMessage } from "@/hooks/use-error-message";
import {
  isApiError,
  type Report,
  reopenIssue,
  type VerificationOutcome,
  verifyIssue,
} from "@/lib/api";
import { cn } from "@/lib/utils";

const NOTE_MAX = 2000;

type ReportIssue = NonNullable<Report["issue"]>;

/** Errors the citizen can act on get their own words. */
const KNOWN = [
  "not_eligible",
  "already_verified",
  "invalid_transition",
] as const;

function knownCode(error: unknown): (typeof KNOWN)[number] | null {
  for (const code of KNOWN) if (isApiError(error, code)) return code;
  return null;
}

/** "contractor_done" → "Contractor done". */
function humanize(code: string): string {
  const words = code.replace(/[_-]+/g, " ").trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/** Store the report the server sends back, so the page updates at once. */
function useReportUpdate(reportId: string) {
  const queryClient = useQueryClient();
  return {
    set: (report: Report) =>
      queryClient.setQueryData(["reports", "detail", reportId], report),
    refetch: () =>
      queryClient.invalidateQueries({
        queryKey: ["reports", "detail", reportId],
      }),
  };
}

/**
 * Asks the reporter whether the closed-off work really fixed the problem
 * (PRD FR-072): the after photos and the closure note, then "Yes, it's
 * fixed" or "No, still broken" (with a required note). Once answered it
 * shows the answer instead.
 */
export function VerificationCard({
  reportId,
  issue,
}: {
  reportId: string;
  issue: ReportIssue;
}) {
  const t = useTranslations("community.verify");
  const format = useFormatter();
  const errorMessage = useErrorMessage();
  const { toast } = useToast();
  const update = useReportUpdate(reportId);
  const [answeringNo, setAnsweringNo] = useState(false);
  const [note, setNote] = useState("");
  const [noteError, setNoteError] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: (body: { outcome: VerificationOutcome; note?: string }) =>
      verifyIssue(issue.id, body),
    onSuccess: (report, body) => {
      update.set(report);
      setAnsweringNo(false);
      toast({
        variant: "success",
        title:
          body.outcome === "resolved" ? t("sentResolved") : t("sentUnresolved"),
      });
    },
    onError: (error) => {
      const code = knownCode(error);
      if (code === "already_verified" || code === "invalid_transition") {
        update.refetch();
      }
    },
  });

  const closure = issue.closure;
  if (!closure || (!issue.can_verify && !issue.my_verification)) return null;

  const code = mutation.isError ? knownCode(mutation.error) : null;

  return (
    <Card className="grid gap-4 border-warning-soft-foreground/25 p-5">
      <div className="grid gap-1">
        <h2 className="text-lg font-semibold">{t("title")}</h2>
        <p className="text-sm text-muted-foreground">
          {t("requestedOn", {
            date: format.dateTime(new Date(closure.requested_at), {
              dateStyle: "medium",
            }),
          })}
        </p>
      </div>

      <div className="grid gap-2">
        <h3 className="text-sm font-semibold">{t("afterPhotos")}</h3>
        {closure.after_photos.length > 0 ? (
          <PhotoGallery
            media={closure.after_photos}
            label={t("afterPhotosOf", { reference: issue.reference })}
          />
        ) : (
          <p className="text-sm text-muted-foreground">{t("noAfterPhotos")}</p>
        )}
        {closure.reason_code ? (
          <p className="text-sm">
            {t("closureNote", { note: humanize(closure.reason_code) })}
          </p>
        ) : null}
      </div>

      {issue.my_verification ? (
        <Alert
          variant={issue.my_verification === "resolved" ? "success" : "warning"}
          live="polite"
        >
          {issue.my_verification === "resolved"
            ? t("answeredResolved")
            : t("answeredUnresolved")}
        </Alert>
      ) : (
        <div className="grid gap-3">
          <p className="text-sm">{t("description")}</p>
          {mutation.isError ? (
            <Alert variant="destructive" live="assertive">
              {code ? t(code) : errorMessage(mutation.error)}
            </Alert>
          ) : null}
          {answeringNo ? (
            <form
              className="grid gap-3"
              noValidate
              onSubmit={(event) => {
                event.preventDefault();
                const trimmed = note.trim();
                if (!trimmed) {
                  setNoteError(t("noteRequired"));
                  return;
                }
                setNoteError(null);
                mutation.mutate({ outcome: "unresolved", note: trimmed });
              }}
            >
              <Field
                label={t("noteLabel")}
                description={t("noteHint")}
                error={noteError ?? undefined}
                required
              >
                {(control) => (
                  <textarea
                    {...control}
                    value={note}
                    onChange={(event) => setNote(event.target.value)}
                    rows={3}
                    maxLength={NOTE_MAX}
                    className={cn(inputClasses, "h-auto py-2")}
                  />
                )}
              </Field>
              <div className="flex flex-wrap gap-2">
                <Button
                  type="submit"
                  variant="destructive"
                  loading={mutation.isPending}
                >
                  <CircleX aria-hidden="true" />
                  {t("submitNo")}
                </Button>
                <Button
                  variant="ghost"
                  disabled={mutation.isPending}
                  onClick={() => {
                    setAnsweringNo(false);
                    setNoteError(null);
                  }}
                >
                  {t("cancel")}
                </Button>
              </div>
            </form>
          ) : (
            <div className="flex flex-wrap gap-2">
              <Button
                loading={
                  mutation.isPending &&
                  mutation.variables?.outcome === "resolved"
                }
                disabled={mutation.isPending}
                onClick={() => mutation.mutate({ outcome: "resolved" })}
              >
                <CircleCheck aria-hidden="true" />
                {t("yes")}
              </Button>
              <Button
                variant="outline"
                disabled={mutation.isPending}
                onClick={() => setAnsweringNo(true)}
              >
                <CircleX aria-hidden="true" />
                {t("no")}
              </Button>
            </div>
          )}
        </div>
      )}
    </Card>
  );
}

/** Lets a reporter reopen a resolved or closed issue, with a reason. */
export function ReopenButton({
  reportId,
  issueId,
}: {
  reportId: string;
  issueId: string;
}) {
  const t = useTranslations("community.reopen");
  const errorMessage = useErrorMessage();
  const { toast } = useToast();
  const update = useReportUpdate(reportId);
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [reasonError, setReasonError] = useState<string | null>(null);
  const formId = useId();

  const mutation = useMutation({
    mutationFn: (text: string) => reopenIssue(issueId, { reason: text }),
    onSuccess: (report) => {
      update.set(report);
      setOpen(false);
      setReason("");
      toast({ variant: "success", title: t("done") });
    },
    onError: (error) => {
      if (isApiError(error, "invalid_transition")) update.refetch();
    },
  });

  const error = mutation.error;
  const message = !mutation.isError
    ? null
    : isApiError(error, "not_eligible")
      ? t("not_eligible")
      : isApiError(error, "invalid_transition")
        ? t("invalid_transition")
        : errorMessage(error);

  return (
    <>
      <Button
        variant="outline"
        onClick={() => {
          mutation.reset();
          setOpen(true);
        }}
      >
        <RotateCcw aria-hidden="true" />
        {t("button")}
      </Button>
      <Dialog
        open={open}
        onOpenChange={(next) => {
          if (!mutation.isPending) setOpen(next);
        }}
        title={t("title")}
        description={t("description")}
        closeLabel={t("close")}
        footer={
          <>
            <Button
              variant="ghost"
              disabled={mutation.isPending}
              onClick={() => setOpen(false)}
            >
              {t("cancel")}
            </Button>
            <Button type="submit" form={formId} loading={mutation.isPending}>
              {t("submit")}
            </Button>
          </>
        }
      >
        <form
          id={formId}
          noValidate
          className="grid gap-3"
          onSubmit={(event) => {
            event.preventDefault();
            const trimmed = reason.trim();
            if (!trimmed) {
              setReasonError(t("reasonRequired"));
              return;
            }
            setReasonError(null);
            mutation.mutate(trimmed);
          }}
        >
          {message ? (
            <Alert variant="destructive" live="assertive">
              {message}
            </Alert>
          ) : null}
          <Field
            label={t("reasonLabel")}
            error={reasonError ?? undefined}
            required
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
        </form>
      </Dialog>
    </>
  );
}
