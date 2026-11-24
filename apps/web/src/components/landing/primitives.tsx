import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

/**
 * Two-tone headings: the first sentence in ink, the rest muted. Messages
 * mark the muted part with <muted>…</muted>; pass this to t.rich.
 */
export const muted = (tone: "light" | "dark" = "light") =>
  function Muted(chunks: ReactNode) {
    return (
      <span className={tone === "dark" ? "text-white/55" : "text-lp-mute"}>
        {chunks}
      </span>
    );
  };

/** Same, for small text where the muted part must still read at 4.5:1. */
export const mutedSmall = (chunks: ReactNode) => (
  <span className="text-lp-mute-2">{chunks}</span>
);

/** The 1200px content column the whole page aligns to. */
export function Container({
  className,
  children,
}: {
  className?: string;
  children: ReactNode;
}) {
  return (
    <div
      className={cn("mx-auto w-full max-w-[1200px] px-5 sm:px-8", className)}
    >
      {children}
    </div>
  );
}

export type PinStatus = "open" | "progress" | "fixed";

const pinFill: Record<PinStatus, string> = {
  open: "#F2B632",
  progress: "#1B2733",
  fixed: "#0F5D57",
};

/** A report marker. Decorative: the status is always given in words nearby. */
export function Pin({
  status,
  className,
}: {
  status: PinStatus;
  className?: string;
}) {
  return (
    <svg
      viewBox="0 0 36 46"
      aria-hidden="true"
      focusable="false"
      className={cn("h-[46px] w-9", className)}
    >
      <ellipse cx="18" cy="43" rx="7" ry="2.5" fill="#10191F" opacity="0.18" />
      <path
        d="M18 1.5C8.9 1.5 1.5 8.6 1.5 17.5c0 11.4 13.6 22.6 15.3 24a1.9 1.9 0 0 0 2.4 0c1.7-1.4 15.3-12.6 15.3-24C34.5 8.6 27.1 1.5 18 1.5Z"
        fill={pinFill[status]}
        stroke="#fff"
        strokeWidth="2.5"
      />
      {status === "open" ? (
        <>
          <path
            d="M18 10v9"
            stroke="#10191F"
            strokeWidth="2.6"
            strokeLinecap="round"
          />
          <circle cx="18" cy="24" r="1.7" fill="#10191F" />
        </>
      ) : status === "progress" ? (
        <>
          <circle
            cx="18"
            cy="17.5"
            r="6"
            fill="none"
            stroke="#FAF9F5"
            strokeWidth="2.4"
          />
          <path
            d="M18 14.5v3.2l2 1.4"
            stroke="#FAF9F5"
            strokeWidth="2"
            strokeLinecap="round"
          />
        </>
      ) : (
        <path
          d="m12 17.8 4 4 8-8.3"
          fill="none"
          stroke="#FAF9F5"
          strokeWidth="2.8"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      )}
    </svg>
  );
}

const badgeTone = {
  open: "bg-lp-marigold-soft text-[#7a4f00] [--dot:#F2B632]",
  progress: "bg-lp-wash text-lp-ink-2 [--dot:#3D4850]",
  fixed: "bg-lp-teal-soft text-lp-teal [--dot:#16A08E]",
  overdue: "bg-lp-marigold-soft text-lp-red [--dot:#C23B26]",
} as const;

export function StatusBadge({
  tone,
  children,
}: {
  tone: keyof typeof badgeTone;
  children: ReactNode;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full py-0.5 ps-2 pe-2.5 text-xs font-medium whitespace-nowrap",
        badgeTone[tone],
      )}
    >
      <span aria-hidden="true" className="size-1.5 rounded-full bg-(--dot)" />
      {children}
    </span>
  );
}

