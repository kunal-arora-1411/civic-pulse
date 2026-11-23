"use client";

import type { ComponentProps, Ref } from "react";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

export const CODE_LENGTH = 6;

type CodeInputProps = Omit<
  ComponentProps<"input">,
  "value" | "onChange" | "type"
> & {
  value: string;
  onValueChange: (value: string) => void;
  /** Fires once when the sixth digit arrives (typed, pasted or autofilled). */
  onComplete?: (value: string) => void;
  ref?: Ref<HTMLInputElement>;
};

/**
 * One input for the whole code, not six boxes: it pastes cleanly, SMS
 * autofill (`autocomplete="one-time-code"`) can fill it in one go, and
 * screen readers announce a single field. There's deliberately no
 * maxLength: it would truncate a pasted "123 456" before we can strip the
 * space, so non-digits are removed and the value is clamped here instead.
 */
export function CodeInput({
  value,
  onValueChange,
  onComplete,
  className,
  ...props
}: CodeInputProps) {
  return (
    <Input
      type="text"
      inputMode="numeric"
      autoComplete="one-time-code"
      pattern="[0-9]*"
      spellCheck={false}
      value={value}
      onChange={(event) => {
        const next = event.target.value
          .replace(/\D/g, "")
          .slice(0, CODE_LENGTH);
        onValueChange(next);
        if (next.length === CODE_LENGTH && value.length !== CODE_LENGTH) {
          onComplete?.(next);
        }
      }}
      className={cn(
        "h-14 text-center font-mono text-2xl tracking-[0.5em] placeholder:tracking-[0.5em]",
        className,
      )}
      placeholder="••••••"
      {...props}
    />
  );
}
