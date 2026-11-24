import { useTranslations } from "next-intl";
import type { CSSProperties } from "react";
import { Link } from "@/i18n/navigation";
import { cn } from "@/lib/utils";
import { MAP_PINS, MORPH_PIN } from "./data";
import {
  Container,
  muted,
  Pin,
  type PinStatus,
  photoGradient,
  StatusBadge,
} from "./primitives";
import { buttonBase, buttonTone } from "./styles";

const shadow =
  "shadow-[0_1px_2px_rgb(10_15_18/0.05),0_16px_36px_-10px_rgb(10_15_18/0.16)]";

/** The street plan behind the pins: blocks, a park, a river, a crew route. */
function StreetPlan() {
  return (
    <svg
      viewBox="0 0 640 340"
      preserveAspectRatio="xMidYMid slice"
      aria-hidden="true"
      focusable="false"
      className="absolute inset-0 size-full"
    >
      <rect width="640" height="340" fill="#ECE7DA" />
      <g fill="#E2DCCB">
        <rect x="20" y="10" width="150" height="70" rx="8" />
        <rect x="200" y="10" width="120" height="70" rx="8" />
        <rect x="560" y="10" width="90" height="70" rx="8" />
        <rect x="20" y="100" width="65" height="100" rx="8" />
        <rect x="105" y="100" width="65" height="100" rx="8" />
        <rect x="200" y="100" width="120" height="45" rx="8" />
        <rect x="200" y="160" width="120" height="40" rx="8" />
        <rect x="350" y="160" width="190" height="40" rx="8" />
        <rect x="560" y="100" width="90" height="100" rx="8" />
        <rect x="20" y="222" width="150" height="60" rx="8" />
        <rect x="200" y="222" width="120" height="45" rx="8" />
        <rect x="350" y="222" width="190" height="45" rx="8" />
        <rect x="560" y="222" width="90" height="60" rx="8" />
      </g>
      <rect x="350" y="10" width="190" height="130" rx="14" fill="#D5E4C4" />
      <g fill="#BFD6A8">
        <circle cx="385" cy="40" r="11" />
        <circle cx="420" cy="62" r="8" />
        <circle cx="470" cy="38" r="12" />
        <circle cx="505" cy="80" r="10" />
        <circle cx="400" cy="110" r="11" />
        <circle cx="455" cy="118" r="9" />
      </g>
      <path
        d="M-30 320 C 120 280, 230 350, 380 310 S 600 260, 690 300"
        stroke="#CDE2E3"
        strokeWidth="40"
        strokeLinecap="round"
        fill="none"
      />
      <g stroke="#fff" strokeLinecap="round" fill="none">
        <path d="M0 90H640" strokeWidth="12" />
        <path d="M0 211H640" strokeWidth="12" />
        <path d="M185 0V300" strokeWidth="11" />
        <path d="M335 0V300" strokeWidth="9" />
        <path d="M550 0V300" strokeWidth="11" />
        <path d="M95 90V211" strokeWidth="6" />
      </g>
      <path d="M0 300 L640 20" stroke="#FBF8EF" strokeWidth="16" />
      <path
        d="M0 300 L640 20"
        stroke="#F2B632"
        strokeOpacity="0.5"
        strokeWidth="1.5"
        strokeDasharray="8 10"
      />
      <path
        d="M185 190 V90 H335 V211 H470"
        stroke="#0F5D57"
        strokeWidth="2.5"
        strokeDasharray="1 7"
        strokeLinecap="round"
        fill="none"
      />
    </svg>
  );
}

const pinStyle = (x: number, y: number, i = 0) =>
  ({ left: `${x}%`, top: `${y}%`, "--i": i }) as CSSProperties;

