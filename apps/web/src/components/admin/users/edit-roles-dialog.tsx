"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useEffect } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { useToast } from "@/components/ui/toast";
import { useErrorMessage } from "@/hooks/use-error-message";
import { type AdminUser, replaceUserRoles } from "@/lib/api";
import { useSession } from "@/lib/auth/use-session";
import { formatIndianPhone } from "@/lib/phone";
import {
  assignableRoles,
  RoleFields,
  roleRowsSchema,
  toRoleInputs,
  toRoleRows,
} from "./role-fields";

export function EditRolesDialog({
  user,
  onClose,
}: {
  /** The user being edited; `null` keeps the dialog closed. */
  user: AdminUser | null;
  onClose: () => void;
}) {
  const t = useTranslations("admin.users");
  const tCommon = useTranslations("common");
  const errorMessage = useErrorMessage();
  const { toast } = useToast();
  const queryClient = useQueryClient();
  const { user: actor } = useSession();

  const schema = z.object({
    roles: roleRowsSchema({
      roleRequired: t("roleRequired"),
      rolesRequired: t("rolesRequired"),
      duplicate: t("rolesDuplicate"),
    }),
  });
  type FormValues = z.input<typeof schema>;
  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: { roles: [] },
  });

  // Load the selected user's roles each time the dialog opens.
  useEffect(() => {
    if (user) form.reset({ roles: toRoleRows(user.roles) });
  }, [user, form]);

  const save = useMutation({
    mutationFn: (values: FormValues) =>
      replaceUserRoles((user as AdminUser).id, toRoleInputs(values.roles)),
    onSuccess: (updated) => {
      queryClient.invalidateQueries({ queryKey: ["admin", "users"] });
      toast({
        variant: "success",
        title: t("rolesSaved", { name: updated.display_name ?? updated.phone }),
      });
      handleClose();
    },
  });

  function handleClose() {
    save.reset();
    onClose();
  }

  const name = user ? user.display_name || formatIndianPhone(user.phone) : "";
  // Keep roles the actor can't grant visible if the user already has them,
  // so saving doesn't silently drop them from the select.
  const options = [
    ...new Set([
      ...assignableRoles(actor, { staffOnly: false }),
      ...(user?.roles.map((r) => r.role) ?? []),
    ]),
  ];

  return (
    <Dialog
      open={user !== null}
      onOpenChange={(next) => {
        if (!next) handleClose();
      }}
      title={t("editRolesTitle", { name })}
      description={t("editRolesDescription")}
      closeLabel={tCommon("close")}
      className="max-w-3xl"
      footer={
        <>
          <Button variant="outline" onClick={handleClose}>
            {t("cancel")}
          </Button>
          <Button type="submit" form="edit-roles-form" loading={save.isPending}>
            {t("saveRoles")}
          </Button>
        </>
      }
    >
      <form
        id="edit-roles-form"
        noValidate
        className="grid gap-4 pb-2"
        onSubmit={form.handleSubmit((values) => save.mutate(values))}
      >
        <RoleFields
          control={form.control}
          register={form.register}
          errors={form.formState.errors}
          roles={options}
        />
        {save.isError ? (
          <Alert variant="destructive" live="assertive">
            {errorMessage(save.error)}
          </Alert>
        ) : null}
      </form>
    </Dialog>
  );
}
