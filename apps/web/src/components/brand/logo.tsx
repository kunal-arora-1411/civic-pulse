import { cn } from "@/lib/utils";

/**
 * The CivicPulse mark: a map pin whose centre carries a pulse line. Its
 * colours are fixed, not themed, so it matches the favicon (app/icon.svg)
 * in light and dark mode alike.
 */
export function LogoMark({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 32 32"
      aria-hidden="true"
      focusable="false"
      className={cn("size-8 shrink-0", className)}
    >
      <rect width="32" height="32" rx="9" fill="#0f5d57" />
      <path
        d="M16 6.5c-4.4 0-8 3.4-8 7.7 0 5.6 6.6 11 7.4 11.6a1 1 0 0 0 1.2 0c.8-.6 7.4-6 7.4-11.6 0-4.3-3.6-7.7-8-7.7Z"
        fill="#fbfdfc"
      />
      <path
        d="M10.5 14.5h3l1.4-3 2.4 6 1.5-3h2.7"
        fill="none"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
        stroke="#0f5d57"
      />
      <circle cx="25" cy="7" r="3" fill="#f2b632" />
    </svg>
  );
}

/**
 * The mark with the name. `compact` keeps the name for screen readers but
 * shows only the mark on phones, where headers are short of room.
 */
export function Logo({
  className,
  compact = false,
}: {
  className?: string;
  compact?: boolean;
}) {
  return (
    <span className={cn("inline-flex items-center gap-2.5", className)}>
      <LogoMark />
      <span
        className={cn(
          "font-display text-lg font-semibold tracking-tight",
          compact && "max-sm:sr-only",
        )}
      >
        CivicPulse
      </span>
    </span>
  );
}