export function LiveMap() {
  const t = useTranslations("landing");
  const filters: { label: string; count: number; tone?: PinStatus }[] = [
    { label: t("map.all"), count: 19 },
    { label: t("status.open"), count: 4, tone: "open" },
    { label: t("status.inProgress"), count: 3, tone: "progress" },
    { label: t("status.fixed"), count: 12, tone: "fixed" },
  ];

  return (
    <section
      id="live-map"
      aria-labelledby="lp-map-title"
      className="scroll-mt-20 py-24 sm:py-34"
    >
      <Container className="grid gap-10 sm:gap-12">
        <div className="lp-reveal flex flex-wrap items-end justify-between gap-6">
          <h2
            id="lp-map-title"
            className="max-w-[720px] text-[30px] leading-[1.12] font-medium tracking-[-0.035em] text-lp-ink sm:text-[40px] sm:leading-[1.1]"
          >
            {t.rich("map.title", { muted: muted() })}
          </h2>
          <Link
            href="/reports"
            className={cn(
              buttonBase,
              buttonTone.secondary,
              "h-11 px-4 text-[15px]",
            )}
          >
            {t("map.track")}
          </Link>
        </div>

        <div
          role="img"
          aria-label={t("map.label")}
          className="lp-reveal relative h-[460px] overflow-clip rounded-[20px] border border-lp-hair sm:h-[640px]"
        >
          <div aria-hidden="true" className="absolute inset-0">
            <StreetPlan />
            <div className="absolute inset-0 bg-white/15" />

            {MAP_PINS.map((pin, index) => (
              <span
                key={`${pin.x}-${pin.y}`}
                className="lp-drop absolute -translate-x-1/2 -translate-y-full"
                style={pinStyle(pin.x, pin.y, index)}
              >
                <Pin status={pin.status} />
              </span>
            ))}

            {/* One report closes on a loop: open pin → ripple → fixed pin. */}
            <span
              className="absolute -translate-x-1/2 -translate-y-full"
              style={pinStyle(MORPH_PIN.x, MORPH_PIN.y)}
            >
              <span className="lp-ripple absolute start-1/2 top-[70%] size-20 -translate-x-1/2 -translate-y-1/2 rounded-full border border-lp-teal-vivid/50 bg-lp-teal-vivid/15 opacity-0" />
              <span className="lp-morph-out relative block">
                <Pin status="open" />
              </span>
              <span className="lp-morph-in absolute inset-0 opacity-0">
                <Pin status="fixed" />
              </span>
            </span>

            <div
              className={cn(
                "absolute start-4 top-4 flex items-center gap-0.5 rounded-xl bg-white p-1 sm:start-6 sm:top-6",
                shadow,
              )}
            >
              {filters.map((filter, index) => (
                <span
                  key={filter.label}
                  className={cn(
                    "flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-[13px] font-medium sm:px-3",
                    index === 0 ? "bg-lp-ink text-white" : "text-lp-ink-2",
                    index > 1 && "hidden sm:flex",
                  )}
                >
                  {filter.label}
                  <span
                    className={cn(
                      "font-lp-mono text-xs",
                      index === 0 ? "text-white/60" : "text-lp-mute-2",
                    )}
                  >
                    {filter.count}
                  </span>
                </span>
              ))}
            </div>

            <div
              className={cn(
                "lp-toast absolute end-6 top-6 hidden items-center gap-2.5 rounded-xl bg-lp-ink py-2.5 ps-3 pe-3.5 text-[13px] font-medium text-white md:flex",
                shadow,
              )}
            >
              <span className="size-2 rounded-full bg-lp-marigold" />
              {t("map.toast")}
              <span className="font-lp-mono text-[11px] font-normal text-white/55">
                {t("map.now")}
              </span>
            </div>

            <div
              className={cn(
                "absolute end-4 bottom-4 w-[min(340px,calc(100%-2rem))] rounded-2xl bg-white p-4 sm:start-[57%] sm:end-auto sm:top-[26%] sm:bottom-auto sm:p-[18px]",
                shadow,
              )}
            >
              <div className="flex items-center gap-3">
                <span
                  className={cn(
                    "size-12 shrink-0 rounded-[10px]",
                    photoGradient,
                  )}
                />
                <div className="min-w-0">
                  <p className="truncate text-[15px] font-medium text-lp-ink">
                    {t("map.selectedTitle")}
                  </p>
                  <p className="truncate font-lp-mono text-[11px] text-lp-mute-2">
                    {t("map.selectedRef")}
                  </p>
                </div>
              </div>
              <div className="mt-3.5 grid grid-cols-4 gap-1">
                {[0, 1, 2, 3].map((step) => (
                  <span
                    key={step}
                    className="h-1 rounded-full bg-lp-teal-vivid"
                  />
                ))}
              </div>
              <div className="mt-3.5 flex items-center justify-between gap-2">
                <StatusBadge tone="fixed">{t("status.fixed")}</StatusBadge>
                <span className="truncate font-lp-mono text-[11px] text-lp-mute-2">
                  {t("map.selectedTimeline")}
                </span>
              </div>
            </div>

            <div
              className={cn(
                "absolute start-6 bottom-6 hidden items-center gap-3.5 rounded-[10px] bg-white px-3 py-2 text-xs text-lp-ink-2 sm:flex",
                shadow,
              )}
            >
              {(["open", "progress", "fixed"] as const).map((tone) => (
                <span key={tone} className="flex items-center gap-1.5">
                  <span
                    className={cn(
                      "size-2 rounded-full",
                      tone === "open"
                        ? "bg-lp-marigold"
                        : tone === "progress"
                          ? "bg-lp-ink"
                          : "bg-lp-teal",
                    )}
                  />
                  {t(
                    tone === "open"
                      ? "status.open"
                      : tone === "progress"
                        ? "status.inProgress"
                        : "status.fixed",
                  )}
                </span>
              ))}
            </div>

            <span className="absolute end-6 bottom-6 hidden rounded-lg bg-white px-2.5 py-1.5 font-lp-mono text-[11px] text-lp-ink-2 lg:block">
              {t("map.updated")}
            </span>

            <span className="absolute end-6 top-1/2 hidden -translate-y-1/2 flex-col overflow-clip rounded-[10px] border border-lp-hair bg-white text-lp-ink-2 sm:flex">
              <span className="grid size-8 place-items-center border-b border-lp-hair text-lg leading-none">
                +
              </span>
              <span className="grid size-8 place-items-center text-lg leading-none">
                −
              </span>
            </span>
          </div>
        </div>
      </Container>
    </section>
  );
}
