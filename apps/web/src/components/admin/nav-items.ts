import {
  BadgeCheck,
  ChartLine,
  Cpu,
  Gauge,
  GitCompareArrows,
  Inbox,
  LayoutDashboard,
  type LucideIcon,
  Map as MapIcon,
  Megaphone,
  ScrollText,
  SlidersHorizontal,
  Tags,
  Timer,
  Users,
  UsersRound,
  Workflow,
} from "lucide-react";
import type { CurrentUser } from "@/lib/api";
import { hasPermission } from "@/lib/auth/access";

export type AdminNavKey =
  | "overview"
  | "issues"
  | "review"
  | "map"
  | "workload"
  | "teams"
  | "closure"
  | "analytics"
  | "announcements"
  | "categories"
  | "matching"
  | "priority"
  | "sla"
  | "ai"
  | "users"
  | "audit";

/** Sidebar sections, also used as the page eyebrow. */
export type AdminNavGroup = "operations" | "configuration" | "governance";

export type AdminNavItem = {
  key: AdminNavKey;
  group: AdminNavGroup;
  href:
    | "/admin"
    | "/admin/issues"
    | "/admin/review"
    | "/admin/map"
    | "/admin/workload"
    | "/admin/teams"
    | "/admin/settings/closure"
    | "/admin/analytics"
    | "/admin/announcements"
    | "/admin/categories"
    | "/admin/settings/matching"
    | "/admin/settings/priority"
    | "/admin/settings/sla"
    | "/admin/ai"
    | "/admin/users"
    | "/admin/audit";
  icon: LucideIcon;
  /** Hidden unless the user has this permission. No value: any staff. */
  permission?: string;
  /** Shows a count next to the label, e.g. open review tasks. */
  badge?: "openReviews";
};

export const ADMIN_NAV: readonly AdminNavItem[] = [
  {
    key: "overview",
    group: "operations",
    href: "/admin",
    icon: LayoutDashboard,
  },
  {
    key: "issues",
    group: "operations",
    href: "/admin/issues",
    icon: Inbox,
    permission: "issue:read",
  },
  {
    key: "review",
    group: "operations",
    href: "/admin/review",
    icon: GitCompareArrows,
    permission: "issue:triage",
    badge: "openReviews",
  },
  {
    key: "map",
    group: "operations",
    href: "/admin/map",
    icon: MapIcon,
    permission: "issue:read",
  },
  {
    key: "workload",
    group: "operations",
    href: "/admin/workload",
    icon: Workflow,
    permission: "issue:assign",
  },
  {
    key: "analytics",
    group: "operations",
    href: "/admin/analytics",
    icon: ChartLine,
    permission: "analytics:read",
  },
  {
    key: "announcements",
    group: "operations",
    href: "/admin/announcements",
    icon: Megaphone,
    permission: "config:read",
  },
  {
    key: "categories",
    group: "configuration",
    href: "/admin/categories",
    icon: Tags,
    permission: "config:read",
  },
  {
    key: "matching",
    group: "configuration",
    href: "/admin/settings/matching",
    icon: SlidersHorizontal,
    permission: "config:read",
  },
  {
    key: "priority",
    group: "configuration",
    href: "/admin/settings/priority",
    icon: Gauge,
    permission: "config:read",
  },
  {
    key: "sla",
    group: "configuration",
    href: "/admin/settings/sla",
    icon: Timer,
    permission: "config:read",
  },
  {
    key: "closure",
    group: "configuration",
    href: "/admin/settings/closure",
    icon: BadgeCheck,
    permission: "config:read",
  },
  {
    key: "teams",
    group: "configuration",
    href: "/admin/teams",
    icon: Users,
    permission: "config:read",
  },
  {
    key: "ai",
    group: "configuration",
    href: "/admin/ai",
    icon: Cpu,
    permission: "config:read",
  },
  {
    key: "users",
    group: "governance",
    href: "/admin/users",
    icon: UsersRound,
    permission: "user:manage",
  },
  {
    key: "audit",
    group: "governance",
    href: "/admin/audit",
    icon: ScrollText,
    permission: "audit:read",
  },
];

/**
 * The entries this user should see. A convenience only: the pages check
 * the same permission, and the API enforces it regardless.
 */
export function visibleNavItems(
  user: CurrentUser,
  items: readonly AdminNavItem[] = ADMIN_NAV,
): AdminNavItem[] {
  return items.filter(
    (item) => !item.permission || hasPermission(user, item.permission),
  );
}

export function isActive(item: AdminNavItem, pathname: string): boolean {
  if (item.href === "/admin") return pathname === "/admin";
  return pathname === item.href || pathname.startsWith(`${item.href}/`);
}

export function navGroupOf(key: AdminNavKey): AdminNavGroup {
  return ADMIN_NAV.find((item) => item.key === key)?.group ?? "operations";
}
