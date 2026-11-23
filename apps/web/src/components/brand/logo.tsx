import { cn } from "@/lib/utils";

/** The CivicPulse mark: a map pin whose centre carries a pulse line. */
export function LogoMark({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 32 32"
      aria-hidden="true"
      focusable="false"
      className={cn("size-8 shrink-0", className)}
    >
      <rect width="32" height="32" rx="9" className="fill-primary" />
      <path
        d="M16 6.5c-4.4 0-8 3.4-8 7.7 0 5.6 6.6 11 7.4 11.6a1 1 0 0 0 1.2 0c.8-.6 7.4-6 7.4-11.6 0-4.3-3.6-7.7-8-7.7Z"
        className="fill-primary-foreground"
      />
      <path
        d="M10.5 14.5h3l1.4-3 2.4 6 1.5-3h2.7"
        fill="none"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
        className="stroke-primary"
      />
      <circle cx="25" cy="7" r="3" className="fill-accent" />
    </svg>
  );
}

export function Logo({ className }: { className?: string }) {
  return (
    <span className={cn("inline-flex items-center gap-2.5", className)}>
      <LogoMark />
      <span className="font-display text-lg font-semibold tracking-tight">
        CivicPulse
      </span>
    </span>
  );
}
