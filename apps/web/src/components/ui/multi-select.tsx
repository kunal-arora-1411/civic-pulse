"use client";

import { Check, ChevronDown } from "lucide-react";
import {
  type ReactNode,
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import { cn } from "@/lib/utils";
import { inputClasses } from "./input";

export type MultiSelectOption = {
  value: string;
  label: string;
  icon?: ReactNode;
};

/**
 * A disclosure holding a group of checkboxes. Native checkboxes keep
 * keyboard and screen reader behaviour standard (Tab, Space), which a
 * custom listbox would have to rebuild. The button summarises the choice
 * ("Status: 2 selected") so the state is readable when closed.
 */
export function MultiSelect({
  label,
  options,
  value,
  onChange,
  allLabel,
  selectedLabel,
  className,
}: {
  label: string;
  options: MultiSelectOption[];
  value: string[];
  onChange: (value: string[]) => void;
  /** Shown when nothing is selected, e.g. "All statuses". */
  allLabel: string;
  /** Shown for several selections, e.g. "3 selected". */
  selectedLabel: (count: number) => string;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const panelId = useId();
  const labelId = useId();
  useLayoutEffect(() => () => setOpen(false), []);

  useEffect(() => {
    if (!open) return;
    const onPointer = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpen(false);
        rootRef.current?.querySelector("button")?.focus();
      }
    };
    document.addEventListener("pointerdown", onPointer);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onPointer);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const summary =
    value.length === 0
      ? allLabel
      : value.length === 1
        ? (options.find((option) => option.value === value[0])?.label ??
          selectedLabel(1))
        : selectedLabel(value.length);

  const toggle = (option: string) =>
    onChange(
      value.includes(option)
        ? value.filter((item) => item !== option)
        : [...value, option],
    );

  return (
    <div ref={rootRef} className={cn("relative grid gap-1.5", className)}>
      <span id={labelId} className="text-sm font-semibold leading-none">
        {label}
      </span>
      <button
        type="button"
        aria-expanded={open}
        aria-controls={panelId}
        aria-labelledby={`${labelId} ${panelId}-summary`}
        onClick={() => setOpen((current) => !current)}
        className={cn(
          inputClasses,
          "cursor-pointer items-center justify-between gap-2 text-start",
          value.length > 0 && "border-primary",
        )}
      >
        <span id={`${panelId}-summary`} className="truncate">
          {summary}
        </span>
        <ChevronDown
          aria-hidden="true"
          className="size-4 shrink-0 text-muted-foreground"
        />
      </button>
      <fieldset
        id={panelId}
        hidden={!open}
        aria-labelledby={labelId}
        className="absolute top-full z-40 mt-1 grid max-h-72 w-full min-w-56 gap-0.5 overflow-y-auto rounded-xl border border-border bg-card p-1.5 shadow-raised"
      >
        {options.map((option) => {
          const checked = value.includes(option.value);
          return (
            <label
              key={option.value}
              className="flex cursor-pointer items-center gap-2.5 rounded-md px-2.5 py-2 text-sm hover:bg-muted has-focus-visible:ring-2 has-focus-visible:ring-ring"
            >
              <input
                type="checkbox"
                className="sr-only"
                checked={checked}
                onChange={() => toggle(option.value)}
              />
              <span
                aria-hidden="true"
                className={cn(
                  "grid size-4 shrink-0 place-items-center rounded border",
                  checked
                    ? "border-primary bg-primary text-primary-foreground"
                    : "border-input",
                )}
              >
                {checked ? <Check className="size-3" /> : null}
              </span>
              {option.icon}
              <span className="truncate">{option.label}</span>
            </label>
          );
        })}
      </fieldset>
    </div>
  );
}
