"use client";

import { useQuery } from "@tanstack/react-query";
import { ChevronRight, ClipboardList, MapPin } from "lucide-react";
import { useFormatter, useTranslations } from "next-intl";
import { useState } from "react";
import { CategoryIcon } from "@/components/issues/category-icon";
import { PriorityBadge } from "@/components/issues/priority-badge";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useErrorMessage } from "@/hooks/use-error-message";
import { useLocalized } from "@/hooks/use-reference-data";
import { Link } from "@/i18n/navigation";
import { listWorkOrders, type WorkOrder, type WorkOrderState } from "@/lib/api";
import { cn } from "@/lib/utils";
import { WorkOrderStateBadge } from "./work-order-state-badge";

/** Tabs over the queue. "Active" is the API's default set. */
const TABS = {
  active: undefined,
  done: ["done"],
} satisfies Record<string, readonly WorkOrderState[] | undefined>;
type Tab = keyof typeof TABS;

/** New jobs first, then the ones in hand, then those waiting on approval. */
const ORDER: Record<WorkOrderState, number> = {
  pending_acceptance: 0,
  in_progress: 1,
  accepted: 2,
  completion_requested: 3,
  done: 4,
  declined: 5,
  cancelled: 6,
};

/** Every query under this prefix is the caller's own field data. */
export const FIELD_KEY = ["field", "work-orders"] as const;

function WorkOrderCard({ order }: { order: WorkOrder }) {
  const t = useTranslations("field.list");
  const format = useFormatter();
  const localized = useLocalized();
  const { issue } = order;
  return (
    <li>
      <Link
        href={`/field/work-orders/${order.id}`}
        className="group block rounded-2xl focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-ring/30"
      >
        <Card className="grid gap-2 p-4 transition-colors group-hover:bg-muted/60">
          <div className="flex flex-wrap items-center gap-2">
            <WorkOrderStateBadge state={order.state} />
            {issue.priority_band ? (
              <PriorityBadge band={issue.priority_band} />
            ) : null}
            <span className="ms-auto font-mono text-xs text-muted-foreground">
              {issue.reference}
            </span>
          </div>
          <p className="flex items-center gap-2 font-semibold">
            <CategoryIcon icon={issue.category.icon} className="size-4" />
            {localized(issue.category.name_i18n)}
          </p>
          <p className="flex items-start gap-2 text-sm text-muted-foreground">
            <MapPin aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
            <span>
              {issue.address_text || t("noAddress")}
              {issue.ward ? ` · ${issue.ward.name}` : ""}
            </span>
          </p>
          <div className="flex items-center justify-between text-xs text-muted-foreground">
            <span>
              {t("assignedAt", {
                when: format.relativeTime(new Date(order.created_at)),
              })}
            </span>
            <ChevronRight
              aria-hidden="true"
              className="size-4 rtl:rotate-180"
            />
          </div>
        </Card>
      </Link>
    </li>
  );
}

/**
 * The field worker's queue (FR-064). Only their own work orders: the API
 * scopes the list to the caller and never sends reporter data.
 */
export function WorkOrderList() {
  const t = useTranslations("field");
  const errorMessage = useErrorMessage();
  const [tab, setTab] = useState<Tab>("active");
  const query = useQuery({
    queryKey: [...FIELD_KEY, "list", tab],
    queryFn: ({ signal }) =>
      listWorkOrders({ state: TABS[tab], limit: 100 }, signal),
  });
  const items = [...(query.data?.items ?? [])].sort(
    (a, b) =>
      ORDER[a.state] - ORDER[b.state] ||
      b.created_at.localeCompare(a.created_at),
  );

  return (
    <div className="grid gap-4">
      <div
        role="tablist"
        aria-label={t("list.tabsLabel")}
        className="inline-flex w-fit gap-1 rounded-xl bg-card p-1 shadow-card"
      >
        {(Object.keys(TABS) as Tab[]).map((key) => (
          <button
            key={key}
            type="button"
            role="tab"
            aria-selected={tab === key}
            onClick={() => setTab(key)}
            className={cn(
              "rounded-lg px-3 py-1.5 text-sm font-semibold focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-ring/30",
              tab === key
                ? "bg-primary text-primary-foreground"
                : "text-muted-foreground hover:bg-muted",
            )}
          >
            {t(`list.tabs.${key}`)}
          </button>
        ))}
      </div>

      {query.isPending ? (
        <div className="grid gap-3" aria-busy="true">
          <span className="sr-only">{t("list.loading")}</span>
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-32 rounded-2xl" />
          ))}
        </div>
      ) : query.isError ? (
        <Alert variant="destructive" live="assertive" title={t("list.error")}>
          <p>{errorMessage(query.error)}</p>
          <Button
            variant="outline"
            size="sm"
            className="mt-2"
            onClick={() => query.refetch()}
          >
            {t("list.retry")}
          </Button>
        </Alert>
      ) : items.length === 0 ? (
        <Card className="relative grid justify-items-center gap-3 overflow-hidden px-6 py-14 text-center">
          <div
            aria-hidden="true"
            className="bg-survey-grid absolute inset-0 [mask-image:radial-gradient(ellipse_at_center,black,transparent_70%)]"
          />
          <span className="bg-brand-gradient relative grid size-16 place-items-center rounded-2xl text-white shadow-raised">
            <ClipboardList aria-hidden="true" className="size-7" />
          </span>
          <h2 className="relative text-xl font-semibold tracking-tight">
            {tab === "done" ? t("list.noneDone") : t("emptyTitle")}
          </h2>
          {tab === "active" ? (
            <p className="relative max-w-sm text-muted-foreground">
              {t("emptyBody")}
            </p>
          ) : null}
        </Card>
      ) : (
        <ul className="grid gap-3" aria-label={t(`list.tabs.${tab}`)}>
          {items.map((order) => (
            <WorkOrderCard key={order.id} order={order} />
          ))}
        </ul>
      )}
    </div>
  );
}
