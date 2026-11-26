"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Flag, MessageSquare } from "lucide-react";
import { useFormatter, useTranslations } from "next-intl";
import { useState } from "react";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Field } from "@/components/ui/field";
import { inputClasses } from "@/components/ui/input";
import { useErrorMessage } from "@/hooks/use-error-message";
import {
  addIssueComment,
  flagComment,
  type IssueComment,
  listIssueComments,
} from "@/lib/api";
import { cn } from "@/lib/utils";

const BODY_MAX = 1000;

function CommentItem({
  comment,
  issueId,
}: {
  comment: IssueComment;
  issueId: string;
}) {
  const t = useTranslations("community.comments");
  const format = useFormatter();
  const errorMessage = useErrorMessage();
  const queryClient = useQueryClient();
  const flag = useMutation({
    mutationFn: () => flagComment(comment.id),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["comments", issueId] }),
  });
  return (
    <li className="grid gap-1 rounded-lg border border-border p-3">
      <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
        <span>{comment.mine ? t("you") : t("resident")}</span>
        <span aria-hidden="true">·</span>
        <time dateTime={comment.created_at}>
          {format.dateTime(new Date(comment.created_at), {
            dateStyle: "medium",
          })}
        </time>
        {comment.state !== "approved" ? (
          <Badge variant={comment.state === "pending" ? "warning" : "neutral"}>
            {t(`state.${comment.state}`)}
          </Badge>
        ) : null}
      </div>
      <p className="whitespace-pre-line text-sm">{comment.body}</p>
      {comment.state === "rejected" && comment.moderation_reason ? (
        <p className="text-xs text-muted-foreground">
          {t("rejectedBecause", { reason: comment.moderation_reason })}
        </p>
      ) : null}
      {!comment.mine && comment.state === "approved" ? (
        <div className="flex items-center gap-2">
          {comment.flagged_by_me ? (
            <span className="text-xs text-muted-foreground">
              {t("flagged")}
            </span>
          ) : (
            <Button
              variant="ghost"
              size="sm"
              className="w-fit text-muted-foreground"
              onClick={() => flag.mutate()}
              loading={flag.isPending}
            >
              <Flag aria-hidden="true" />
              {t("flag")}
            </Button>
          )}
          {flag.isError ? (
            <span className="text-xs text-destructive-soft-foreground">
              {errorMessage(flag.error)}
            </span>
          ) : null}
        </div>
      ) : null}
    </li>
  );
}

/**
 * Comments on an issue (FR-017). Citizens see approved comments and their
 * own; a new comment waits for a moderator before anyone else sees it.
 */
export function IssueComments({ issueId }: { issueId: string }) {
  const t = useTranslations("community.comments");
  const errorMessage = useErrorMessage();
  const queryClient = useQueryClient();
  const [body, setBody] = useState("");
  const [attempted, setAttempted] = useState(false);
  const comments = useQuery({
    queryKey: ["comments", issueId],
    queryFn: ({ signal }) => listIssueComments(issueId, signal),
  });
  const add = useMutation({
    mutationFn: () => addIssueComment(issueId, body.trim()),
    onSuccess: () => {
      setBody("");
      setAttempted(false);
      queryClient.invalidateQueries({ queryKey: ["comments", issueId] });
    },
  });
  const missing = !body.trim();

  return (
    <Card className="grid gap-4 p-5">
      <h2 className="eyebrow flex items-center gap-2">
        <MessageSquare aria-hidden="true" className="size-4" />
        {t("title")}
      </h2>
      {comments.isError ? (
        <Alert variant="destructive">{errorMessage(comments.error)}</Alert>
      ) : comments.data && comments.data.items.length > 0 ? (
        <ul className="grid gap-2" aria-label={t("title")}>
          {comments.data.items.map((comment) => (
            <CommentItem key={comment.id} comment={comment} issueId={issueId} />
          ))}
        </ul>
      ) : comments.data ? (
        <p className="text-sm text-muted-foreground">{t("none")}</p>
      ) : null}

      <form
        className="grid gap-2"
        onSubmit={(event) => {
          event.preventDefault();
          setAttempted(true);
          if (missing) return;
          add.mutate();
        }}
      >
        <Field
          label={t("add")}
          description={t("addHelp")}
          error={attempted && missing ? t("required") : undefined}
        >
          {(control) => (
            <textarea
              {...control}
              value={body}
              onChange={(event) => setBody(event.target.value)}
              rows={3}
              maxLength={BODY_MAX}
              className={cn(inputClasses, "h-auto py-2")}
            />
          )}
        </Field>
        {add.isSuccess ? (
          <Alert variant="success" live="polite">
            {t("sent")}
          </Alert>
        ) : null}
        {add.isError ? (
          <Alert variant="destructive" live="assertive">
            {errorMessage(add.error)}
          </Alert>
        ) : null}
        <Button type="submit" className="w-fit" loading={add.isPending}>
          {t("submit")}
        </Button>
      </form>
    </Card>
  );
}
