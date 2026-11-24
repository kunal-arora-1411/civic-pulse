"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Link2, Plus, X } from "lucide-react";
import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";
import { CategoryIcon } from "@/components/issues/category-icon";
import { StatusBadge } from "@/components/issues/status-badge";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import { Field } from "@/components/ui/field";
import { inputClasses } from "@/components/ui/input";
import { useToast } from "@/components/ui/toast";
import { useErrorMessage } from "@/hooks/use-error-message";
import { useLocalized } from "@/hooks/use-reference-data";
import { Link } from "@/i18n/navigation";
import {
  addRelatedIssue,
  type IssueDetail,
  type IssueListItem,
  removeRelatedIssue,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import { IssuePicker } from "./issue-picker";

/**
 * Issues that are connected but not the same problem (FR-060): a burst
 * main and the waterlogging it caused, say. Linking doesn't move reports
 * or change counts; it just keeps the connection visible from both ends.
 */
export function RelatedIssues({
  issue,
  canEdit,
}: {
  issue: IssueDetail;
  canEdit: boolean;
}) {
  const t = useTranslations("admin.issueDetail.related");
  const localized = useLocalized();
  const errorMessage = useErrorMessage();
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const [adding, setAdding] = useState(false);
  const refresh = () =>
    queryClient.invalidateQueries({ queryKey: ["issues", "detail", issue.id] });

  const remove = useMutation({
    mutationFn: (other: IssueListItem) =>
      removeRelatedIssue(issue.id, other.id),
    onSuccess: (_, other) => {
      toast({
        variant: "success",
        title: t("removed", { reference: other.reference }),
      });
      return refresh();
    },
    onError: (error) => toast({ variant: "error", title: errorMessage(error) }),
  });

  return (
    <Card className="grid gap-3 p-5">
      <div className="flex items-start justify-between gap-3">
        <h2 className="font-semibold">{t("heading")}</h2>
        {canEdit ? (
          <Button variant="outline" size="sm" onClick={() => setAdding(true)}>
            <Plus aria-hidden="true" />
            {t("add")}
          </Button>
        ) : null}
      </div>
      {issue.related.length === 0 ? (
        <p className="text-sm text-muted-foreground">{t("none")}</p>
      ) : (
        <ul className="grid gap-2">
          {issue.related.map(({ issue: other, note }) => (
            <li
              key={other.id}
              className="flex items-start gap-2 rounded-lg border border-border p-3"
            >
              <Link2
                aria-hidden="true"
                className="mt-0.5 size-4 shrink-0 text-muted-foreground"
              />
              <div className="grid min-w-0 flex-1 gap-1">
                <div className="flex flex-wrap items-center gap-2">
                  <Link
                    href={`/admin/issues/${other.id}`}
                    className="font-mono text-sm font-semibold text-primary underline-offset-4 hover:underline"
                  >
                    {other.reference}
                  </Link>
                  <StatusBadge status={other.status} />
                </div>
                <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
                  <CategoryIcon
                    icon={other.category.icon}
                    className="size-3.5"
                  />
                  {localized(other.category.name_i18n)}
                </p>
                {note ? <p className="text-sm">{note}</p> : null}
              </div>
              {canEdit ? (
                <Button
                  variant="ghost"
                  size="icon-sm"
                  aria-label={t("remove", { reference: other.reference })}
                  disabled={remove.isPending}
                  onClick={() => remove.mutate(other)}
                >
                  <X aria-hidden="true" />
                </Button>
              ) : null}
            </li>
          ))}
        </ul>
      )}
      <AddRelatedDialog
        issue={issue}
        open={adding}
        onOpenChange={setAdding}
        onAdded={refresh}
      />
    </Card>
  );
}

function AddRelatedDialog({
  issue,
  open,
  onOpenChange,
  onAdded,
}: {
  issue: IssueDetail;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onAdded: () => Promise<unknown>;
}) {
  const t = useTranslations("admin.issueDetail.related");
  const tDialog = useTranslations("admin.issueDetail.dialog");
  const errorMessage = useErrorMessage();
  const { toast } = useToast();
  const [picked, setPicked] = useState<IssueListItem[]>([]);
  const [note, setNote] = useState("");
  const [attempted, setAttempted] = useState(false);

  useEffect(() => {
    if (!open) return;
    setPicked([]);
    setNote("");
    setAttempted(false);
  }, [open]);

  const mutation = useMutation({
    mutationFn: () =>
      addRelatedIssue(issue.id, {
        issue_id: picked[0].id,
        note: note.trim() || undefined,
      }),
    onSuccess: async () => {
      toast({
        variant: "success",
        title: t("added", { reference: picked[0].reference }),
      });
      await onAdded();
      onOpenChange(false);
    },
  });

  const submit = () => {
    setAttempted(true);
    if (picked.length === 0) return;
    mutation.mutate();
  };

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={t("dialogTitle", { reference: issue.reference })}
      description={t("dialogDescription")}
      closeLabel={tDialog("close")}
      footer={
        <>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {tDialog("cancel")}
          </Button>
          <Button onClick={submit} loading={mutation.isPending}>
            {t("submit")}
          </Button>
        </>
      }
    >
      <div className="grid gap-5">
        <IssuePicker
          label={t("pickLabel")}
          excludeIds={[issue.id, ...issue.related.map((item) => item.issue.id)]}
          selected={picked}
          onChange={setPicked}
          error={
            attempted && picked.length === 0 ? t("pickRequired") : undefined
          }
        />
        <Field label={t("note")} description={t("noteHelp")}>
          {(control) => (
            <textarea
              {...control}
              value={note}
              onChange={(event) => setNote(event.target.value)}
              rows={2}
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
