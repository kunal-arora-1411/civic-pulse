"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { useErrorMessage } from "@/hooks/use-error-message";
import { useRouter } from "@/i18n/navigation";
import { anonymizeMe } from "@/lib/api/endpoints/users";

/**
 * "Delete my personal data" (P6-12). The account's phone, email, name and
 * photo metadata are wiped and every session ends; reports stay, without
 * anything that identifies the reporter.
 */
export function DeleteAccount() {
  const t = useTranslations("profile.delete");
  const tCommon = useTranslations("common");
  const errorMessage = useErrorMessage();
  const router = useRouter();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);

  const remove = useMutation({
    mutationFn: anonymizeMe,
    onSuccess: () => {
      queryClient.clear();
      router.replace("/");
    },
  });

  return (
    <section
      aria-labelledby="delete-account"
      className="grid gap-3 rounded-2xl border border-border bg-card p-5"
    >
      <h2 id="delete-account" className="text-lg font-semibold">
        {t("title")}
      </h2>
      <p className="text-sm text-muted-foreground">{t("body")}</p>
      <div>
        <Button variant="outline" onClick={() => setOpen(true)}>
          <Trash2 aria-hidden="true" />
          {t("open")}
        </Button>
      </div>
      <Dialog
        open={open}
        onOpenChange={(next) => {
          setOpen(next);
          if (!next) remove.reset();
        }}
        title={t("confirmTitle")}
        description={t("confirmBody")}
        closeLabel={tCommon("close")}
        footer={
          <>
            <Button variant="ghost" onClick={() => setOpen(false)}>
              {t("cancel")}
            </Button>
            <Button
              variant="destructive"
              disabled={remove.isPending}
              onClick={() => remove.mutate()}
            >
              {remove.isPending ? t("deleting") : t("confirm")}
            </Button>
          </>
        }
      >
        {remove.isError ? (
          <Alert variant="destructive">{errorMessage(remove.error)}</Alert>
        ) : null}
      </Dialog>
    </section>
  );
}
