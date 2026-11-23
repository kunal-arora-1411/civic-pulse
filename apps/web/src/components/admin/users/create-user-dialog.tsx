"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useRef } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { useToast } from "@/components/ui/toast";
import { useErrorMessage } from "@/hooks/use-error-message";
import { type CreateUserBody, createUser, isApiError } from "@/lib/api";
import { useSession } from "@/lib/auth/use-session";
import { normalizeIndianPhone } from "@/lib/phone";
import {
  assignableRoles,
  emptyRoleRow,
  RoleFields,
  roleRowsSchema,
  toRoleInputs,
} from "./role-fields";

function newKey(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

/**
 * Idempotency keys follow the request body: retrying the same body (say,
 * after a timeout whose request actually succeeded) reuses the key so the
 * server replays the first result instead of creating a duplicate. Editing
 * the form produces a different body and therefore a fresh key; reusing
 * the old one would get `422 idempotency_key_reused`.
 */
function useIdempotencyKey() {
  const last = useRef<{ body: string; key: string } | null>(null);
  return {
    keyFor(body: unknown): string {
      const serialized = JSON.stringify(body);
      if (last.current?.body !== serialized) {
        last.current = { body: serialized, key: newKey() };
      }
      return last.current.key;
    },
    reset() {
      last.current = null;
    },
  };
}

export function CreateUserDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const t = useTranslations("admin.users");
  const tCommon = useTranslations("common");
  const errorMessage = useErrorMessage();
  const { toast } = useToast();
  const queryClient = useQueryClient();
  const { user: actor } = useSession();
  const idempotency = useIdempotencyKey();

  const schema = z.object({
    phone: z
      .string()
      .trim()
      .min(1, t("phoneRequired"))
      .refine((v) => normalizeIndianPhone(v) !== null, t("phoneInvalid")),
    display_name: z
      .string()
      .trim()
      .min(2, t("nameRequired"))
      .max(100, t("nameTooLong")),
    email: z
      .string()
      .trim()
      .refine(
        (v) => v === "" || z.email().safeParse(v).success,
        t("emailInvalid"),
      ),
    roles: roleRowsSchema({
      roleRequired: t("roleRequired"),
      rolesRequired: t("rolesRequired"),
      duplicate: t("rolesDuplicate"),
    }),
  });
  type FormValues = z.input<typeof schema>;

  const defaults: FormValues = {
    phone: "",
    display_name: "",
    email: "",
    roles: [{ ...emptyRoleRow }],
  };
  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: defaults,
  });

  const create = useMutation({
    mutationFn: (body: CreateUserBody) =>
      createUser(body, { idempotencyKey: idempotency.keyFor(body) }),
    onSuccess: (created) => {
      idempotency.reset();
      queryClient.invalidateQueries({ queryKey: ["admin", "users"] });
      toast({
        variant: "success",
        title: t("created", { name: created.display_name ?? created.phone }),
      });
      close();
    },
    onError: (error) => {
      if (isApiError(error, "conflict")) {
        form.setError(
          "phone",
          { message: t("phoneTaken") },
          { shouldFocus: true },
        );
      }
    },
  });

  function close() {
    form.reset(defaults);
    create.reset();
    onOpenChange(false);
  }

  const onSubmit = form.handleSubmit((values) => {
    const phone = normalizeIndianPhone(values.phone);
    if (!phone) return;
    create.mutate({
      phone,
      display_name: values.display_name.trim(),
      ...(values.email.trim() ? { email: values.email.trim() } : {}),
      roles: toRoleInputs(values.roles),
    });
  });

  const { errors } = form.formState;
  const formError =
    create.isError && !isApiError(create.error, "conflict")
      ? errorMessage(create.error)
      : null;

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => (next ? onOpenChange(true) : close())}
      title={t("createTitle")}
      description={t("createDescription")}
      closeLabel={tCommon("close")}
      className="max-w-3xl"
      footer={
        <>
          <Button variant="outline" onClick={close}>
            {t("cancel")}
          </Button>
          <Button
            type="submit"
            form="create-user-form"
            loading={create.isPending}
          >
            {t("createSubmit")}
          </Button>
        </>
      }
    >
      <form
        id="create-user-form"
        noValidate
        onSubmit={onSubmit}
        className="grid gap-5 pb-2"
      >
        <div className="grid gap-4 sm:grid-cols-2">
          <Field
            label={t("nameLabel")}
            error={errors.display_name?.message}
            required
          >
            {(control) => (
              <Input
                {...control}
                {...form.register("display_name")}
                autoComplete="off"
              />
            )}
          </Field>
          <Field
            label={t("phoneLabel")}
            description={t("phoneDescription")}
            error={errors.phone?.message}
            required
          >
            {(control) => (
              <Input
                {...control}
                {...form.register("phone")}
                type="tel"
                inputMode="tel"
                autoComplete="off"
                placeholder="98765 43210"
                className="font-mono"
              />
            )}
          </Field>
          <Field
            label={t("emailLabel")}
            description={t("optional")}
            error={errors.email?.message}
            className="sm:col-span-2"
          >
            {(control) => (
              <Input
                {...control}
                {...form.register("email")}
                type="email"
                autoComplete="off"
              />
            )}
          </Field>
        </div>

        <RoleFields
          control={form.control}
          register={form.register}
          errors={errors}
          roles={assignableRoles(actor, { staffOnly: true })}
        />

        {formError ? (
          <Alert variant="destructive" live="assertive">
            {formError}
          </Alert>
        ) : null}
      </form>
    </Dialog>
  );
}
