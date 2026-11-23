"use client";

import { CircleAlert } from "lucide-react";
import { type ReactNode, useId } from "react";
import { cn } from "@/lib/utils";
import { Label } from "./label";

export type FieldControlProps = {
  id: string;
  "aria-describedby": string | undefined;
  "aria-invalid": true | undefined;
  required: boolean | undefined;
};

export type FieldProps = {
  label: ReactNode;
  /** Help text shown under the label. */
  description?: ReactNode;
  /** Validation message. Its presence marks the control invalid. */
  error?: ReactNode;
  required?: boolean;
  className?: string;
  /** Override the generated id, e.g. to match an existing `htmlFor`. */
  id?: string;
  children: (control: FieldControlProps) => ReactNode;
};

/**
 * Wires a label, help text and error message to a single control so screen
 * readers announce all three. The control is rendered through a render prop
 * so any input-like element can be used.
 */
export function Field({
  label,
  description,
  error,
  required,
  className,
  id: idProp,
  children,
}: FieldProps) {
  const generatedId = useId();
  const id = idProp ?? generatedId;
  const descriptionId = description ? `${id}-description` : undefined;
  const errorId = error ? `${id}-error` : undefined;
  const describedBy =
    [descriptionId, errorId].filter(Boolean).join(" ") || undefined;

  return (
    <div className={cn("grid gap-1.5", className)}>
      <Label htmlFor={id} required={required}>
        {label}
      </Label>
      {description ? (
        <p id={descriptionId} className="text-sm text-muted-foreground">
          {description}
        </p>
      ) : null}
      {children({
        id,
        "aria-describedby": describedBy,
        "aria-invalid": error ? true : undefined,
        required,
      })}
      {error ? (
        <p
          id={errorId}
          className="flex items-start gap-1.5 text-sm font-medium text-destructive-soft-foreground"
        >
          <CircleAlert aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
          <span>{error}</span>
        </p>
      ) : null}
    </div>
  );
}
