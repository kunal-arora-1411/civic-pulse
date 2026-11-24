"use client";

import { useQuery } from "@tanstack/react-query";
import {
  ArrowLeft,
  ArrowRightLeft,
  Combine,
  MapPin,
  Split,
  Tags,
  UserRound,
} from "lucide-react";
import { useSearchParams } from "next/navigation";
import { useFormatter, useTranslations } from "next-intl";
import { use, useEffect, useState } from "react";
import { useDetailLabels } from "@/components/citizen/report-detail";
import { CategoryIcon } from "@/components/issues/category-icon";
import { StatusBadge } from "@/components/issues/status-badge";
import { PinMap } from "@/components/map/lazy-maps";
import { PhotoGallery } from "@/components/media/photo-gallery";
import { PageLoading } from "@/components/page-loading";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { useErrorMessage } from "@/hooks/use-error-message";
import { useLocalized } from "@/hooks/use-reference-data";
import { Link, useRouter } from "@/i18n/navigation";
import {
  getIssue,
  type IssueDetail,
  isApiError,
  isMergedIssue,
  type MergedIssue,
  type StaffReport,
} from "@/lib/api";
import { hasPermission } from "@/lib/auth/access";
import { useSession } from "@/lib/auth/use-session";
import { processingRefetchInterval } from "@/lib/media/processing";
import { IssueTimeline } from "./issue-timeline";
import { MatchInfo } from "./match-info";
import { PriorityDialog, SeverityDialog } from "./override-dialogs";
import { PriorityCard } from "./priority-card";
import { RelatedIssues } from "./related-issues";
import { StatusDialog } from "./status-dialog";
import { CategoryDialog, MergeDialog, SplitDialog } from "./structure-dialogs";

function ReportItem({
  report,
  issue,
  canGiveFeedback,
}: {
  report: StaffReport;
  issue: IssueDetail;
  canGiveFeedback: boolean;
}) {
  const t = useTranslations("admin.issueDetail");
  const format = useFormatter();
  const detailLabel = useDetailLabels(report.category.id);
  const details = Object.entries(report.details ?? {}).filter(
    ([, value]) => value !== null && value !== "",
  );
  return (
    <li className="grid gap-3 border-b border-border py-4 first:pt-0 last:border-0 last:pb-0">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="font-mono text-sm font-semibold">{report.reference}</p>
        <p className="text-xs text-muted-foreground">
          <time dateTime={report.created_at}>
            {format.dateTime(new Date(report.created_at), {
              dateStyle: "medium",
              timeStyle: "short",
            })}
          </time>
        </p>
      </div>
      <p className="flex items-center gap-1.5 text-sm">
        <UserRound
          aria-hidden="true"
          className="size-4 text-muted-foreground"
        />
        <span className="sr-only">{t("reporter")}: </span>
        {report.reporter?.display_name || t("anonymousReporter")}
      </p>
      {report.description ? (
        <p className="whitespace-pre-line text-sm">{report.description}</p>
      ) : null}
      {details.length > 0 ? (
        <dl className="grid gap-x-6 gap-y-1 text-sm sm:grid-cols-[auto_1fr]">
          {details.map(([key, value]) => {
            const { label, text } = detailLabel(key, value);
            return (
              <div key={key} className="contents">
                <dt className="text-muted-foreground">{label}</dt>
                <dd className="font-medium">{text}</dd>
              </div>
            );
          })}
        </dl>
      ) : null}
      <p className="text-xs text-muted-foreground">
        {t(`locationSource.${report.location.source}`)}
        {report.location.accuracy_m
          ? ` · ±${Math.round(report.location.accuracy_m)} m`
          : ""}
      </p>
      <MatchInfo
        report={report}
        issue={issue}
        canGiveFeedback={canGiveFeedback}
      />
    </li>
  );
}

