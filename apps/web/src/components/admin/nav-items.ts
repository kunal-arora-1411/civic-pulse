import {
  LayoutDashboard,
  type LucideIcon,
  ScrollText,
  UsersRound,
} from "lucide-react";
import type { CurrentUser } from "@/lib/api";
import { hasPermission } from "@/lib/auth/access";

export type AdminNavKey = "overview" | "users" | "audit";

export type AdminNavItem = {
  key: AdminNavKey;
  href: "/admin" | "/admin/users" | "/admin/audit";
  icon: LucideIcon;
  /** Hidden unless the user has this permission. No value: any staff. */
  permission?: string;
};

export const ADMIN_NAV: readonly AdminNavItem[] = [
  { key: "overview", href: "/admin", icon: LayoutDashboard },
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
