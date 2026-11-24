"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CircleAlert, RotateCcw, Save } from "lucide-react";
import { useTranslations } from "next-intl";
import { type ReactNode, useEffect, useId, useMemo, useState } from "react";
import { PageLoading } from "@/components/page-loading";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useToast } from "@/components/ui/toast";
import { useErrorMessage } from "@/hooks/use-error-message";
import { hasPermission } from "@/lib/auth/access";
import { useSession } from "@/lib/auth/use-session";
import {
  type FormErrors,
  type FormValues,
  toForm,
} from "@/lib/settings/config";
import { cn } from "@/lib/utils";

/**
 * Load, edit, validate and save one settings document. Values are kept
 * as typed strings; errors show once the user has tried to save, and
 * then update as they type. "Restore defaults" only fills the form, so
 * nothing changes until Save.
 */
export function useSettingsForm<T extends object>({
  queryKey,
  load,
  save,
  validate,
  fromValues,
  defaults,
}: {
  queryKey: readonly unknown[];
  load: (signal: AbortSignal) => Promise<T>;
  save: (config: T) => Promise<T>;
  validate: (values: FormValues) => FormErrors;
  fromValues: (values: FormValues) => T;
  defaults: T;
}) {
  const queryClient = useQueryClient();
  const { user } = useSession();
  const canManage = hasPermission(user, "config:manage");
  const query = useQuery({
    queryKey,
    queryFn: ({ signal }) => load(signal),
  });
  const [values, setValues] = useState<FormValues | null>(null);
  const [saved, setSaved] = useState<FormValues | null>(null);
  const [attempted, setAttempted] = useState(false);
  const [restored, setRestored] = useState(false);

  useEffect(() => {
    if (!query.data) return;
    const loaded = toForm(query.data);
    setSaved(loaded);
    setValues((current) => current ?? loaded);
  }, [query.data]);

  const errors = useMemo(
    () => (values && attempted ? validate(values) : {}),
    [values, attempted, validate],
  );
  const dirty =
    values !== null &&
    saved !== null &&
    Object.keys(values).some((key) => values[key] !== saved[key]);

  const mutation = useMutation({
    mutationFn: (config: T) => save(config),
    onSuccess: (config) => {
      queryClient.setQueryData(queryKey, config);
      const next = toForm(config);
      setSaved(next);
      setValues(next);
      setAttempted(false);
      setRestored(false);
    },
  });

  return {
    query,
    values,
    errors,
    dirty,
    canManage,
    restored,
    mutation,
    setValue: (path: string, value: string) => {
      setRestored(false);
      setValues((current) =>
        current ? { ...current, [path]: value } : current,
      );
    },
    restoreDefaults: () => {
      setValues(toForm(defaults));
      setRestored(true);
    },
    submit: () => {
      if (!values) return false;
      setAttempted(true);
      if (Object.keys(validate(values)).length > 0) return false;
      mutation.mutate(fromValues(values));
      return true;
    },
  };
}

/** What the shared pieces need from a form, whatever document it edits. */
export type SettingsForm = {
  query: {
    isPending: boolean;
    isError: boolean;
    error: unknown;
    refetch: () => unknown;
  };
  values: FormValues | null;
  errors: FormErrors;
  dirty: boolean;
  canManage: boolean;
  restored: boolean;
  mutation: {
    isPending: boolean;
    isError: boolean;
    isSuccess: boolean;
    error: unknown;
  };
  setValue: (path: string, value: string) => void;
  restoreDefaults: () => void;
  submit: () => boolean;
};

