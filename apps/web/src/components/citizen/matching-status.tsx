"use client";

import {
  CircleCheckBig,
  Clock,
  Hourglass,
  Loader2,
  type LucideIcon,
  UsersRound,
} from "lucide-react";
import { useNow, useTranslations } from "next-intl";
import { Badge } from "@/components/ui/badge";
import type { Report } from "@/lib/api";
import { matchingIsSlow, matchingView } from "@/lib/report/matching";
import { cn } from "@/lib/utils";

/**
 * Where the citizen's report ended up after duplicate matching: still
 * being checked, waiting for a person, added to an issue others had
 * already reported, or a new issue of its own. The text sits in a polite
 * live region, so a screen reader hears the outcome when it arrives.
 */
export function MatchingStatus({
  report,
  className,
}: {
  report: Pick<Report, "matching_status" | "issue" | "created_at">;
  className?: string;
}) {
  const t = useTranslations("reports.matching");
  const now = useNow({ updateInterval: 15_000 });
  const view = matchingView(report);
  const gaveUp = matchingIsSlow(report, now);

  let icon: LucideIcon;
  let title: string;
  let body: string | null;
  let spinning = false;
  let tone: "muted" | "success" = "muted";

  if (gaveUp && (view.state === "pending" || view.state === "review")) {
    icon = Clock;
    title = t("slowTitle");
    body = t("slowBody");
  } else if (view.state === "pending") {
    icon = Loader2;
    spinning = true;
    title = t("pendingTitle");
    body = t("pendingBody");
  } else if (view.state === "review") {
    icon = Hourglass;
    title = t("reviewTitle");
    body = t("reviewBody");
  } else if (view.state === "linked") {
    icon = UsersRound;
    tone = "success";
    title = t("linkedTitle", { reference: view.reference });
    body =
      view.people !== null && view.people > 1
        ? t("linkedBody", { count: view.people })
        : t("linkedBodyNoCount");
  } else if (view.state === "new_issue") {
    icon = CircleCheckBig;
    tone = "success";
    title = t("newTitle", { reference: view.reference });
    body = t("newBody");
  } else {
    icon = CircleCheckBig;
    tone = "success";
    title = t("placedTitle", { reference: view.reference });
    body = null;
  }
  const Icon = icon;

  return (
    <output
      className={cn(
        "flex items-start gap-3 rounded-xl border p-4 text-start text-sm",
        tone === "success"
          ? "border-success-soft-foreground/20 bg-success-soft text-success-soft-foreground"
          : "border-border bg-muted/60",
        className,
      )}
    >
      <Icon
        aria-hidden="true"
        className={cn(
          "mt-0.5 size-5 shrink-0",
          spinning && "motion-safe:animate-spin",
        )}
      />
      <span className="grid gap-0.5">
        <span className="font-semibold">{title}</span>
        {body ? <span className="leading-relaxed">{body}</span> : null}
      </span>
    </output>
  );
}

/** Stands in for the issue status badge until the report has an issue. */
export function MatchingBadge({
  state,
  className,
}: {
  state: "pending" | "review";
  className?: string;
}) {
  const t = useTranslations("reports.matching");
  const Icon = state === "review" ? Hourglass : Clock;
  return (
    <Badge variant="neutral" className={className}>
      <Icon aria-hidden="true" />
      {state === "review" ? t("badgeReview") : t("badgeChecking")}
    </Badge>
  );
}
