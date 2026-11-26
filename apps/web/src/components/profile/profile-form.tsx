"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Lock, Phone } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { useToast } from "@/components/ui/toast";
import { useErrorMessage } from "@/hooks/use-error-message";
import { type AppLocale, localeNames, locales } from "@/i18n/routing";
import { switchLocale } from "@/i18n/switch-locale";
import {
  type CurrentUser,
  session,
  type UpdateMeBody,
  updateMe,
} from "@/lib/api";
import { formatIndianPhone } from "@/lib/phone";

export function ProfileForm({ user }: { user: CurrentUser }) {
  const t = useTranslations("profile");
  const tRoles = useTranslations("roles");
  const currentLocale = useLocale();
  const errorMessage = useErrorMessage();
  const { toast } = useToast();
  const queryClient = useQueryClient();

  const schema = z.object({
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
    locale: z.enum(locales),
  });
  type FormValues = z.input<typeof schema>;

  const initialLocale = (locales as readonly string[]).includes(user.locale)
    ? (user.locale as AppLocale)
    : (currentLocale as AppLocale);

  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      display_name: user.display_name ?? "",
      email: user.email ?? "",
      locale: initialLocale,
    },
  });

  const save = useMutation({
    mutationFn: (body: UpdateMeBody) => updateMe(body),
    onSuccess: (updated) => {
      session.setUser(updated);
      // An added or removed email changes whether email can be delivered.
      void queryClient.invalidateQueries({
        queryKey: ["notification-preferences"],
      });
      form.reset({
        display_name: updated.display_name ?? "",
        email: updated.email ?? "",
        locale: (locales as readonly string[]).includes(updated.locale)
          ? (updated.locale as AppLocale)
          : initialLocale,
      });
      if (
        updated.locale !== currentLocale &&
        (locales as readonly string[]).includes(updated.locale)
      ) {
        // Switching language reloads the page in the new locale.
        switchLocale(updated.locale as AppLocale);
        return;
      }
      toast({ variant: "success", title: t("saved") });
    },
  });

  const onSubmit = form.handleSubmit((values) => {
    const email = values.email.trim();
    save.mutate({
      display_name: values.display_name.trim(),
      email: email === "" ? null : email,
      locale: values.locale,
    });
  });

  const { errors, isDirty } = form.formState;

  return (
    <div className="grid gap-6">
      <Card>
        <CardHeader>
          <CardTitle>{t("accountTitle")}</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-4">
          <div className="flex items-start gap-3">
            <span className="grid size-10 shrink-0 place-items-center rounded-lg bg-secondary text-secondary-foreground">
              <Phone aria-hidden="true" className="size-5" />
            </span>
            <div className="grid gap-0.5">
              <p className="text-sm font-semibold">{t("phoneLabel")}</p>
              <p className="font-mono">{formatIndianPhone(user.phone)}</p>
              <p className="flex items-center gap-1.5 text-sm text-muted-foreground">
                <Lock aria-hidden="true" className="size-3.5" />
                {t("phoneHelp")}
              </p>
            </div>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {user.roles.map((assignment) => (
              <Badge
                key={`${assignment.role}-${assignment.department_id}-${assignment.jurisdiction_id}`}
                variant={assignment.role === "citizen" ? "neutral" : "primary"}
              >
                {tRoles(assignment.role)}
              </Badge>
            ))}
          </div>
        </CardContent>
      </Card>

      <Card>
        <form noValidate onSubmit={onSubmit}>
          <CardHeader>
            <CardTitle>{t("detailsTitle")}</CardTitle>
          </CardHeader>
          <CardContent className="grid gap-5">
            <Field
              label={t("nameLabel")}
              error={errors.display_name?.message}
              required
            >
              {(control) => (
                <Input
                  {...control}
                  {...form.register("display_name")}
                  autoComplete="name"
                />
              )}
            </Field>
            <Field
              label={t("emailLabel")}
              description={t("emailHelp")}
              error={errors.email?.message}
            >
              {(control) => (
                <Input
                  {...control}
                  {...form.register("email")}
                  type="email"
                  autoComplete="email"
                />
              )}
            </Field>
            <Field
              label={t("languageLabel")}
              description={t("languageHelp")}
              error={errors.locale?.message}
            >
              {(control) => (
                <Select {...control} {...form.register("locale")}>
                  {locales.map((value) => (
                    <option key={value} value={value} lang={value}>
                      {localeNames[value]}
                    </option>
                  ))}
                </Select>
              )}
            </Field>
            {save.isError ? (
              <Alert variant="destructive" live="assertive">
                {errorMessage(save.error)}
              </Alert>
            ) : null}
          </CardContent>
          <CardFooter className="justify-end">
            <Button
              variant="ghost"
              disabled={!isDirty || save.isPending}
              onClick={() => form.reset()}
            >
              {t("discard")}
            </Button>
            <Button type="submit" loading={save.isPending} disabled={!isDirty}>
              {t("save")}
            </Button>
          </CardFooter>
        </form>
      </Card>
    </div>
  );
}
