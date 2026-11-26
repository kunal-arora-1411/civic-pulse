import { cn } from "@/lib/utils";

/**
 * The sweeping teal-to-marigold arcs from the marketing site, for dark
 * hero panels. Purely decorative.
 */
export function BrandArcs({ className }: { className?: string }) {
  return (
    <svg
      aria-hidden="true"
      focusable="false"
      viewBox="0 0 400 400"
      fill="none"
      preserveAspectRatio="xMaxYMax slice"
      className={cn("pointer-events-none", className)}
    >
      <defs>
        <linearGradient id="cp-arc" x1="0" y1="1" x2="1" y2="0">
          <stop offset="0%" stopColor="var(--brand-1)" />
          <stop offset="55%" stopColor="var(--brand-2)" />
          <stop offset="100%" stopColor="var(--brand-3)" />
        </linearGradient>
      </defs>
      <path
        d="M120 420 C 160 240, 280 120, 440 90"
        stroke="url(#cp-arc)"
        strokeWidth="56"
        strokeLinecap="round"
        opacity="0.95"
      />
      <path
        d="M210 440 C 240 300, 330 210, 450 190"
        stroke="url(#cp-arc)"
        strokeWidth="28"
        strokeLinecap="round"
        opacity="0.55"
      />
      <path
        d="M40 430 C 90 200, 240 40, 450 0"
        stroke="url(#cp-arc)"
        strokeWidth="10"
        strokeLinecap="round"
        opacity="0.4"
      />
    </svg>
  );
}
