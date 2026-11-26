import type { Metadata } from "next";
import type { ReactNode } from "react";
import { Link } from "@/i18n/navigation";

export const metadata: Metadata = {
  title: { absolute: "CivicPulse Blog · From a photo to a fixed street" },
  description:
    "How CivicPulse turns citizen reports into grouped, prioritised and publicly tracked civic issues for Indian municipalities.",
};

function Figure({
  caption,
  children,
}: {
  caption: string;
  children: ReactNode;
}) {
  return (
    <figure className="my-10 overflow-hidden rounded-2xl border border-black/10 bg-white shadow-sm">
      <div className="bg-gradient-to-br from-sky-50 via-white to-emerald-50 p-6">
        {children}
      </div>
      <figcaption className="border-t border-black/5 px-5 py-3 text-sm text-slate-500">
        {caption}
      </figcaption>
    </figure>
  );
}

function HeroArt() {
  return (
    <svg
      viewBox="0 0 800 360"
      role="img"
      aria-label="A city street with a pothole, a streetlight and a garbage bin, each marked by a report pin"
      className="h-auto w-full"
    >
      <defs>
        <linearGradient id="sky" x1="0" x2="0" y1="0" y2="1">
          <stop offset="0" stopColor="#e0f2fe" />
          <stop offset="1" stopColor="#f0fdf4" />
        </linearGradient>
      </defs>
      <rect width="800" height="360" fill="url(#sky)" />
      {[60, 170, 300, 430, 560, 680].map((x, i) => (
        <rect
          key={x}
          x={x}
          y={120 - (i % 3) * 30}
          width="90"
          height={140 + (i % 3) * 30}
          rx="6"
          fill={i % 2 ? "#cbd5e1" : "#94a3b8"}
        />
      ))}
      <rect y="260" width="800" height="100" fill="#334155" />
      {[40, 200, 360, 520, 680].map((x) => (
        <rect
          key={x}
          x={x}
          y="306"
          width="80"
          height="8"
          rx="4"
          fill="#f8fafc"
        />
      ))}
      <ellipse cx="250" cy="290" rx="46" ry="12" fill="#0f172a" />
      <rect x="520" y="150" width="8" height="112" fill="#475569" />
      <circle cx="524" cy="146" r="14" fill="#fde047" opacity="0.4" />
      <rect x="640" y="222" width="44" height="40" rx="4" fill="#16a34a" />
      <rect x="636" y="214" width="52" height="10" rx="3" fill="#15803d" />
      {[
        [250, 240, "#ef4444"],
        [524, 100, "#f59e0b"],
        [662, 170, "#10b981"],
      ].map(([x, y, c]) => (
        <g key={`${x}`} transform={`translate(${x} ${y})`}>
          <path
            d="M0 0c-14 0-24 10-24 23 0 17 24 37 24 37s24-20 24-37C24 10 14 0 0 0z"
            fill={c as string}
          />
          <circle cy="22" r="8" fill="#fff" />
        </g>
      ))}
    </svg>
  );
}

function FlowArt() {
  const steps = [
    ["📷", "Report", "Photo + GPS"],
    ["🧠", "Classify", "AI suggests category"],
    ["🔗", "Group", "Duplicates merged"],
    ["⚡", "Prioritise", "Severity + community"],
    ["🛠️", "Resolve", "Field team fixes"],
    ["✅", "Verify", "Citizens confirm"],
  ];
  return (
    <ol className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
      {steps.map(([icon, title, sub], i) => (
        <li
          key={title}
          className="relative rounded-xl border border-black/10 bg-white p-4 text-center shadow-sm"
        >
          <span className="absolute -top-2 -left-2 grid size-6 place-items-center rounded-full bg-sky-600 text-xs font-semibold text-white">
            {i + 1}
          </span>
          <div aria-hidden="true" className="text-3xl">
            {icon}
          </div>
          <div className="mt-2 font-semibold text-slate-900">{title}</div>
          <div className="text-xs text-slate-500">{sub}</div>
        </li>
      ))}
    </ol>
  );
}

