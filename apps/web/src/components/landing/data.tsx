import {
  Droplet,
  Lightbulb,
  type LucideIcon,
  Trash2,
  TreePine,
  Waves,
} from "lucide-react";
import type { PinStatus } from "./primitives";

/*
 * Everything on the landing page that looks like data is synthetic. The
 * stats are illustrative pilot figures (the page says so) until there is
 * a public statistics endpoint to read them from.
 */

/**
 * Where "Book a walkthrough" and "Talk to our team" go. There is no sales
 * contact yet, so those buttons stay hidden until this is configured.
 */
export const CONTACT_URL = process.env.NEXT_PUBLIC_CONTACT_URL || null;

export const STATS = {
  resolved: 9312,
  medianDays: 3.2,
  wards: 42,
  hindiShare: 38,
} as const;

/** A pothole has no lucide icon, so it gets its own. */
export function PotholeIcon(props: React.SVGProps<SVGSVGElement>) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      {...props}
    >
      <ellipse cx="12" cy="14" rx="9" ry="4" />
      <path d="M7 13.5c1.5-1 3-1.3 5-1.3s3.5.3 5 1.3" />
    </svg>
  );
}

export const CATEGORIES: {
  key: "pothole" | "streetlight" | "garbage" | "drain" | "water" | "tree";
  icon: LucideIcon | typeof PotholeIcon;
}[] = [
  { key: "pothole", icon: PotholeIcon },
  { key: "streetlight", icon: Lightbulb },
  { key: "garbage", icon: Trash2 },
  { key: "drain", icon: Waves },
  { key: "water", icon: Droplet },
  { key: "tree", icon: TreePine },
];

/** Pins on the illustrative map, as percentages of the panel. */
export const MAP_PINS: { status: PinStatus; x: number; y: number }[] = [
  { status: "open", x: 21, y: 33 },
  { status: "fixed", x: 35, y: 19 },
  { status: "progress", x: 43, y: 73 },
  { status: "open", x: 75, y: 28 },
  { status: "fixed", x: 10, y: 66 },
  { status: "open", x: 65, y: 81 },
  { status: "fixed", x: 86, y: 56 },
  { status: "progress", x: 27, y: 88 },
  { status: "fixed", x: 58, y: 14 },
  { status: "open", x: 93, y: 81 },
];

/** The one pin that changes from open to fixed on a loop. */
export const MORPH_PIN = { x: 51, y: 52 };

type Department = "sanitation" | "electrical" | "parks" | "roads";
type Sla =
  | { kind: "over"; hours: number }
  | { kind: "hoursLeft"; hours: number }
  | { kind: "daysLeft"; days: number }
  | { kind: "closed" };

export const CONSOLE_ROWS: {
  ref: string;
  category: "drain" | "streetlight" | "garbage" | "tree" | "pothole";
  ward: number;
  department: Department;
  status: "overdue" | "progress" | "open" | "fixed";
  sla: Sla;
  assignee: string | null;
}[] = [
  {
    ref: "CP-2622",
    category: "drain",
    ward: 42,
    department: "sanitation",
    status: "overdue",
    sla: { kind: "over", hours: 2 },
    assignee: "RM",
  },
  {
    ref: "CP-2625",
    category: "streetlight",
    ward: 42,
    department: "electrical",
    status: "progress",
    sla: { kind: "hoursLeft", hours: 4 },
    assignee: "AP",
  },
  {
    ref: "CP-2620",
    category: "garbage",
    ward: 41,
    department: "sanitation",
    status: "open",
    sla: { kind: "daysLeft", days: 1 },
    assignee: null,
  },
  {
    ref: "CP-2618",
    category: "tree",
    ward: 42,
    department: "parks",
    status: "progress",
    sla: { kind: "hoursLeft", hours: 6 },
    assignee: "JS",
  },
  {
    ref: "CP-2611",
    category: "pothole",
    ward: 42,
    department: "roads",
    status: "fixed",
    sla: { kind: "closed" },
    assignee: "SK",
  },
];

export const CONSOLE_KPIS = {
  open: 23,
  overdue: 4,
  inProgress: 17,
  fixedToday: 11,
} as const;
