"use client";

import {
  ChevronDown,
  ClipboardList,
  LayoutDashboard,
  LogOut,
  UserRound,
} from "lucide-react";
import { useTranslations } from "next-intl";
import { useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { buttonVariants } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Link, useRouter } from "@/i18n/navigation";
import { logout } from "@/lib/api";
import { canUseAdmin, canUseField } from "@/lib/auth/access";
import { useSession } from "@/lib/auth/use-session";
import { formatIndianPhone } from "@/lib/phone";
import { cn } from "@/lib/utils";

function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  return parts
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase())
    .join("");
}

/**
 * Sign-in link or account disclosure for headers. A disclosure (button +
 * list of links) rather than an ARIA menu: it's just navigation, so plain
 * Tab order is what users expect.
 */
export function AccountMenu({ align = "end" }: { align?: "start" | "end" }) {
  const t = useTranslations("account");
  const { status, user } = useSession();
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [signingOut, setSigningOut] = useState(false);
  const panelId = useId();
  const rootRef = useRef<HTMLDivElement>(null);

  // Close when the route is hidden by <Activity>, so it isn't still open
  // when the user comes back.
  useLayoutEffect(() => () => setOpen(false), []);

  useEffect(() => {
    if (!open) return;
    const onPointer = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpen(false);
        rootRef.current?.querySelector("button")?.focus();
      }
    };
    document.addEventListener("pointerdown", onPointer);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onPointer);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  if (status === "unknown") {
    return <Skeleton className="h-9 w-24 rounded-lg" />;
  }

  if (status === "anonymous" || !user) {
    return (
      <Link href="/login" className={buttonVariants({ size: "sm" })}>
        {t("signIn")}
      </Link>
    );
  }

  const name = user.display_name || formatIndianPhone(user.phone);
  const itemClass =
    "flex w-full items-center gap-2.5 rounded-md px-3 py-2 text-start text-sm hover:bg-muted [&_svg]:size-4 [&_svg]:text-muted-foreground";

  return (
    <div ref={rootRef} className="relative">
      <button
        type="button"
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen((value) => !value)}
        className="flex h-9 items-center gap-2 rounded-lg ps-1 pe-2 text-sm font-medium hover:bg-muted"
      >
        <span
          aria-hidden="true"
          className="grid size-7 place-items-center rounded-full bg-primary text-xs font-semibold text-primary-foreground"
        >
          {initials(user.display_name || "?")}
        </span>
        <span className="max-w-32 truncate">{name}</span>
        <span className="sr-only">{t("menuLabel")}</span>
        <ChevronDown
          aria-hidden="true"
          className="size-4 text-muted-foreground"
        />
      </button>
      <div
        id={panelId}
        hidden={!open}
        className={cn(
          "absolute top-full z-40 mt-2 w-60 rounded-xl border border-border bg-card p-1.5 shadow-raised motion-safe:animate-fade",
          align === "end" ? "end-0" : "start-0",
        )}
      >
        <div className="border-b border-border px-3 pt-1.5 pb-2.5">
          <p className="truncate text-sm font-semibold">{name}</p>
          <p className="font-mono text-xs text-muted-foreground">
            {formatIndianPhone(user.phone)}
          </p>
        </div>
        <ul className="grid gap-0.5 pt-1.5">
          {canUseAdmin(user) ? (
            <li>
              <Link
                href="/admin"
                className={itemClass}
                onClick={() => setOpen(false)}
              >
                <LayoutDashboard aria-hidden="true" />
                {t("adminConsole")}
              </Link>
            </li>
          ) : null}
          {canUseField(user) ? (
            <li>
              <Link
                href="/field"
                className={itemClass}
                onClick={() => setOpen(false)}
              >
                <ClipboardList aria-hidden="true" />
                {t("fieldApp")}
              </Link>
            </li>
          ) : null}
          <li>
            <Link
              href="/profile"
              className={itemClass}
              onClick={() => setOpen(false)}
            >
              <UserRound aria-hidden="true" />
              {t("profile")}
            </Link>
          </li>
          <li>
            <button
              type="button"
              disabled={signingOut}
              className={cn(itemClass, "disabled:opacity-60")}
              onClick={async () => {
                setSigningOut(true);
                await logout();
                setSigningOut(false);
                setOpen(false);
                router.replace("/");
              }}
            >
              <LogOut aria-hidden="true" />
              {signingOut ? t("signingOut") : t("signOut")}
            </button>
          </li>
        </ul>
      </div>
    </div>
  );
}
