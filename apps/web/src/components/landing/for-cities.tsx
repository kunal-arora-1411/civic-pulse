import { Search } from "lucide-react";
import { useTranslations } from "next-intl";
import type { ReactNode } from "react";
import { Link } from "@/i18n/navigation";
import { cn } from "@/lib/utils";
import { CityTabs } from "./city-tabs";
import { CONSOLE_KPIS, CONSOLE_ROWS, CONTACT_URL } from "./data";
import { Container, muted, Pin, Ribbon, StatusBadge } from "./primitives";
import { buttonBase, buttonTone } from "./styles";

export function ForCities() {
  const t = useTranslations("landing.cities");
  const features = [
    [t("features.routingTitle"), t("features.routingBody")],
    [t("features.slaTitle"), t("features.slaBody")],
    [t("features.auditTitle"), t("features.auditBody")],
    [t("features.rolesTitle"), t("features.rolesBody")],
  ];

  return (
    <section
      id="for-cities"
      aria-labelledby="lp-cities-title"
      className="relative scroll-mt-16 overflow-clip bg-lp-ink py-24 text-white sm:py-34"
    >
      <div
        aria-hidden="true"
        className="pointer-events-none absolute start-1/2 top-[38%] h-[500px] w-[900px] max-w-none -translate-x-1/2 rounded-full bg-lp-teal opacity-50 blur-[200px] rtl:translate-x-1/2"
      />
      <Container className="relative grid gap-10 sm:gap-12">
        <div className="lp-reveal flex flex-wrap items-end justify-between gap-6">
          <h2
            id="lp-cities-title"
            className="max-w-[720px] text-[30px] leading-[1.12] font-medium tracking-[-0.035em] sm:text-[40px] sm:leading-[1.1]"
          >
            {t.rich("title", { muted: muted("dark") })}
          </h2>
          {CONTACT_URL ? (
            <a
              href={CONTACT_URL}
              className={cn(
                buttonBase,
                buttonTone.inverse,
                "h-11 px-4 text-[15px]",
              )}
            >
              {t("walkthrough")}
            </a>
          ) : null}
        </div>

        <div className="lp-reveal">
          <CityTabs
            label={t("tabsLabel")}
            tabs={[
              { label: t("tabs.queue"), panel: <QueuePanel /> },
              { label: t("tabs.map"), panel: <MapPanel /> },
              { label: t("tabs.audit"), panel: <AuditPanel /> },
              { label: t("tabs.field"), panel: <FieldPanel /> },
            ]}
          />
        </div>

        <ul className="grid border-t border-white/12 sm:grid-cols-2 lg:grid-cols-4">
          {features.map(([title, body], index) => (
            <li
              key={title}
              className={cn(
                "grid content-start gap-2 border-white/12 py-6 sm:px-6",
                index % 2 === 1 && "sm:border-s",
                index > 0 && "lg:border-s",
                index === 0 && "sm:ps-0",
                index === 2 && "sm:ps-0 lg:ps-6",
              )}
            >
              <h3 className="text-base font-medium">{title}</h3>
              <p className="text-sm leading-[1.55] text-white/65">{body}</p>
            </li>
          ))}
        </ul>
      </Container>
    </section>
  );
}

const panelShell =
  "overflow-clip rounded-[18px] bg-white text-lp-ink shadow-[0_40px_80px_-20px_rgb(0_0_0/0.45)]";

function WindowBar({ children }: { children?: ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-4 border-b border-lp-hair bg-lp-wash px-4 py-3 sm:px-[18px]">
      <span className="flex gap-2" aria-hidden="true">
        <span className="size-2.5 rounded-full bg-[#E5675A]" />
        <span className="size-2.5 rounded-full bg-lp-marigold" />
        <span className="size-2.5 rounded-full bg-[#56B37A]" />
      </span>
      {children}
    </div>
  );
}