function ClusterArt() {
  const dots = [
    [120, 90],
    [140, 110],
    [110, 120],
    [135, 80],
    [150, 95],
    [330, 150],
    [345, 165],
    [320, 170],
    [520, 70],
  ];
  return (
    <svg
      viewBox="0 0 640 220"
      role="img"
      aria-label="Many individual report dots on a map grouped into three issue circles"
      className="h-auto w-full"
    >
      <rect width="640" height="220" rx="12" fill="#f1f5f9" />
      <path
        d="M0 140 C160 120 260 200 640 150"
        stroke="#cbd5e1"
        strokeWidth="18"
        fill="none"
      />
      <path
        d="M220 0 C240 80 200 160 260 220"
        stroke="#cbd5e1"
        strokeWidth="14"
        fill="none"
      />
      {[
        [133, 100, 42, "5 reports → 1 issue"],
        [332, 162, 30, "3 reports → 1 issue"],
        [520, 70, 20, "1 report"],
      ].map(([x, y, r, label]) => (
        <g key={label as string}>
          <circle
            cx={x as number}
            cy={y as number}
            r={r as number}
            fill="#0ea5e9"
            opacity="0.15"
            stroke="#0284c7"
            strokeDasharray="4 4"
          />
          <text
            x={x as number}
            y={(y as number) + (r as number) + 16}
            textAnchor="middle"
            fontSize="13"
            fill="#0f172a"
          >
            {label}
          </text>
        </g>
      ))}
      {dots.map(([x, y]) => (
        <circle key={`${x}-${y}`} cx={x} cy={y} r="5" fill="#ef4444" />
      ))}
    </svg>
  );
}

function ChartArt() {
  const bars = [42, 55, 48, 70, 64, 82, 90];
  return (
    <svg
      viewBox="0 0 640 220"
      role="img"
      aria-label="Bar chart showing resolved issues rising week over week"
      className="h-auto w-full"
    >
      {bars.map((v, i) => (
        <g key={`w${i + 1}`}>
          <rect
            x={40 + i * 84}
            y={190 - v * 1.8}
            width="52"
            height={v * 1.8}
            rx="6"
            fill={i === bars.length - 1 ? "#10b981" : "#38bdf8"}
          />
          <text
            x={66 + i * 84}
            y="210"
            textAnchor="middle"
            fontSize="12"
            fill="#64748b"
          >
            W{i + 1}
          </text>
        </g>
      ))}
    </svg>
  );
}

const STATS = [
  ["1 photo", "is all a citizen needs to report"],
  ["~2 s", "to suggest a category on CPU"],
  ["0", "duplicate issues for the same pothole"],
  ["100%", "public timeline for every issue"],
];