/** Stripe-style flowing ribbon in the brand gradient. Decorative. */
export function Ribbon({
  className,
  variant = "hero",
}: {
  className?: string;
  variant?: "hero" | "banner";
}) {
  const id = `lp-ribbon-${variant}`;
  if (variant === "banner") {
    return (
      <svg
        viewBox="0 0 1200 440"
        preserveAspectRatio="xMaxYMid slice"
        aria-hidden="true"
        focusable="false"
        className={className}
      >
        <defs>
          <linearGradient
            id={`${id}-a`}
            x1="1200"
            y1="0"
            x2="700"
            y2="440"
            gradientUnits="userSpaceOnUse"
          >
            <stop stopColor="#0F5D57" />
            <stop offset="0.4" stopColor="#16A08E" />
            <stop offset="0.7" stopColor="#A6E8D8" />
            <stop offset="1" stopColor="#F2B632" />
          </linearGradient>
          <linearGradient
            id={`${id}-b`}
            x1="1200"
            y1="80"
            x2="760"
            y2="440"
            gradientUnits="userSpaceOnUse"
          >
            <stop stopColor="#16A08E" />
            <stop offset="0.6" stopColor="#F2B632" />
            <stop offset="1" stopColor="#FDF1D6" />
          </linearGradient>
        </defs>
        <g className="lp-ribbon">
          <path
            d="M1300 -60C1060 60 900 220 860 470"
            stroke={`url(#${id}-a)`}
            strokeWidth="170"
            strokeLinecap="round"
            fill="none"
          />
          <path
            d="M1340 20C1140 120 1010 260 990 480"
            stroke={`url(#${id}-b)`}
            strokeWidth="70"
            strokeLinecap="round"
            fill="none"
            opacity="0.9"
          />
          <path
            d="M1260 -90C1010 30 840 200 790 470"
            stroke="#fff"
            strokeOpacity="0.35"
            strokeWidth="3"
            fill="none"
          />
        </g>
      </svg>
    );
  }
  return (
    <svg
      viewBox="0 0 1440 980"
      preserveAspectRatio="xMaxYMin slice"
      aria-hidden="true"
      focusable="false"
      className={className}
    >
      <defs>
        <linearGradient
          id={`${id}-a`}
          x1="1440"
          y1="0"
          x2="1000"
          y2="980"
          gradientUnits="userSpaceOnUse"
        >
          <stop stopColor="#0F5D57" />
          <stop offset="0.35" stopColor="#16A08E" />
          <stop offset="0.65" stopColor="#A6E8D8" />
          <stop offset="1" stopColor="#F2B632" />
        </linearGradient>
        <linearGradient
          id={`${id}-b`}
          x1="1440"
          y1="100"
          x2="1100"
          y2="900"
          gradientUnits="userSpaceOnUse"
        >
          <stop stopColor="#16A08E" />
          <stop offset="0.5" stopColor="#F2B632" />
          <stop offset="1" stopColor="#FDF1D6" />
        </linearGradient>
      </defs>
      <g className="lp-ribbon">
        <path
          d="M1560 -80C1330 120 1180 330 1230 600C1262 770 1360 880 1520 1000"
          stroke={`url(#${id}-a)`}
          strokeWidth="150"
          strokeLinecap="round"
          fill="none"
          opacity="0.95"
        />
        <path
          d="M1600 -40C1400 160 1280 360 1320 610C1345 760 1420 860 1560 960"
          stroke={`url(#${id}-b)`}
          strokeWidth="70"
          strokeLinecap="round"
          fill="none"
          opacity="0.85"
        />
        <path
          d="M1500 -120C1240 80 1090 300 1130 590C1150 740 1230 860 1360 980"
          stroke="#fff"
          strokeOpacity="0.55"
          strokeWidth="6"
          fill="none"
        />
        <path
          d="M1520 -110C1270 90 1130 310 1170 595C1192 745 1270 865 1400 985"
          stroke="#fff"
          strokeOpacity="0.35"
          strokeWidth="3"
          fill="none"
        />
      </g>
    </svg>
  );
}

/** A grey road-photo stand-in, used where the design shows a photo. */
export const photoGradient =
  "bg-[linear-gradient(135deg,#a39c8c,#5e6266)] relative overflow-clip after:absolute after:inset-x-[18%] after:top-[52%] after:h-[26%] after:rounded-[50%] after:bg-[#2f2b24]";