function QueuePanel() {
  const t = useTranslations("landing");
  const c = useTranslations("landing.cities");
  const kpis = [
    [c("kpis.open"), CONSOLE_KPIS.open, ""],
    [c("kpis.overdue"), CONSOLE_KPIS.overdue, "text-lp-red"],
    [c("kpis.inProgress"), CONSOLE_KPIS.inProgress, ""],
    [c("kpis.fixedToday"), CONSOLE_KPIS.fixedToday, "text-lp-teal-text"],
  ] as const;
  const statusLabel = {
    overdue: t("status.overdue"),
    progress: t("status.inProgress"),
    open: t("status.open"),
    fixed: t("status.fixed"),
  };

  return (
    <div role="img" aria-label={c("consoleLabel")} className={panelShell}>
      <div aria-hidden="true">
        <WindowBar>
          <span className="hidden w-[420px] max-w-full items-center gap-2 rounded-lg border border-lp-hair bg-white px-3 py-1.5 text-[13px] text-lp-mute-2 md:flex">
            <Search className="size-3.5" strokeWidth={2} />
            {c("search")}
          </span>
          <span className="flex items-center gap-2 text-[13px] font-medium text-lp-ink-2">
            <span className="hidden sm:inline">{c("team")}</span>
            <span className="grid size-6 place-items-center rounded-full bg-lp-teal text-[10px] text-white">
              SK
            </span>
          </span>
        </WindowBar>
        <div className="grid gap-4 p-4 sm:p-6">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            {kpis.map(([label, value, tone]) => (
              <div
                key={label}
                className="grid gap-1 rounded-xl border border-lp-hair px-4 py-3"
              >
                <span className="text-xs text-lp-mute-2">{label}</span>
                <span
                  className={cn(
                    "text-[28px] leading-none font-medium tracking-[-0.03em]",
                    tone,
                  )}
                >
                  {value}
                </span>
              </div>
            ))}
          </div>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[760px] border-collapse text-start">
              <thead>
                <tr className="border-b border-lp-hair font-lp-mono text-[10px] tracking-[0.06em] text-lp-mute-2 uppercase">
                  {(
                    [
                      "ref",
                      "issue",
                      "ward",
                      "department",
                      "status",
                      "sla",
                      "assignee",
                    ] as const
                  ).map((col) => (
                    <th
                      key={col}
                      className="px-2.5 pb-2 text-start font-medium"
                    >
                      {c(`columns.${col}`)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {CONSOLE_ROWS.map((row) => {
                  const sla =
                    row.sla.kind === "closed"
                      ? c("sla.closed")
                      : row.sla.kind === "daysLeft"
                        ? c("sla.daysLeft", { days: row.sla.days })
                        : c(`sla.${row.sla.kind}`, { hours: row.sla.hours });
                  return (
                    <tr
                      key={row.ref}
                      className={cn(
                        "text-sm",
                        row.status === "overdue" && "bg-lp-marigold-soft/60",
                      )}
                    >
                      <td className="rounded-s-[10px] px-2.5 py-2.5 font-lp-mono text-xs text-lp-mute-2">
                        {row.ref}
                      </td>
                      <td className="px-2.5 py-2.5 font-medium">
                        {t(`categories.${row.category}`)}
                      </td>
                      <td className="px-2.5 py-2.5 font-lp-mono text-xs">
                        {row.ward}
                      </td>
                      <td className="px-2.5 py-2.5">
                        {c(`departments.${row.department}`)}
                      </td>
                      <td className="px-2.5 py-2.5">
                        <StatusBadge tone={row.status}>
                          {statusLabel[row.status]}
                        </StatusBadge>
                      </td>
                      <td
                        className={cn(
                          "px-2.5 py-2.5 font-lp-mono text-xs font-medium",
                          row.status === "overdue"
                            ? "text-lp-red"
                            : "text-lp-ink-2",
                        )}
                      >
                        {sla}
                      </td>
                      <td className="rounded-e-[10px] px-2.5 py-2.5">
                        {row.assignee ? (
                          <span className="rounded-full border border-lp-hair bg-lp-wash px-1.5 py-0.5 text-[11px] font-medium text-lp-ink-2">
                            {row.assignee}
                          </span>
                        ) : (
                          <span className="text-[13px] text-lp-mute-2">
                            {c("unassigned")}
                          </span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
}

function MapPanel() {
  const t = useTranslations("landing.cities");
  const pins = [
    ["open", 18, 30],
    ["fixed", 32, 62],
    ["progress", 48, 38],
    ["fixed", 63, 70],
    ["open", 76, 34],
    ["fixed", 88, 60],
  ] as const;
  return (
    <div className={panelShell}>
      <WindowBar />
      <div className="grid gap-5 p-4 sm:p-6 md:grid-cols-[1fr_280px] md:items-center">
        <div
          aria-hidden="true"
          className="relative h-[280px] overflow-clip rounded-xl bg-[#ECE7DA]"
        >
          <svg
            aria-hidden="true"
            viewBox="0 0 600 280"
            preserveAspectRatio="none"
            className="absolute inset-0 size-full"
          >
            <path
              d="M0 90H600M0 200H600M150 0V280M330 0V280M480 0V280"
              stroke="#fff"
              strokeWidth="12"
            />
            <path d="M0 270 600 40" stroke="#FBF8EF" strokeWidth="16" />
          </svg>
          {pins.map(([status, x, y]) => (
            <span
              key={`${x}-${y}`}
              className="absolute -translate-x-1/2 -translate-y-full"
              style={{ left: `${x}%`, top: `${y}%` }}
            >
              <Pin status={status} />
            </span>
          ))}
        </div>
        <p className="text-[15px] leading-[1.6] text-lp-ink-2">
          {t("mapPanel")}
        </p>
      </div>
    </div>
  );
}

function AuditPanel() {
  const t = useTranslations("landing.cities.audit");
  const entries = [
    [t("first"), t("firstWho"), "16:05"],
    [t("second"), t("secondWho"), "11:40"],
    [t("third"), t("thirdWho"), "09:13"],
  ];
  return (
    <div className={panelShell}>
      <WindowBar />
      <ol className="grid gap-1 p-4 sm:p-6">
        {entries.map(([what, who, time]) => (
          <li
            key={time}
            className="flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1 border-b border-lp-hair px-2 py-3.5 last:border-b-0"
          >
            <span className="text-[15px] font-medium">{what}</span>
            <span className="flex gap-4 text-[13px] text-lp-mute-2">
              <span>{who}</span>
              <span className="font-lp-mono">{time}</span>
            </span>
          </li>
        ))}
      </ol>
    </div>
  );
}

function FieldPanel() {
  const t = useTranslations("landing.cities.field");
  const jobs = [t("first"), t("second"), t("third")];
  return (
    <div className={panelShell}>
      <WindowBar />
      <div className="grid gap-3 p-4 sm:p-6">
        <p className="text-[15px] font-medium">{t("title")}</p>
        <ol className="grid gap-2.5">
          {jobs.map((job, index) => (
            <li
              key={job}
              className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-lp-hair px-4 py-3"
            >
              <span className="text-sm">{job}</span>
              <span
                aria-hidden="true"
                className={cn(
                  "rounded-lg px-3 py-1.5 text-[13px] font-medium",
                  index === 0
                    ? "bg-lp-teal text-white"
                    : "bg-lp-wash text-lp-ink-2",
                )}
              >
                {index === 0 ? t("photo") : t("start")}
              </span>
            </li>
          ))}
        </ol>
      </div>
    </div>
  );
}

/** The final call to action: a dark banner with the ribbon. */
export function CtaBanner() {
  const t = useTranslations("landing.cta");
  return (
    <section aria-labelledby="lp-cta-title" className="py-24 sm:py-34">
      <Container>
        <div className="lp-reveal relative overflow-clip rounded-3xl bg-lp-ink px-6 py-14 sm:px-16 sm:py-18">
          <Ribbon
            variant="banner"
            className="pointer-events-none absolute inset-0 size-full opacity-40 sm:opacity-100"
          />
          <div className="relative grid max-w-[600px] gap-8">
            <h2
              id="lp-cta-title"
              className="text-[34px] leading-[1.06] font-medium tracking-[-0.045em] text-white sm:text-[56px] sm:leading-[1.04]"
            >
              {t.rich("title", { muted: muted("dark") })}
            </h2>
            <div className="flex flex-wrap gap-2.5">
              <Link
                href="/report"
                className={cn(
                  buttonBase,
                  buttonTone.inverse,
                  "h-11 px-4 text-[15px]",
                )}
              >
                {t("report")}
              </Link>
              <Link
                href="/track"
                className={cn(
                  buttonBase,
                  buttonTone.ghostDark,
                  "h-11 px-4 text-[15px]",
                )}
              >
                {t("track")}
              </Link>
              {CONTACT_URL ? (
                <a
                  href={CONTACT_URL}
                  className={cn(
                    buttonBase,
                    buttonTone.ghostDark,
                    "h-11 px-4 text-[15px]",
                  )}
                >
                  {t("talk")}
                </a>
              ) : null}
            </div>
          </div>
        </div>
      </Container>
    </section>
  );
}
