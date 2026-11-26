"use client";

import { useQuery } from "@tanstack/react-query";
import {
  ArrowLeft,
  CheckCheck,
  Hammer,
  MapPin,
  MessageSquarePlus,
  Navigation,
  Play,
  ThumbsUp,
  Undo2,
} from "lucide-react";
import { useFormatter, useTranslations } from "next-intl";
import { use, useState } from "react";
import { CategoryIcon } from "@/components/issues/category-icon";
import { PriorityBadge } from "@/components/issues/priority-badge";
import { PinMap } from "@/components/map/lazy-maps";
import { PhotoGallery } from "@/components/media/photo-gallery";
import { PageLoading } from "@/components/page-loading";
import { Alert } from "@/components/ui/alert";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { useToast } from "@/components/ui/toast";
import { useErrorMessage } from "@/hooks/use-error-message";
import { useLocalized } from "@/hooks/use-reference-data";
import { Link } from "@/i18n/navigation";
import {
  acceptWorkOrder,
  getWorkOrder,
  isApiError,
  startWorkOrder,
  type WorkOrder,
} from "@/lib/api";
import { processingRefetchInterval } from "@/lib/media/processing";
import { cn } from "@/lib/utils";
import {
  useWorkOrderAction,
  type WorkOrderConflict,
  workOrderKey,
} from "./use-work-order-action";
import {
  ClosureDialog,
  DeclineDialog,
  ProgressDialog,
} from "./work-order-dialogs";
import { WorkOrderStateBadge } from "./work-order-state-badge";

/** Opens turn-by-turn directions in the phone's maps app. */
export function directionsUrl({ lat, lng }: { lat: number; lng: number }) {
  return `https://www.google.com/maps/dir/?api=1&destination=${lat},${lng}`;
}

type Dialog = "decline" | "progress" | "closure" | null;

function Actions({
  order,
  onOpen,
  onConflict,
}: {
  order: WorkOrder;
  onOpen: (dialog: Exclude<Dialog, null>) => void;
  onConflict: (conflict: WorkOrderConflict) => void;
}) {
  const t = useTranslations("field.detail");
  const errorMessage = useErrorMessage();
  const { toast } = useToast();
  const accept = useWorkOrderAction(
    order.id,
    () => acceptWorkOrder(order.id, order.version),
    {
      onSuccess: () => toast({ variant: "success", title: t("accepted") }),
      onConflict,
    },
  );
  const start = useWorkOrderAction(
    order.id,
    () => startWorkOrder(order.id, order.version),
    {
      onSuccess: () => toast({ variant: "success", title: t("started") }),
      onConflict,
    },
  );
  const failed = [accept, start].find(
    (mutation) =>
      mutation.isError &&
      !isApiError(mutation.error, "version_conflict") &&
      !isApiError(mutation.error, "invalid_work_order_action"),
  );

  let buttons: React.ReactNode = null;
  switch (order.state) {
    case "pending_acceptance":
      buttons = (
        <>
          <Button variant="outline" onClick={() => onOpen("decline")}>
            <Undo2 aria-hidden="true" />
            {t("decline")}
          </Button>
          <Button
            onClick={() => accept.mutate(undefined)}
            loading={accept.isPending}
          >
            <ThumbsUp aria-hidden="true" />
            {t("accept")}
          </Button>
        </>
      );
      break;
    case "accepted":
      buttons = (
        <>
          <Button variant="outline" onClick={() => onOpen("decline")}>
            <Undo2 aria-hidden="true" />
            {t("decline")}
          </Button>
          <Button variant="outline" onClick={() => onOpen("progress")}>
            <MessageSquarePlus aria-hidden="true" />
            {t("addUpdate")}
          </Button>
          <Button
            onClick={() => start.mutate(undefined)}
            loading={start.isPending}
          >
            <Play aria-hidden="true" />
            {t("start")}
          </Button>
        </>
      );
      break;
    case "in_progress":
      buttons = (
        <>
          <Button variant="outline" onClick={() => onOpen("progress")}>
            <MessageSquarePlus aria-hidden="true" />
            {t("addUpdate")}
          </Button>
          <Button onClick={() => onOpen("closure")}>
            <CheckCheck aria-hidden="true" />
            {t("requestClosure")}
          </Button>
        </>
      );
      break;
    default:
      return (
        <Alert variant="info" title={t(`ended.${order.state}.title`)}>
          {t(`ended.${order.state}.body`)}
        </Alert>
      );
  }
  return (
    <div className="grid gap-3">
      {failed ? (
        <Alert variant="destructive" live="assertive">
          {errorMessage(failed.error)}
        </Alert>
      ) : null}
      {/* Sticky so the next step is always a thumb away on a phone. */}
      <div className="sticky bottom-0 z-10 -mx-4 flex flex-col-reverse gap-2 border-t border-border bg-panel/95 px-4 py-3 backdrop-blur sm:static sm:mx-0 sm:flex-row sm:justify-end sm:border-0 sm:bg-transparent sm:p-0">
        {buttons}
      </div>
    </div>
  );
}