/** A number input wired to a settings form path. */
export function NumberField({
  form,
  path,
  label,
  help,
  errorText,
  defaultValue,
  step = "0.01",
  suffix,
  className,
}: {
  form: SettingsForm;
  path: string;
  label: string;
  help?: ReactNode;
  /** Already translated, from form.errors[path]. */
  errorText?: string;
  defaultValue?: string | number;
  step?: string;
  suffix?: string;
  className?: string;
}) {
  const t = useTranslations("admin.settings");
  const id = useId();
  const helpId = `${id}-help`;
  const errorId = `${id}-error`;
  // Help sits under the input rather than above it, so the inputs in a
  // grid line up however long each explanation is.
  return (
    <div className={cn("grid content-start gap-1.5", className)}>
      <Label htmlFor={id}>{label}</Label>
      <div className="flex items-center gap-2">
        <Input
          id={id}
          type="number"
          inputMode="decimal"
          step={step}
          value={form.values?.[path] ?? ""}
          onChange={(event) => form.setValue(path, event.target.value)}
          disabled={!form.canManage}
          aria-invalid={errorText ? true : undefined}
          aria-describedby={[errorText ? errorId : null, helpId]
            .filter(Boolean)
            .join(" ")}
          className="w-32 tabular-nums"
        />
        {suffix ? (
          <span className="text-sm text-muted-foreground">{suffix}</span>
        ) : null}
      </div>
      {errorText ? (
        <p
          id={errorId}
          className="flex items-start gap-1.5 text-sm font-medium text-destructive-soft-foreground"
        >
          <CircleAlert aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
          <span>{errorText}</span>
        </p>
      ) : null}
      <p id={helpId} className="text-sm text-muted-foreground">
        {help}
        {defaultValue !== undefined ? (
          <span className="block text-xs">
            {t("default", { value: String(defaultValue) })}
          </span>
        ) : null}
      </p>
    </div>
  );
}

export function SettingsSection({
  title,
  description,
  children,
  className,
}: {
  title: string;
  description?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  const headingId = useId();
  return (
    <Card
      role="region"
      aria-labelledby={headingId}
      className={cn("grid gap-5 p-5 sm:p-6", className)}
    >
      <div className="grid gap-1">
        <h2 id={headingId} className="text-lg font-semibold">
          {title}
        </h2>
        {description ? (
          <p className="text-sm text-muted-foreground">{description}</p>
        ) : null}
      </div>
      {children}
    </Card>
  );
}

/**
 * Loading and error states, the read-only notice, and the sticky footer
 * with Save and Restore defaults around a settings form.
 */
export function SettingsFrame({
  form,
  savedMessage,
  children,
}: {
  form: SettingsForm;
  savedMessage: string;
  children: ReactNode;
}) {
  const t = useTranslations("admin.settings");
  const errorMessage = useErrorMessage();
  const { toast } = useToast();
  const errorCount = Object.keys(form.errors).length;

  useEffect(() => {
    if (form.mutation.isSuccess)
      toast({ variant: "success", title: savedMessage });
  }, [form.mutation.isSuccess, savedMessage, toast]);

  if (form.query.isPending || !form.values) {
    if (form.query.isError) {
      return (
        <Alert variant="destructive" live="assertive" title={t("loadError")}>
          <p>{errorMessage(form.query.error)}</p>
          <Button
            variant="outline"
            size="sm"
            className="mt-3"
            onClick={() => form.query.refetch()}
          >
            {t("retry")}
          </Button>
        </Alert>
      );
    }
    return <PageLoading />;
  }

  return (
    <form
      noValidate
      className="grid gap-6"
      onSubmit={(event) => {
        event.preventDefault();
        form.submit();
      }}
    >
      {form.canManage ? null : <Alert variant="info">{t("readOnly")}</Alert>}
      {children}
      {errorCount > 0 ? (
        <Alert variant="destructive" live="assertive">
          {t("fixErrors", { count: errorCount })}
        </Alert>
      ) : null}
      {form.mutation.isError ? (
        <Alert variant="destructive" live="assertive">
          {errorMessage(form.mutation.error)}
        </Alert>
      ) : null}
      {form.canManage ? (
        <div className="sticky bottom-0 z-20 -mx-4 flex flex-col-reverse gap-2 border-t border-border bg-background/95 px-4 py-3 backdrop-blur sm:mx-0 sm:flex-row sm:items-center sm:justify-between sm:rounded-xl sm:border sm:px-4">
          <div className="flex items-center gap-3">
            <Button variant="ghost" onClick={form.restoreDefaults}>
              <RotateCcw aria-hidden="true" />
              {t("restoreDefaults")}
            </Button>
            <output className="text-sm text-muted-foreground">
              {form.restored
                ? t("defaultsRestored")
                : form.dirty
                  ? t("unsaved")
                  : ""}
            </output>
          </div>
          <Button type="submit" loading={form.mutation.isPending}>
            <Save aria-hidden="true" />
            {t("save")}
          </Button>
        </div>
      ) : null}
    </form>
  );
}
