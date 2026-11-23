"use client";

import { CircleAlert, CircleCheck, Info, X } from "lucide-react";
import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
} from "react";
import { cn } from "@/lib/utils";

export type ToastVariant = "info" | "success" | "error";

export type ToastOptions = {
  title: string;
  description?: string;
  variant?: ToastVariant;
  /** Milliseconds before auto-dismissal. Errors stay a little longer. */
  duration?: number;
};

type ToastItem = Required<Omit<ToastOptions, "description">> & {
  id: number;
  description?: string;
};

type ToastContextValue = {
  toast: (options: ToastOptions) => void;
  dismiss: (id: number) => void;
};

const ToastContext = createContext<ToastContextValue | null>(null);

const icons = { info: Info, success: CircleCheck, error: CircleAlert };

/**
 * Transient notifications. Two live regions are always present in the DOM
 * (screen readers ignore regions that appear together with their content):
 * a polite one for confirmations and an assertive one for errors.
 */
export function ToastProvider({
  children,
  dismissLabel,
}: {
  children: ReactNode;
  dismissLabel: string;
}) {
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const nextId = useRef(0);
  const timers = useRef(new Map<number, ReturnType<typeof setTimeout>>());

  const dismiss = useCallback((id: number) => {
    setToasts((current) => current.filter((item) => item.id !== id));
    const timer = timers.current.get(id);
    if (timer) clearTimeout(timer);
    timers.current.delete(id);
  }, []);

  const toast = useCallback(
    ({ title, description, variant = "info", duration }: ToastOptions) => {
      const id = nextId.current++;
      const ms = duration ?? (variant === "error" ? 8000 : 5000);
      setToasts((current) => [
        ...current.slice(-3),
        { id, title, description, variant, duration: ms },
      ]);
      timers.current.set(
        id,
        setTimeout(() => dismiss(id), ms),
      );
    },
    [dismiss],
  );

  const value = useMemo(() => ({ toast, dismiss }), [toast, dismiss]);

  const render = (items: ToastItem[]) =>
    items.map((item) => {
      const Icon = icons[item.variant];
      return (
        <div
          key={item.id}
          className={cn(
            "pointer-events-auto flex w-full items-start gap-3 rounded-xl border bg-card p-4 text-sm shadow-raised motion-safe:animate-rise",
            item.variant === "error"
              ? "border-destructive/40"
              : item.variant === "success"
                ? "border-primary/30"
                : "border-border",
          )}
        >
          <Icon
            aria-hidden="true"
            className={cn(
              "mt-0.5 size-5 shrink-0",
              item.variant === "error"
                ? "text-destructive"
                : item.variant === "success"
                  ? "text-primary"
                  : "text-muted-foreground",
            )}
          />
          <div className="grid flex-1 gap-0.5">
            <p className="font-semibold">{item.title}</p>
            {item.description ? (
              <p className="text-muted-foreground">{item.description}</p>
            ) : null}
          </div>
          <button
            type="button"
            onClick={() => dismiss(item.id)}
            aria-label={dismissLabel}
            className="-m-1 rounded-md p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
          >
            <X aria-hidden="true" className="size-4" />
          </button>
        </div>
      );
    });

  return (
    <ToastContext value={value}>
      {children}
      <div className="pointer-events-none fixed inset-x-0 bottom-0 z-50 flex flex-col items-center gap-2 p-4 sm:items-end sm:p-6">
        <output aria-live="polite" className="grid w-full max-w-sm gap-2">
          {render(toasts.filter((item) => item.variant !== "error"))}
        </output>
        <div
          role="alert"
          aria-live="assertive"
          className="grid w-full max-w-sm gap-2"
        >
          {render(toasts.filter((item) => item.variant === "error"))}
        </div>
      </div>
    </ToastContext>
  );
}

export function useToast(): ToastContextValue {
  const context = useContext(ToastContext);
  if (!context) throw new Error("useToast must be used inside <ToastProvider>");
  return context;
}
