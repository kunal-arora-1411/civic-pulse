"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Undo2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { useToast } from "@/components/ui/toast";
import { useErrorMessage } from "@/hooks/use-error-message";
import { isApiError, type Report, withdrawReport } from "@/lib/api";

/** The issue is finished; withdrawing would only rewrite history. */
const FINAL = new Set(["resolved", "closed"]);

/**
 * Let the reporter withdraw their own report (FR-018). The report stays
 * on the issue as a record but no longer counts towards it. Offered only
 * once matching has placed it and while the issue is still open; the API
 * refuses the rest with `invalid_transition`.
 */
export function WithdrawReport({ report }: { report: Report }) {
  const t = useTranslations("reports.withdraw");
  const errorMessage = useErrorMessage();
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const [open, setOpen] = useState(false);

  const mutation = useMutation({
    mutationFn: () => withdrawReport(report.id),
    onSuccess: (updated) => {
      queryClient.setQueryData(["reports", "detail", report.id], updated);
      queryClient.invalidateQueries({ queryKey: ["reports", "mine"] });
      toast({ variant: "success", title: t("done") });
      setOpen(false);
    },
  });

  if (report.status === "withdrawn") {
    return <Alert variant="info">{t("withdrawn")}</Alert>;
  }
  if (!report.issue || FINAL.has(report.issue.status)) return null;

  const refused = isApiError(mutation.error, "invalid_transition");
  return (
    <>
      <Button
        variant="ghost"
        size="sm"
        className="w-fit text-muted-foreground"
        onClick={() => {
          mutation.reset();
          setOpen(true);
        }}
      >
        <Undo2 aria-hidden="true" />
        {t("button")}
      </Button>
      <Dialog
        open={open}
        onOpenChange={setOpen}
        title={t("title", { reference: report.reference })}
        description={t("description")}
        closeLabel={t("close")}
        footer={
          <>
            <Button variant="outline" onClick={() => setOpen(false)}>
              {t("cancel")}
            </Button>
            <Button
              variant="destructive"
              onClick={() => mutation.mutate()}
              loading={mutation.isPending}
              disabled={refused}
            >
              {t("submit")}
            </Button>
          </>
        }
      >
        {mutation.isError ? (
          <Alert variant="destructive" live="assertive">
            {refused ? t("refused") : errorMessage(mutation.error)}
          </Alert>
        ) : null}
      </Dialog>
    </>
  );
}