function Body({
  issue,
  onReload,
}: {
  issue: IssueDetail;
  onReload: () => Promise<unknown>;
}) {
  const t = useTranslations("admin.issueDetail");
  const format = useFormatter();
  const localized = useLocalized();
  const { user } = useSession();
  const can = (permission: string) => hasPermission(user, permission);
  const [changing, setChanging] = useState(false);
  const [dialog, setDialog] = useState<
    "priority" | "severity" | "category" | "merge" | "split" | null
  >(null);
  const closeDialog = (open: boolean) => {
    if (!open) setDialog(null);
  };
  const media = issue.reports.flatMap((report) => report.media);

  return (
    <div className="grid gap-6 motion-safe:animate-rise">
      <header className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div className="grid gap-2">
          <div className="flex flex-wrap items-center gap-2">
            <StatusBadge status={issue.status} />
            <span className="text-sm text-muted-foreground">
              {t("reportCount", { count: issue.report_count })}
            </span>
          </div>
          <h1 className="font-mono text-2xl font-semibold sm:text-3xl">
            {issue.reference}
          </h1>
          <p className="flex items-center gap-2 text-muted-foreground">
            <CategoryIcon icon={issue.category.icon} className="size-4" />
            {localized(issue.category.name_i18n)}
            {issue.ward ? <span aria-hidden="true">·</span> : null}
            {issue.ward?.name}
          </p>
        </div>
        <div className="flex flex-wrap gap-2 sm:justify-end">
          {can("issue:update") ? (
            <Button variant="outline" onClick={() => setDialog("category")}>
              <Tags aria-hidden="true" />
              {t("actions.category")}
            </Button>
          ) : null}
          {can("issue:merge") ? (
            <Button variant="outline" onClick={() => setDialog("merge")}>
              <Combine aria-hidden="true" />
              {t("actions.merge")}
            </Button>
          ) : null}
          {can("issue:merge") && issue.reports.length > 1 ? (
            <Button variant="outline" onClick={() => setDialog("split")}>
              <Split aria-hidden="true" />
              {t("actions.split")}
            </Button>
          ) : null}
          {issue.allowed_transitions.length > 0 ? (
            <Button onClick={() => setChanging(true)}>
              <ArrowRightLeft aria-hidden="true" />
              {t("changeStatus")}
            </Button>
          ) : null}
        </div>
      </header>

      <div className="grid gap-6 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
        <div className="grid content-start gap-6">
          <Card className="grid gap-3 p-5">
            <h2 className="font-semibold">{t("photos")}</h2>
            <PhotoGallery
              media={media}
              label={t("photosOf", { reference: issue.reference })}
              showOriginal
            />
          </Card>

          <Card className="grid gap-3 p-5">
            <h2 className="font-semibold">
              {t("reports", { count: issue.reports.length })}
            </h2>
            <ul className="grid">
              {issue.reports.map((report) => (
                <ReportItem
                  key={report.id}
                  report={report}
                  issue={issue}
                  canGiveFeedback={can("issue:triage")}
                />
              ))}
            </ul>
          </Card>

          <Card className="grid gap-3 p-5">
            <h2 className="font-semibold">{t("history")}</h2>
            <IssueTimeline events={issue.timeline} />
          </Card>
        </div>

        <div className="grid content-start gap-6">
          <PriorityCard
            issue={issue}
            canSetPriority={can("issue:set_priority")}
            canSetSeverity={can("issue:update")}
            onOverridePriority={() => setDialog("priority")}
            onChangeSeverity={() => setDialog("severity")}
          />

          <Card className="grid gap-3 p-5">
            <h2 className="font-semibold">{t("location")}</h2>
            <div className="h-56 overflow-hidden rounded-lg border border-border">
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
              {issue.address_text || t("noAddress")}
            </p>
            <p className="font-mono text-xs text-muted-foreground">
              {issue.location.lat.toFixed(5)}, {issue.location.lng.toFixed(5)}
            </p>
          </Card>

          <RelatedIssues issue={issue} canEdit={can("issue:update")} />

          <Card className="p-5">
            <h2 className="mb-3 font-semibold">{t("facts")}</h2>
            <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-sm">
              <dt className="text-muted-foreground">{t("created")}</dt>
              <dd>
                {format.dateTime(new Date(issue.created_at), {
                  dateStyle: "medium",
                  timeStyle: "short",
                })}
              </dd>
              <dt className="text-muted-foreground">{t("updated")}</dt>
              <dd>
                {format.dateTime(new Date(issue.updated_at), {
                  dateStyle: "medium",
                  timeStyle: "short",
                })}
              </dd>
              <dt className="text-muted-foreground">{t("reporters")}</dt>
              <dd>{issue.unique_reporter_count}</dd>
              <dt className="text-muted-foreground">{t("version")}</dt>
              <dd className="tabular-nums">{issue.version}</dd>
            </dl>
          </Card>
        </div>
      </div>

      <StatusDialog
        issue={issue}
        open={changing}
        onOpenChange={setChanging}
        onReload={onReload}
      />
      <PriorityDialog
        issue={issue}
        open={dialog === "priority"}
        onOpenChange={closeDialog}
        onReload={onReload}
      />
      <SeverityDialog
        issue={issue}
        open={dialog === "severity"}
        onOpenChange={closeDialog}
        onReload={onReload}
      />
      <CategoryDialog
        issue={issue}
        open={dialog === "category"}
        onOpenChange={closeDialog}
        onReload={onReload}
      />
      <MergeDialog
        issue={issue}
        open={dialog === "merge"}
        onOpenChange={closeDialog}
        onReload={onReload}
      />
      <SplitDialog
        issue={issue}
        open={dialog === "split"}
        onOpenChange={closeDialog}
        onReload={onReload}
      />
    </div>
  );
}

