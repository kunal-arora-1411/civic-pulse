"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { useToast } from "@/components/ui/toast";
import { useErrorMessage } from "@/hooks/use-error-message";
import { type AdminUser, updateUser } from "@/lib/api";
import { formatIndianPhone } from "@/lib/phone";

/** Confirms activating or deactivating an account. */
export function StatusDialog({
  user,
  onClose,
}: {
  user: AdminUser | null;
  onClose: () => void;
}) {
  const t = useTranslations("admin.users");
  const tCommon = useTranslations("common");
  const errorMessage = useErrorMessage();
  const { toast } = useToast();
  const queryClient = useQueryClient();

  const change = useMutation({
    mutationFn: (target: AdminUser) =>
      updateUser(target.id, { is_active: !target.is_active }),
    onSuccess: (updated) => {
      queryClient.invalidateQueries({ queryKey: ["admin", "users"] });
      const name = updated.display_name ?? formatIndianPhone(updated.phone);
      toast({
        variant: "success",
        title: updated.is_active
          ? t("activated", { name })
          : t("deactivated", { name }),
      });
      handleClose();
    },
  });

  function handleClose() {
    change.reset();
    onClose();
  }

  const deactivating = user?.is_active ?? false;
  const name = user ? user.display_name || formatIndianPhone(user.phone) : "";

  return (
    <Dialog
      open={user !== null}
      onOpenChange={(next) => {
        if (!next) handleClose();
      }}
      title={
        deactivating
          ? t("deactivateTitle", { name })
          : t("activateTitle", { name })
      }
      description={deactivating ? t("deactivateBody") : t("activateBody")}
      closeLabel={tCommon("close")}
      footer={
        <>
          <Button variant="outline" onClick={handleClose}>
            {t("cancel")}
          </Button>
          <Button
            variant={deactivating ? "destructive" : "primary"}
            loading={change.isPending}
            onClick={() => user && change.mutate(user)}
          >
            {deactivating ? t("deactivate") : t("activate")}
          </Button>
        </>
      }
    >
      {change.isError ? (
        <Alert variant="destructive" live="assertive">
          {errorMessage(change.error)}
        </Alert>
      ) : null}
    </Dialog>
  );
}
