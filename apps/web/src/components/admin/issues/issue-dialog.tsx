"use client";

import { useQueryClient } from "@tanstack/react-query";
import { type LucideIcon, RefreshCw } from "lucide-react";
import { useTranslations } from "next-intl";
import { type ReactNode, useCallback, useEffect, useId, useState } from "react";
import { Alert } from "@/components/ui/alert";
import { Button, type ButtonProps } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Field } from "@/components/ui/field";
import { inputClasses } from "@/components/ui/input";
import { type IssueDetail, isApiError } from "@/lib/api";
import { cn } from "@/lib/utils";

export type Conflict = ReturnType<typeof useVersionConflict>;

/**
 * After a mutation that returns the issue: show it at once, and refresh
 * the lists and the map, where its priority or reports may have moved.
 */
export function useApplyIssue() {
  const queryClient = useQueryClient();
  return useCallback(
    (updated: IssueDetail) => {
      queryClient.setQueryData(["issues", "detail", updated.id], updated);
      queryClient.invalidateQueries({ queryKey: ["issues", "list"] });
      queryClient.invalidateQueries({ queryKey: ["issues", "geojson"] });
    },
    [queryClient],
  );
}

export type ChoiceOption<T extends string> = {
  value: T;
  label: ReactNode;
  icon?: LucideIcon;
  hint?: ReactNode;
};

/** A radio group drawn as rows, with an icon and words for each choice. */
export function ChoiceList<T extends string>({
  legend,
  options,
  value,
  onChange,
  error,
}: {
  legend: string;
  options: ChoiceOption<T>[];
  value: T | null;
  onChange: (value: T) => void;
  error?: string;
}) {
  const name = useId();
  const errorId = useId();
  return (
    <fieldset
      className="grid gap-2"
      aria-describedby={error ? errorId : undefined}
    >
      <legend className="mb-1 text-sm font-semibold">{legend}</legend>
      {options.map((option) => {
        const Icon = option.icon;
        const checked = value === option.value;
        return (
          <label
            key={option.value}
            className={cn(
              "flex cursor-pointer items-center gap-3 rounded-lg border px-3 py-2.5 has-focus-visible:ring-3 has-focus-visible:ring-ring/30",
              checked
                ? "border-primary bg-primary-soft"
                : "border-input hover:bg-muted",
            )}
          >
            <input
              type="radio"
              name={name}
              value={option.value}
              checked={checked}
              onChange={() => onChange(option.value)}
              className="size-4 accent-primary"
            />
            {Icon ? <Icon aria-hidden="true" className="size-4" /> : null}
            <span className="font-semibold">{option.label}</span>
            {option.hint ? (
              <span className="ms-auto text-xs text-muted-foreground">
                {option.hint}
              </span>
            ) : null}
          </label>
        );
      })}
      {error ? (
        <p
          id={errorId}
          className="text-sm font-medium text-destructive-soft-foreground"
        >
          {error}
        </p>
      ) : null}
    </fieldset>
  );
}

/**
 * Tracks a 409 version_conflict for one dialog. Like the status dialog,
 * the dialogs on the issue page never retry with the newer version, which
 * would silently overwrite a colleague's change: they explain and offer
 * to reload, keeping what the user typed.
 */
export function useVersionConflict(onReload: () => Promise<unknown>) {
  const [conflict, setConflict] = useState(false);
  const [reloading, setReloading] = useState(false);

  /** True when the error was a version conflict (and is now shown). */
  const check = useCallback((error: unknown) => {
    const hit = isApiError(error, "version_conflict");
    if (hit) setConflict(true);
    return hit;
  }, []);
  const reset = useCallback(() => setConflict(false), []);
  const reload = useCallback(async () => {
    setReloading(true);
    try {
      await onReload();
      setConflict(false);
    } finally {
      setReloading(false);
    }
  }, [onReload]);

  return { conflict, check, reset, reload, reloading };
}

/**
 * The frame every issue action dialog shares: the form, a footer with
 * Cancel and the action, and in place of both, after a version conflict,
 * the explanation and a Reload button.
 */
export function IssueDialog({
  open,
  onOpenChange,
  title,
  description,
  conflict,
  submitLabel,
  submitVariant = "primary",
  onSubmit,
  pending,
  secondary,
  wide = false,
  children,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: ReactNode;
  description?: ReactNode;
  conflict: Conflict;
  submitLabel: ReactNode;
  submitVariant?: ButtonProps["variant"];
  onSubmit: () => void;
  pending: boolean;
  /** Replaces Cancel, e.g. "Back" on a confirmation step. */
  secondary?: ReactNode;
  wide?: boolean;
  children: ReactNode;
}) {
  const t = useTranslations("admin.issueDetail.dialog");
  const { reset } = conflict;
  useEffect(() => {
    if (open) reset();
  }, [open, reset]);

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={title}
      description={description}
      closeLabel={t("close")}
      className={cn(wide && "max-w-2xl")}
      footer={
        conflict.conflict ? (
          <>
            <Button variant="outline" onClick={() => onOpenChange(false)}>
              {t("cancel")}
            </Button>
            <Button onClick={conflict.reload} loading={conflict.reloading}>
              <RefreshCw aria-hidden="true" />
              {t("reload")}
            </Button>
          </>
        ) : (
          <>
            {secondary ?? (
              <Button variant="outline" onClick={() => onOpenChange(false)}>
                {t("cancel")}
              </Button>
            )}
            <Button
              variant={submitVariant}
              onClick={onSubmit}
              loading={pending}
            >
              {submitLabel}
            </Button>
          </>
        )
      }
    >
      {conflict.conflict ? (
        <Alert variant="warning" live="assertive" title={t("conflictTitle")}>
          {t("conflictBody")}
        </Alert>
      ) : (
        children
      )}
    </Dialog>
  );
}

/** A required reason, for the staff-only record of why. */
export function ReasonField({
  value,
  onChange,
  error,
  required = true,
  help,
}: {
  value: string;
  onChange: (value: string) => void;
  error?: string;
  required?: boolean;
  help?: string;
}) {
  const t = useTranslations("admin.issueDetail.dialog");
  return (
    <Field
      label={required ? t("reason") : t("reasonOptional")}
      description={help ?? t("reasonHelp")}
      required={required}
      error={error}
    >
      {(control) => (
        <textarea
          {...control}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          rows={3}
          maxLength={1000}
          className={cn(inputClasses, "h-auto py-2")}
        />
      )}
    </Field>
  );
}