export function IssueDetailScreen({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const t = useTranslations("admin.issueDetail");
  const errorMessage = useErrorMessage();
  const mergedFrom = useSearchParams().get("merged_from");
  const query = useQuery({
    queryKey: ["issues", "detail", id],
    queryFn: ({ signal }) => getIssue(id, signal),
    refetchInterval: ({ state }) =>
      state.data && !isMergedIssue(state.data)
        ? processingRefetchInterval(
            state.data.reports.flatMap((report) => report.media),
            state.dataUpdateCount,
          )
        : false,
  });

  return (
    <div className="grid gap-5">
      <Link
        href="/admin/issues"
        className="inline-flex w-fit items-center gap-1.5 rounded-md text-sm font-semibold text-primary hover:underline"
      >
        <ArrowLeft aria-hidden="true" className="size-4 rtl:rotate-180" />
        {t("back")}
      </Link>
      {query.isPending ? (
        <PageLoading />
      ) : query.isError ? (
        isApiError(query.error, "not_found") ? (
          <Alert variant="info" title={t("notFoundTitle")}>
            {t("notFoundBody")}
          </Alert>
        ) : (
          <Alert variant="destructive" live="assertive" title={t("loadError")}>
            <p>{errorMessage(query.error)}</p>
            <Button
              variant="outline"
              size="sm"
              className="mt-3"
              onClick={() => query.refetch()}
            >
              {t("retry")}
            </Button>
          </Alert>
        )
      ) : isMergedIssue(query.data) ? (
        <MergedRedirect issue={query.data} />
      ) : (
        <>
          {mergedFrom ? (
            <Alert variant="info" live="polite">
              {t("mergedHere", { reference: mergedFrom })}
            </Alert>
          ) : null}
          <Body issue={query.data} onReload={() => query.refetch()} />
        </>
      )}
    </div>
  );
}

/**
 * A merged issue keeps its reference, so old links and bookmarks still
 * arrive here; send them on to the issue that survived, replacing this
 * history entry so Back doesn't bounce straight back. The survivor says
 * where the user came from.
 */
function MergedRedirect({ issue }: { issue: MergedIssue }) {
  const t = useTranslations("admin.issueDetail");
  const router = useRouter();
  const target = `/admin/issues/${issue.merged_into.id}?merged_from=${encodeURIComponent(issue.reference)}`;
  useEffect(() => {
    router.replace(target);
  }, [router, target]);
  return (
    <Alert
      variant="info"
      live="polite"
      title={t("mergedTitle", {
        reference: issue.reference,
        target: issue.merged_into.reference,
      })}
    >
      <p>{t("mergedRedirecting")}</p>
      <Link
        href={target}
        className="mt-2 inline-block font-semibold underline underline-offset-4"
      >
        {t("mergedOpen", { reference: issue.merged_into.reference })}
      </Link>
    </Alert>
  );
}
