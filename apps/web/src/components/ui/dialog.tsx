"use client";

import { X } from "lucide-react";
import { type ReactNode, useEffect, useId, useRef } from "react";
import { cn } from "@/lib/utils";
import { Button } from "./button";

export type DialogProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: ReactNode;
  description?: ReactNode;
  /** Accessible label for the close button (the primitive has no strings). */
  closeLabel: string;
  children?: ReactNode;
  footer?: ReactNode;
  className?: string;
};

/**
 * A modal built on the native <dialog> element. `showModal()` gives us the
 * focus trap, Escape handling, inert background and top-layer stacking
 * without a dependency. Focus returns to the opener when it closes.
 *
 * The open state is synced in an effect whose cleanup closes the element.
 * With Cache Components, Next keeps hidden routes mounted inside
 * <Activity>; effects are torn down when a route is hidden, so a dialog
 * never lingers in the top layer over a different page.
 */
export function Dialog({
  open,
  onOpenChange,
  title,
  description,
  closeLabel,
  children,
  footer,
  className,
}: DialogProps) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const descriptionId = useId();

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog || !open) return;
    const opener =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;
    if (!dialog.open) dialog.showModal();
    return () => {
      if (dialog.open) dialog.close();
      opener?.focus();
    };
  }, [open]);

  return (
    // biome-ignore lint/a11y/useKeyWithClickEvents: Escape is handled natively through the cancel event
    <dialog
      ref={ref}
      aria-labelledby={titleId}
      aria-describedby={description ? descriptionId : undefined}
      onCancel={(event) => {
        event.preventDefault();
        onOpenChange(false);
      }}
      onClick={(event) => {
        // A click on the ::backdrop is reported on the dialog element itself.
        if (event.target === event.currentTarget) onOpenChange(false);
      }}
      className={cn(
        "m-auto w-[calc(100%-2rem)] max-w-lg rounded-2xl border border-border bg-card p-0 text-card-foreground shadow-raised",
        "open:motion-safe:animate-rise backdrop:motion-safe:animate-fade",
        className,
      )}
    >
      {open ? (
        <div className="grid max-h-[85dvh] grid-rows-[auto_1fr_auto]">
          <header className="flex items-start justify-between gap-4 p-5 pb-2 sm:p-6 sm:pb-2">
            <div className="grid gap-1">
              <h2 id={titleId} className="text-lg font-semibold">
                {title}
              </h2>
              {description ? (
                <p id={descriptionId} className="text-sm text-muted-foreground">
                  {description}
                </p>
              ) : null}
            </div>
            <Button
              variant="ghost"
              size="icon-sm"
              aria-label={closeLabel}
              onClick={() => onOpenChange(false)}
              className="-me-2 -mt-1"
            >
              <X aria-hidden="true" />
            </Button>
          </header>
          <div className="overflow-y-auto px-5 py-3 sm:px-6">{children}</div>
          {footer ? (
            <footer className="flex flex-col-reverse gap-2 border-t border-border px-5 py-4 sm:flex-row sm:justify-end sm:px-6">
              {footer}
            </footer>
          ) : null}
        </div>
      ) : null}
    </dialog>
  );
}