function Body({ order }: { order: WorkOrder }) {
  const t = useTranslations("field.detail");
  const tState = useTranslations("workOrderState");
  const format = useFormatter();
  const localized = useLocalized();
  const { toast } = useToast();
  const [dialog, setDialog] = useState<Dialog>(null);
  const [conflict, setConflict] = useState<WorkOrderConflict | null>(null);
  const { issue } = order;
  const before = order.evidence.filter((item) => item.phase === "before");
  const after = order.evidence.filter((item) => item.phase === "after");
  const dialogProps = {
    order,
    onDone: (title: string) => {
      setConflict(null);
      toast({ variant: "success", title });
    },
    onConflict: setConflict,
    onOpenChange: (open: boolean) => {
      if (!open) setDialog(null);
    },
  };

  return (
    <div className="grid gap-5 motion-safe:animate-rise">
      <Link
        href="/field"
        className="inline-flex w-fit items-center gap-1.5 rounded-md text-sm font-semibold text-muted-foreground hover:text-foreground"
      >
        <ArrowLeft aria-hidden="true" className="size-4 rtl:rotate-180" />
        {t("back")}
      </Link>

      <header className="grid gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <WorkOrderStateBadge state={order.state} />
          {issue.priority_band ? (
            <PriorityBadge band={issue.priority_band} />
          ) : null}
        </div>
        <h1 className="flex items-center gap-2 text-2xl font-semibold tracking-tight">
          <CategoryIcon icon={issue.category.icon} className="size-5" />
          {localized(issue.category.name_i18n)}
        </h1>
        <p className="font-mono text-sm text-muted-foreground">
          {issue.reference}
        </p>
      </header>

      {conflict ? (
        <Alert variant="warning" live="assertive" title={t("conflictTitle")}>
          {t("conflictBody", { state: tState(conflict.state) })}
        </Alert>
      ) : null}

      <Actions
        order={order}
        onOpen={(next) => {
          setConflict(null);
          setDialog(next);
        }}
        onConflict={setConflict}
      />

      <Card className="grid gap-3 p-4">
        <h2 className="eyebrow">{t("location")}</h2>
        <div className="h-52 overflow-hidden rounded-lg border border-border">
          <PinMap
            center={issue.location}
            zoom={16}
            pin={issue.location}
            static
            label={t("mapLabel", { reference: issue.reference })}
            pinLabel={issue.reference}
          />
        </div>
        <p className="flex items-start gap-2 text-sm">
          <MapPin aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
          <span>
            {issue.address_text || t("noAddress")}
            {issue.ward ? ` · ${issue.ward.name}` : ""}
          </span>
        </p>
        <a
          href={directionsUrl(issue.location)}
          target="_blank"
          rel="noopener noreferrer"
          className={cn(
            buttonVariants({ variant: "outline" }),
            "w-full sm:w-fit",
          )}
        >
          <Navigation aria-hidden="true" />
          {t("directions")}
          <span className="sr-only"> {t("opensInNewTab")}</span>
        </a>
      </Card>

      <Card className="grid gap-3 p-4">
        <h2 className="eyebrow">{t("whatWasReported")}</h2>
        {issue.descriptions.length > 0 ? (
          <ul className="grid gap-2">
            {issue.descriptions.map((text, index) => (
              <li
                // Descriptions have no id; their order is stable.
                // biome-ignore lint/suspicious/noArrayIndexKey: see above
                key={index}
                className="whitespace-pre-line rounded-lg bg-muted px-3 py-2 text-sm"
              >
                {text}
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-muted-foreground">{t("noDescription")}</p>
        )}
        <PhotoGallery
          media={issue.photos}
          label={t("photosOf", { reference: issue.reference })}
        />
      </Card>

      <Card className="grid gap-4 p-4">
        <h2 className="eyebrow">{t("evidence")}</h2>
        {order.evidence.length === 0 ? (
          <p className="text-sm text-muted-foreground">{t("noEvidence")}</p>
        ) : (
          <>
            {before.length > 0 ? (
              <div className="grid gap-2">
                <h3 className="text-sm font-semibold">{t("before")}</h3>
                <PhotoGallery
                  media={before}
                  label={t("beforeOf", { reference: issue.reference })}
                />
              </div>
            ) : null}
            {after.length > 0 ? (
              <div className="grid gap-2">
                <h3 className="text-sm font-semibold">{t("after")}</h3>
                <PhotoGallery
                  media={after}
                  label={t("afterOf", { reference: issue.reference })}
                />
              </div>
            ) : null}
          </>
        )}
      </Card>

      <Card className="grid gap-3 p-4">
        <h2 className="eyebrow">{t("updates")}</h2>
        {order.updates.length === 0 ? (
          <p className="text-sm text-muted-foreground">{t("noUpdates")}</p>
        ) : (
          <ol className="grid gap-3">
            {[...order.updates].reverse().map((update) => (
              <li
                key={update.at}
                className="grid gap-1 border-s-2 border-border ps-3"
              >
                <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
                  <Hammer aria-hidden="true" className="size-3.5" />
                  <time dateTime={update.at}>
                    {format.dateTime(new Date(update.at), {
                      dateStyle: "medium",
                      timeStyle: "short",
                    })}
                  </time>
                  {update.location ? <span>· {t("withLocation")}</span> : null}
                </p>
                {update.note ? (
                  <p className="whitespace-pre-line text-sm">{update.note}</p>
                ) : (
                  <p className="text-sm text-muted-foreground">
                    {t("photosOnly")}
                  </p>
                )}
              </li>
            ))}
          </ol>
        )}
      </Card>

      <DeclineDialog {...dialogProps} open={dialog === "decline"} />
      <ProgressDialog {...dialogProps} open={dialog === "progress"} />
      <ClosureDialog {...dialogProps} open={dialog === "closure"} />
    </div>
  );
}

/** One work order, with everything a worker needs on site (FR-065). */
export function WorkOrderScreen({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const t = useTranslations("field.detail");
  const errorMessage = useErrorMessage();
  const query = useQuery({
    queryKey: workOrderKey(id),
    queryFn: ({ signal }) => getWorkOrder(id, signal),
    // Evidence photos are processed after upload; poll until they're in.
    refetchInterval: (q) =>
      processingRefetchInterval(
        q.state.data?.evidence ?? [],
        q.state.dataUpdateCount,
      ),
  });

  if (query.isPending) return <PageLoading />;
  if (query.isError) {
    const notFound = isApiError(query.error, "not_found");
    return (
      <div className="grid gap-4">
        <Alert
          variant={notFound ? "warning" : "destructive"}
          live="assertive"
          title={notFound ? t("notFoundTitle") : t("loadError")}
        >
          <p>{notFound ? t("notFoundBody") : errorMessage(query.error)}</p>
        </Alert>
        <div className="flex gap-2">
          <Link
            href="/field"
            className={buttonVariants({ variant: "outline" })}
          >
            {t("back")}
          </Link>
          {notFound ? null : (
            <Button onClick={() => query.refetch()}>{t("retry")}</Button>
          )}
        </div>
      </div>
    );
  }
  return <Body order={query.data} />;
}
