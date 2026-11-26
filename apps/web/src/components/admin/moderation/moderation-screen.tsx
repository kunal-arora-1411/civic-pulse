"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Flag, X } from "lucide-react";
import { useFormatter, useTranslations } from "next-intl";
import { useEffect, useState } from "react";
import { PageHeader } from "@/components/admin/page-header";
import { PageLoading } from "@/components/page-loading";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import { Field } from "@/components/ui/field";
import { inputClasses } from "@/components/ui/input";
import { useToast } from "@/components/ui/toast";
import { useErrorMessage } from "@/hooks/use-error-message";
import { Link } from "@/i18n/navigation";
import {
  type CommentState,
  listModerationQueue,
  type ModerationEntry,
  moderateComment,
} from "@/lib/api";
import { cn } from "@/lib/utils";

const KEY = ["moderation", "comments"] as const;
const TABS: CommentState[] = ["pending", "rejected", "approved"];

function RejectDialog({
  entry,
  onOpenChange,
}: {
  entry: ModerationEntry | null;
  onOpenChange: (open: boolean) => void;
}) {
  const t = useTranslations("admin.moderation");
  const errorMessage = useErrorMessage();
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const [reason, setReason] = useState("");
  const [attempted, setAttempted] = useState(false);
  useEffect(() => {
    if (!entry) return;
    setReason("");
    setAttempted(false);
  }, [entry]);
  const mutation = useMutation({
    mutationFn: () =>
      moderateComment((entry as ModerationEntry).id, {
        decision: "reject",
        reason: reason.trim(),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: KEY });
      toast({ variant: "success", title: t("rejected") });
      onOpenChange(false);
    },
  });
  const missing = !reason.trim();
  return (
    <Dialog
      open={entry !== null}
      onOpenChange={onOpenChange}
      title={t("rejectTitle")}
      description={t("rejectDescription")}
      closeLabel={t("close")}
      footer={
        <>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t("cancel")}
          </Button>
          <Button
            variant="destructive"
            loading={mutation.isPending}
            onClick={() => {
              setAttempted(true);
              if (!missing) mutation.mutate();
            }}
          >
            {t("reject")}
          </Button>
        </>
      }
    >
      <div className="grid gap-4">
        {entry ? (
          <blockquote className="whitespace-pre-line rounded-lg bg-muted px-3 py-2 text-sm">
            {entry.body}
          </blockquote>
        ) : null}
        <Field
          label={t("reason")}
          description={t("reasonHelp")}
          required
          error={attempted && missing ? t("reasonRequired") : undefined}
        >
          {(control) => (
            <textarea
              {...control}
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              rows={3}
              maxLength={500}
              className={cn(inputClasses, "h-auto py-2")}
            />
          )}
        </Field>
        {mutation.isError ? (
          <Alert variant="destructive" live="assertive">
            {errorMessage(mutation.error)}
          </Alert>
        ) : null}
      </div>
    </Dialog>
  );
}

function Entry({
  entry,
  onReject,
}: {
  entry: ModerationEntry;
  onReject: () => void;
}) {
  const t = useTranslations("admin.moderation");
  const format = useFormatter();
  const errorMessage = useErrorMessage();
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const approve = useMutation({
    mutationFn: () => moderateComment(entry.id, { decision: "approve" }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: KEY });
      toast({ variant: "success", title: t("approved") });
    },
  });
  return (
    <li>
      <Card className="grid gap-2 p-4">
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <Link
            href={`/admin/issues/${entry.issue.id}`}
            className="font-mono font-semibold text-primary underline-offset-4 hover:underline"
          >
            {entry.issue.reference}
          </Link>
          <span className="text-muted-foreground">
            {entry.author_name ?? t("unnamed")} ·{" "}
            <time dateTime={entry.created_at}>
              {format.dateTime(new Date(entry.created_at), {
                dateStyle: "medium",
                timeStyle: "short",
              })}
            </time>
          </span>
          {entry.flag_count ? (
            <Badge variant="warning">
              <Flag aria-hidden="true" />
              {t("flags", { count: entry.flag_count })}
            </Badge>
          ) : null}
        </div>
        <p className="whitespace-pre-line">{entry.body}</p>
        {entry.moderation_reason ? (
          <p className="text-sm text-muted-foreground">
            {t("reasonShown", { reason: entry.moderation_reason })}
          </p>
        ) : null}
        <div className="flex flex-wrap gap-2">
          {entry.state !== "approved" ? (
            <Button
              size="sm"
              onClick={() => approve.mutate()}
              loading={approve.isPending}
            >
              <Check aria-hidden="true" />
              {t("approve")}
            </Button>
          ) : null}
          {entry.state !== "rejected" ? (
            <Button size="sm" variant="outline" onClick={onReject}>
              <X aria-hidden="true" />
              {t("reject")}
            </Button>
          ) : null}
        </div>
        {approve.isError ? (
          <Alert variant="destructive">{errorMessage(approve.error)}</Alert>
        ) : null}
      </Card>
    </li>
  );
}

/**
 * The moderation queue (FR-086): citizens' comments on issues in the
 * moderator's scope, most flagged first. Approving publishes a comment;
 * rejecting removes it with a reason its author sees.
 */
export function ModerationScreen() {
  const t = useTranslations("admin.moderation");
  const errorMessage = useErrorMessage();
  const [state, setState] = useState<CommentState>("pending");
  const [rejecting, setRejecting] = useState<ModerationEntry | null>(null);
  const query = useQuery({
    queryKey: [...KEY, state],
    queryFn: ({ signal }) => listModerationQueue({ state, limit: 50 }, signal),
  });

  return (
    <div className="grid gap-6 motion-safe:animate-rise">
      <PageHeader
        section="moderation"
        title={t("title")}
        description={t("description")}
      />
      <div
        role="tablist"
        aria-label={t("tabsLabel")}
        className="inline-flex w-fit gap-1 rounded-xl bg-card p-1 shadow-card"
      >
        {TABS.map((tab) => (
          <button
            key={tab}
            type="button"
            role="tab"
            aria-selected={state === tab}
            onClick={() => setState(tab)}
            className={cn(
              "rounded-lg px-3 py-1.5 text-sm font-semibold focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-ring/30",
              state === tab
                ? "bg-primary text-primary-foreground"
                : "text-muted-foreground hover:bg-muted",
            )}
          >
            {t(`tabs.${tab}`)}
          </button>
        ))}
      </div>
      {query.isPending ? (
        <PageLoading />
      ) : query.isError ? (
        <Alert variant="destructive" live="assertive" title={t("loadError")}>
          {errorMessage(query.error)}
        </Alert>
      ) : query.data.items.length === 0 ? (
        <Card className="p-6 text-center text-muted-foreground">
          {t(`empty.${state}`)}
        </Card>
      ) : (
        <ul className="grid gap-3" aria-label={t(`tabs.${state}`)}>
          {query.data.items.map((entry) => (
            <Entry
              key={entry.id}
              entry={entry}
              onReject={() => setRejecting(entry)}
            />
          ))}
        </ul>
      )}
      <RejectDialog
        entry={rejecting}
        onOpenChange={(open) => {
          if (!open) setRejecting(null);
        }}
      />
    </div>
  );
}