export default function BlogPage() {
  return (
    <main id="main" className="flex-1 bg-white">
      <article className="mx-auto max-w-3xl px-5 py-14 sm:py-20">
        <p className="text-sm font-semibold tracking-wide text-sky-700 uppercase">
          Product story · CivicPulse
        </p>
        <h1 className="mt-3 text-4xl font-bold tracking-tight text-slate-900 sm:text-5xl">
          From a photo to a fixed street: how CivicPulse makes civic complaints
          count
        </h1>
        <p className="mt-5 text-lg leading-relaxed text-slate-600">
          Potholes, overflowing garbage and dark streetlights are reported every
          day, yet residents rarely learn what happened next. CivicPulse is a
          geotagged civic issue platform for Indian municipalities that groups
          duplicate complaints, prioritises them with AI and community
          verification, and tracks every fix in public.
        </p>

        <Figure caption="Every report is a geotagged pin: potholes, broken streetlights, garbage dumps.">
          <HeroArt />
        </Figure>

        <section className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          {STATS.map(([big, small]) => (
            <div key={big} className="rounded-xl bg-slate-50 p-4 text-center">
              <div className="text-2xl font-bold text-sky-700">{big}</div>
              <div className="mt-1 text-xs text-slate-500">{small}</div>
            </div>
          ))}
        </section>

        <h2 className="mt-14 text-2xl font-bold text-slate-900">The problem</h2>
        <p className="mt-4 leading-relaxed text-slate-700">
          Urban residents report the same problem dozens of times through phone
          calls, WhatsApp groups and portals, while ward officers drown in
          duplicates with no way to tell which issue is the most urgent.
          Citizens get no feedback, so trust erodes and people stop reporting.
        </p>

        <h2 className="mt-12 text-2xl font-bold text-slate-900">
          How it works
        </h2>
        <Figure caption="The CivicPulse loop: from a citizen's photo to a verified closure.">
          <FlowArt />
        </Figure>
        <ul className="mt-2 list-disc space-y-3 pl-6 text-slate-700">
          <li>
            <strong>Report in seconds.</strong> Snap a photo, confirm the GPS
            pin and pick (or accept) the suggested category, in English or
            Hindi.
          </li>
          <li>
            <strong>AI that assists, never decides alone.</strong> A CLIP model
            running on ONNX suggests the category, and faces are blurred before
            any photo is published.
          </li>
          <li>
            <strong>Duplicates become one issue.</strong> Location, category,
            visual similarity and perceptual hashes group repeat reports.
            Ambiguous cases go to a human review queue.
          </li>
          <li>
            <strong>Priority you can explain.</strong> Severity rules, report
            counts and community support produce a priority score with every
            factor shown to staff.
          </li>
        </ul>

        <h2 className="mt-12 text-2xl font-bold text-slate-900">
          Grouping duplicate complaints
        </h2>
        <Figure caption="Nine reports on the map become three issues, so crews visit each spot once.">
          <ClusterArt />
        </Figure>
        <p className="leading-relaxed text-slate-700">
          When ten people report the same pothole, the ward sees one issue with
          ten reporters, which is a stronger signal and one work order. Every
          reporter follows the same issue and receives the same updates.
        </p>

        <h2 className="mt-12 text-2xl font-bold text-slate-900">
          Community verification and public tracking
        </h2>
        <p className="mt-4 leading-relaxed text-slate-700">
          Field workers close work with an after photo. The issue is resolved
          only when a supervisor approves or at least two citizens confirm the
          fix, and a single “still broken” sends it back. Every issue has a
          public timeline with locations generalised for privacy, and residents
          are notified at each step.
        </p>
        <Figure caption="Analytics show staff and residents how resolution improves week by week.">
          <ChartArt />
        </Figure>

        <h2 className="mt-12 text-2xl font-bold text-slate-900">
          Built for municipalities
        </h2>
        <ul className="mt-4 grid gap-3 sm:grid-cols-2">
          {[
            "Multi-tenant with row-level security per city",
            "Roles for citizens, operators, supervisors and field workers",
            "Audit trail for every sensitive action",
            "Works on low-end phones, in English and Hindi",
            "Notifications for reporters, operators and assignees",
            "Analytics on response times, hotspots and AI quality",
          ].map((item) => (
            <li
              key={item}
              className="flex gap-2 rounded-lg border border-black/10 p-3 text-sm text-slate-700"
            >
              <span aria-hidden="true" className="text-emerald-600">
                ✔
              </span>
              {item}
            </li>
          ))}
        </ul>

        <div className="mt-14 rounded-2xl bg-gradient-to-r from-sky-600 to-emerald-600 p-8 text-white">
          <h2 className="text-2xl font-bold">See a problem? Report it.</h2>
          <p className="mt-2 text-white/90">
            It takes under a minute, and you can follow it until it's fixed.
          </p>
          <div className="mt-5 flex flex-wrap gap-3">
            <Link
              href="/report"
              className="rounded-lg bg-white px-5 py-2.5 font-semibold text-sky-700"
            >
              Report an issue
            </Link>
            <Link
              href="/"
              className="rounded-lg border border-white/60 px-5 py-2.5 font-semibold"
            >
              Back to home
            </Link>
          </div>
        </div>
      </article>
    </main>
  );
}
