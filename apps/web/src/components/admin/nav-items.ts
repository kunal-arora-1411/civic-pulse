import {
  ChartLine,
  Cpu,
  Gauge,
  GitCompareArrows,
  Inbox,
  LayoutDashboard,
  type LucideIcon,
  Map as MapIcon,
  ScrollText,
  SlidersHorizontal,
  Tags,
  UsersRound,
} from "lucide-react";
import type { CurrentUser } from "@/lib/api";
import { hasPermission } from "@/lib/auth/access";

export type AdminNavKey =
  | "overview"
  | "issues"
  | "review"
  | "map"
  | "analytics"
  | "categories"
  | "matching"
  | "priority"
  | "ai"
  | "users"
  | "audit";

export type AdminNavItem = {
  key: AdminNavKey;
  href:
    | "/admin"
    | "/admin/issues"
    | "/admin/review"
    | "/admin/map"
    | "/admin/analytics"
    | "/admin/categories"
    | "/admin/settings/matching"
    | "/admin/settings/priority"
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
  { key: "overview", href: "/admin", icon: LayoutDashboard },
  {
    key: "issues",
    href: "/admin/issues",
    icon: Inbox,
    permission: "issue:read",
  },
  {
    key: "review",
    href: "/admin/review",
    icon: GitCompareArrows,
    permission: "issue:triage",
    badge: "openReviews",
  },
  { key: "map", href: "/admin/map", icon: MapIcon, permission: "issue:read" },
  {
    key: "analytics",
    href: "/admin/analytics",
    icon: ChartLine,
    permission: "analytics:read",
  },
  {
    key: "categories",
    href: "/admin/categories",
    icon: Tags,
    permission: "config:read",
  },
  {
    key: "matching",
    href: "/admin/settings/matching",
    icon: SlidersHorizontal,
    permission: "config:read",
  },
  {
    key: "priority",
    href: "/admin/settings/priority",
    icon: Gauge,
    permission: "config:read",
  },
  { key: "ai", href: "/admin/ai", icon: Cpu, permission: "config:read" },
  {
    key: "users",
    href: "/admin/users",
    icon: UsersRound,
    permission: "user:manage",
  },
  {
    key: "audit",
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
