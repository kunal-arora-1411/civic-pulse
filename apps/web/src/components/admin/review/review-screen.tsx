"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  CirclePlus,
  ExternalLink,
  Inbox,
  Keyboard,
  Link2,
  MapPin,
  UserRound,
} from "lucide-react";
import { useSearchParams } from "next/navigation";
import { useFormatter, useNow, useTranslations } from "next-intl";
import { type ReactNode, useCallback, useEffect, useId, useState } from "react";
import { PageHeader } from "@/components/admin/page-header";
import { CategoryIcon } from "@/components/issues/category-icon";
import { PriorityBadge } from "@/components/issues/priority-badge";
import { StatusBadge } from "@/components/issues/status-badge";
import { ComparisonMap } from "@/components/map/lazy-maps";
import { PhotoGallery } from "@/components/media/photo-gallery";
import { RemoteImage } from "@/components/media/remote-image";
import { PageLoading } from "@/components/page-loading";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { useToast } from "@/components/ui/toast";
import { useErrorMessage } from "@/hooks/use-error-message";
import { useLocalized } from "@/hooks/use-reference-data";
import { useShortcuts } from "@/hooks/use-shortcuts";
import { Link } from "@/i18n/navigation";
import {
  isApiError,
  listReviewTasks,
  type ReviewAction,
  type ReviewCandidate,
  type ReviewTask,
  resolveReviewTask,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import { SignalBreakdown } from "./signal-breakdown";
import { REVIEW_COUNT_KEY } from "./use-open-review-count";

const LIST_KEY = ["review-tasks", "list"] as const;

function Kbd({ children }: { children: ReactNode }) {
  return (
    // The key is announced through aria-keyshortcuts on the control.
    <span aria-hidden="true" className="max-sm:hidden">
      <kbd className="ms-1 inline-grid min-w-5 place-items-center rounded border border-current/30 px-1 font-mono text-[0.6875rem] leading-4 font-semibold opacity-80">
        {children}
      </kbd>
    </span>
  );
}

function useAgo() {
  const format = useFormatter();
  const now = useNow({ updateInterval: 60_000 });
  return (at: string) => format.relativeTime(new Date(at), now);
}

function TaskList({
  tasks,
  selectedId,
  onSelect,
}: {
  tasks: ReviewTask[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  const t = useTranslations("admin.review");
  const localized = useLocalized();
  const ago = useAgo();
  const format = useFormatter();
  return (
    <ul className="divide-y divide-border">
      {tasks.map((task) => {
        const selected = task.id === selectedId;
        const best = task.candidates[0];
        return (
          <li key={task.id} className="relative">
            {selected ? (
              <span
                aria-hidden="true"
                className="absolute inset-y-0 start-0 w-1 bg-accent"
              />
            ) : null}
            <button
              type="button"
              aria-current={selected ? "true" : undefined}
              onClick={() => onSelect(task.id)}
              className={cn(
                "grid w-full gap-1 px-4 py-3 text-start hover:bg-muted/60",
                selected && "bg-primary-soft hover:bg-primary-soft",
              )}
            >
              <span className="flex items-center justify-between gap-2">
                <span className="font-mono text-sm font-semibold">
                  {task.report.reference}
                </span>
                <span className="text-xs text-muted-foreground">
                  {ago(task.created_at)}
                </span>
              </span>
              <span className="flex items-center gap-1.5 text-sm text-muted-foreground">
                <CategoryIcon
                  icon={task.report.category.icon}
                  className="size-4 shrink-0"
                />
                <span className="truncate">
                  {localized(task.report.category.name_i18n)}
                </span>
              </span>
              <span className="text-xs text-muted-foreground">
                {best
                  ? t("listBest", {
                      count: task.candidates.length,
                      score: format.number(best.score, {
                        minimumFractionDigits: 2,
                        maximumFractionDigits: 2,
                      }),
                    })
                  : t("listNoCandidates")}
              </span>
            </button>
          </li>
        );
      })}
    </ul>
  );
}

function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="contents">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="min-w-0">{children}</dd>
    </div>
  );
}

function ReportPanel({ task }: { task: ReviewTask }) {
  const t = useTranslations("admin.review");
  const localized = useLocalized();
  const ago = useAgo();
  const report = task.report;
  return (
    <Card className="grid content-start gap-3 p-4">
      <h3 className="flex items-center gap-2 font-semibold">
        <span className="cp-tag-inline" data-tone="report">
          {t("newReport")}
        </span>
        <span className="font-mono text-sm">{report.reference}</span>
      </h3>
      <PhotoGallery
        media={report.media}
        label={t("photosOf", { reference: report.reference })}
        className="grid-cols-3 sm:grid-cols-3"
      />
      <p className="whitespace-pre-line text-sm">
        {report.description || (
          <span className="text-muted-foreground">{t("noDescription")}</span>
        )}
      </p>
      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1.5 text-sm">
        <Fact label={t("category")}>
          <span className="inline-flex items-center gap-1.5">
            <CategoryIcon icon={report.category.icon} className="size-4" />
            {localized(report.category.name_i18n)}
          </span>
        </Fact>
        <Fact label={t("where")}>
          {report.address_text || t("noAddress")}
          {report.ward ? (
            <span className="block text-muted-foreground">
              {report.ward.name}
            </span>
          ) : null}
        </Fact>
        <Fact label={t("when")}>{ago(report.created_at)}</Fact>
        <Fact label={t("reporter")}>
          <span className="inline-flex items-center gap-1.5">
            <UserRound aria-hidden="true" className="size-4" />
            {report.reporter?.display_name || t("anonymous")}
          </span>
        </Fact>
      </dl>
    </Card>
  );
}

function CandidatePanel({ candidate }: { candidate: ReviewCandidate }) {
  const t = useTranslations("admin.review");
  const localized = useLocalized();
  const ago = useAgo();
  const issue = candidate.issue;
  return (
    <Card className="grid content-start gap-3 p-4">
      <h3 className="flex flex-wrap items-center gap-2 font-semibold">
        <span className="cp-tag-inline" data-tone="issue">
          {t("existingIssue")}
        </span>
        <Link
          href={`/admin/issues/${issue.id}`}
          className="inline-flex items-center gap-1 font-mono text-sm text-primary underline-offset-4 hover:underline"
        >
          {issue.reference}
          <ExternalLink aria-hidden="true" className="size-3.5" />
        </Link>
      </h3>
      {/* Same tile size as the report's photos, so the two compare fairly. */}
      <div className="grid grid-cols-3 gap-2">
        <RemoteImage
          src={issue.thumb_url}
          alt={t("issuePhoto", { reference: issue.reference })}
          className="aspect-square w-full rounded-lg border border-border object-cover"
        />
      </div>
      <div className="flex flex-wrap gap-1.5">
        <StatusBadge status={issue.status} />
        {issue.priority ? (
          <PriorityBadge
            band={issue.priority.band}
            score={issue.priority.score}
          />
        ) : null}
      </div>
      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1.5 text-sm">
        <Fact label={t("category")}>
          <span className="inline-flex items-center gap-1.5">
            <CategoryIcon icon={issue.category.icon} className="size-4" />
            {localized(issue.category.name_i18n)}
          </span>
        </Fact>
        <Fact label={t("where")}>
          {issue.address_text || t("noAddress")}
          {issue.ward ? (
            <span className="block text-muted-foreground">
              {issue.ward.name}
            </span>
          ) : null}
        </Fact>
        <Fact label={t("reports")}>
          {t("reportCount", {
            reports: issue.report_count,
            people: issue.unique_reporter_count,
          })}
        </Fact>
        <Fact label={t("opened")}>{ago(issue.created_at)}</Fact>
      </dl>
    </Card>
  );
}

function Comparison({
  task,
  candidateIndex,
  onCandidate,
  onResolve,
  pending,
  conflict,
  error,
  onNext,
  hasNext,
}: {
  task: ReviewTask;
  candidateIndex: number;
  onCandidate: (index: number) => void;
  onResolve: (action: ReviewAction) => void;
  pending: ReviewAction["action"] | null;
  conflict: boolean;
  error: string | null;
  onNext: () => void;
  hasNext: boolean;
}) {
  const t = useTranslations("admin.review");
  const format = useFormatter();
  const groupName = useId();
  const candidate = task.candidates[candidateIndex] ?? null;

  if (conflict) {
    return (
      <Alert variant="warning" live="assertive" title={t("conflictTitle")}>
        <p>{t("conflictBody")}</p>
        <Button size="sm" className="mt-3" onClick={onNext}>
          {hasNext ? t("conflictNext") : t("conflictReload")}
        </Button>
      </Alert>
    );
  }

  return (
    <div className="grid gap-4">
      {task.candidates.length > 1 ? (
        <fieldset className="grid gap-2">
          <legend className="mb-1 text-sm font-semibold">
            {t("candidatesLegend", { count: task.candidates.length })}
          </legend>
          <div className="flex flex-wrap gap-2">
            {task.candidates.map((item, index) => (
              <label
                key={item.match_decision_id}
                className={cn(
                  "flex cursor-pointer items-center gap-2 rounded-lg border px-3 py-2 text-sm has-focus-visible:ring-3 has-focus-visible:ring-ring/30",
                  index === candidateIndex
                    ? "border-primary bg-primary-soft"
                    : "border-input bg-card hover:bg-muted",
                )}
              >
                <input
                  type="radio"
                  name={groupName}
                  checked={index === candidateIndex}
                  onChange={() => onCandidate(index)}
                  className="size-4 accent-primary"
                  aria-keyshortcuts={index < 9 ? String(index + 1) : undefined}
                />
                <span className="font-mono font-semibold">
                  {item.issue.reference}
                </span>
                <span className="tabular-nums text-muted-foreground">
                  {t("candidateScore", {
                    score: format.number(item.score, {
                      minimumFractionDigits: 2,
                      maximumFractionDigits: 2,
                    }),
                  })}
                </span>
                {index < 9 ? <Kbd>{index + 1}</Kbd> : null}
              </label>
            ))}
          </div>
        </fieldset>
      ) : null}

      <div className="grid gap-4 md:grid-cols-2">
        <ReportPanel task={task} />
        {candidate ? (
          <CandidatePanel candidate={candidate} />
        ) : (
          <Card className="grid place-items-center p-6 text-center text-sm text-muted-foreground">
            {t("noCandidates")}
          </Card>
        )}
      </div>

      {candidate ? (
        <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)] lg:items-start">
          <Card className="grid content-start gap-3 p-4">
            <h3 className="font-semibold">{t("mapHeading")}</h3>
            <div className="h-56 overflow-hidden rounded-lg border border-border">
              <ComparisonMap
                report={task.report.location}
                issue={candidate.issue.location}
                radiusM={candidate.signals.radius_m}
                reportLabel={t("newReport")}
                issueLabel={candidate.issue.reference}
                label={t("mapLabel", {
                  report: task.report.reference,
                  issue: candidate.issue.reference,
                })}
              />
            </div>
            <p className="flex items-center gap-1.5 text-sm">
              <MapPin aria-hidden="true" className="size-4 shrink-0" />
              {t("distanceApart", {
                distance: format.number(candidate.signals.distance_m, {
                  maximumFractionDigits: 0,
                }),
                radius: format.number(candidate.signals.radius_m, {
                  maximumFractionDigits: 0,
                }),
              })}
            </p>
          </Card>
          <Card className="grid content-start gap-3 p-4">
            <h3 className="font-semibold">{t("whyHeading")}</h3>
            <SignalBreakdown
              signals={candidate.signals}
              score={candidate.score}
            />
          </Card>
        </div>
      ) : null}

      {error ? (
        <Alert variant="destructive" live="assertive">
          {error}
        </Alert>
      ) : null}

      <div className="sticky bottom-0 z-20 -mx-4 flex flex-col gap-2 border-t border-border bg-background/95 px-4 py-3 backdrop-blur sm:static sm:mx-0 sm:flex-row sm:justify-end sm:border-0 sm:bg-transparent sm:px-0 sm:backdrop-blur-none">
        <Button
          variant="outline"
          size="lg"
          onClick={() => onResolve({ action: "new_issue" })}
          loading={pending === "new_issue"}
          disabled={pending !== null}
          aria-keyshortcuts="N"
        >
          <CirclePlus aria-hidden="true" />
          {t("newIssue")}
          <Kbd>N</Kbd>
        </Button>
        {candidate ? (
          <Button
            size="lg"
            onClick={() =>
              onResolve({ action: "link", issue_id: candidate.issue.id })
            }
            loading={pending === "link"}
            disabled={pending !== null}
            aria-keyshortcuts="L"
          >
            <Link2 aria-hidden="true" />
            {t("link", { reference: candidate.issue.reference })}
            <Kbd>L</Kbd>
          </Button>
        ) : null}
      </div>
    </div>
  );
}

function ShortcutHelp({ open }: { open: boolean }) {
  const t = useTranslations("admin.review.shortcuts");
  if (!open) return null;
  const rows: [string, string][] = [
    ["J", t("next")],
    ["K", t("previous")],
    ["1–9", t("candidate")],
    ["L", t("link")],
    ["N", t("newIssue")],
    ["?", t("toggle")],
  ];
  return (
    <Card className="mb-4 p-4">
      <h2 className="mb-2 text-sm font-semibold">{t("title")}</h2>
      <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-sm sm:grid-cols-[auto_1fr_auto_1fr]">
        {rows.map(([key, label]) => (
          <div key={key} className="contents">
            <dt>
              <kbd className="inline-grid min-w-6 place-items-center rounded border border-input px-1.5 font-mono text-xs font-semibold">
                {key}
              </kbd>
            </dt>
            <dd>{label}</dd>
          </div>
        ))}
      </dl>
    </Card>
  );
}

/**
 * The duplicate review queue (FR-031, FR-035, FR-037): reports the
 * matcher wasn't sure about, each next to the issues it might duplicate,
 * with the evidence and the reasoning, and two decisions. Nothing here is
 * decided by the AI alone (PRD §8.6).
 *
 * The task being reviewed is kept in `?task=` so a link to it can be
 * shared. Single-key shortcuts (J/K, 1–9, L, N) make a run of reviews
 * quick, and every one of them has a visible button with its key shown.
 */
export function ReviewScreen() {
  const t = useTranslations("admin.review");
  const errorMessage = useErrorMessage();
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const searchParams = useSearchParams();
  const [selectedId, setSelectedId] = useState<string | null>(
    searchParams.get("task"),
  );
  const [candidateIndex, setCandidateIndex] = useState(0);
  const [listOpen, setListOpen] = useState(false);
  const [help, setHelp] = useState(false);
  const [conflictId, setConflictId] = useState<string | null>(null);

  const tasks = useQuery({
    queryKey: LIST_KEY,
    queryFn: ({ signal }) =>
      listReviewTasks({ status: "open", limit: 50 }, signal),
  });
  const items = tasks.data?.items ?? [];
  const current =
    (selectedId ? items.find((task) => task.id === selectedId) : items[0]) ??
    null;
  const index = current ? items.indexOf(current) : -1;
  const missing = Boolean(selectedId && tasks.isSuccess && !current);

  const select = useCallback((id: string | null) => {
    setSelectedId(id);
    setCandidateIndex(0);
    setListOpen(false);
    setConflictId(null);
    const url = new URL(window.location.href);
    if (id) url.searchParams.set("task", id);
    else url.searchParams.delete("task");
    window.history.replaceState(null, "", `${url.pathname}${url.search}`);
  }, []);

  // A fresh list can drop the task on screen (someone else resolved it);
  // keep the candidate index in range either way.
  useEffect(() => {
    if (current && candidateIndex >= Math.max(1, current.candidates.length)) {
      setCandidateIndex(0);
    }
  }, [current, candidateIndex]);

  const nextAfter = (task: ReviewTask) => {
    const position = items.indexOf(task);
    return items[position + 1] ?? items[position - 1] ?? null;
  };

  const mutation = useMutation({
    mutationFn: ({
      task,
      action,
    }: {
      task: ReviewTask;
      action: ReviewAction;
    }) => resolveReviewTask(task.id, action),
    onSuccess: (result, { task, action }) => {
      // The report's issue as placed: the new issue, or the one it joined
      // (the survivor, if the chosen candidate was merged meanwhile).
      const placed = result.report.issue?.reference;
      const chosen =
        action.action === "link"
          ? task.candidates.find((c) => c.issue.id === action.issue_id)?.issue
              .reference
          : undefined;
      const report = task.report.reference;
      toast({
        variant: "success",
        title:
          action.action === "link"
            ? t("linked", { report, issue: placed ?? chosen ?? "" })
            : placed
              ? t("createdAs", { report, issue: placed })
              : t("created", { report }),
      });
      const next = nextAfter(task);
      queryClient.setQueryData(
        LIST_KEY,
        (page: typeof tasks.data) =>
          page && {
            ...page,
            items: page.items.filter((item) => item.id !== task.id),
            total: Math.max(0, page.total - 1),
          },
      );
      select(next?.id ?? null);
      queryClient.invalidateQueries({ queryKey: LIST_KEY });
      queryClient.invalidateQueries({ queryKey: REVIEW_COUNT_KEY });
      queryClient.invalidateQueries({ queryKey: ["issues"] });
    },
    onError: (error, { task }) => {
      if (isApiError(error, "conflict")) setConflictId(task.id);
    },
  });

  const resolve = (action: ReviewAction) => {
    if (!current || mutation.isPending) return;
    if (action.action === "link" && !current.candidates[candidateIndex]) return;
    mutation.mutate({ task: current, action });
  };

  const goNextAfterConflict = () => {
    const next = current ? nextAfter(current) : null;
    queryClient.invalidateQueries({ queryKey: LIST_KEY });
    queryClient.invalidateQueries({ queryKey: REVIEW_COUNT_KEY });
    select(next?.id ?? null);
    mutation.reset();
  };

  useShortcuts(
    {
      j: () => items[index + 1] && select(items[index + 1].id),
      k: () => index > 0 && select(items[index - 1].id),
      l: () => {
        const candidate = current?.candidates[candidateIndex];
        if (candidate)
          resolve({ action: "link", issue_id: candidate.issue.id });
      },
      n: () => resolve({ action: "new_issue" }),
      "?": () => setHelp((value) => !value),
      ...Object.fromEntries(
        Array.from({ length: 9 }, (_, i) => [
          String(i + 1),
          () => {
            if (current && i < current.candidates.length) setCandidateIndex(i);
          },
        ]),
      ),
    },
    tasks.isSuccess && conflictId === null,
  );

  const conflict = Boolean(current && conflictId === current.id);
  const serverError =
    mutation.isError &&
    mutation.variables?.task.id === current?.id &&
    !isApiError(mutation.error, "conflict")
      ? errorMessage(mutation.error)
      : null;

  return (
    <div className="motion-safe:animate-rise">
      <PageHeader
        title={t("title")}
        description={t("description")}
        actions={
          <Button
            variant="outline"
            className="max-sm:hidden"
            aria-expanded={help}
            aria-keyshortcuts="?"
            onClick={() => setHelp((value) => !value)}
          >
            <Keyboard aria-hidden="true" />
            {t("shortcuts.title")}
            <Kbd>?</Kbd>
          </Button>
        }
      />
      <ShortcutHelp open={help} />

      {tasks.isPending ? (
        <PageLoading />
      ) : tasks.isError ? (
        <Alert variant="destructive" live="assertive" title={t("loadError")}>
          <p>{errorMessage(tasks.error)}</p>
          <Button
            variant="outline"
            size="sm"
            className="mt-3"
            onClick={() => tasks.refetch()}
          >
            {t("retry")}
          </Button>
        </Alert>
      ) : items.length === 0 ? (
        <Card className="grid justify-items-center gap-2 px-6 py-12 text-center">
          <Inbox aria-hidden="true" className="size-9 text-muted-foreground" />
          <p className="font-semibold">{t("emptyTitle")}</p>
          <p className="max-w-md text-sm text-muted-foreground">
            {t("emptyBody")}
          </p>
        </Card>
      ) : (
        <div className="grid gap-4 lg:grid-cols-[18rem_minmax(0,1fr)] lg:items-start">
          <section
            aria-labelledby="review-list-heading"
            className={cn(
              "overflow-hidden rounded-xl border border-border bg-card shadow-card lg:sticky lg:top-20",
              current && !listOpen && "max-lg:hidden",
            )}
          >
            <h2
              id="review-list-heading"
              className="border-b border-border px-4 py-3 text-sm font-semibold"
            >
              {t("listHeading", { count: tasks.data.total })}
            </h2>
            <TaskList
              tasks={items}
              selectedId={current?.id ?? null}
              onSelect={select}
            />
          </section>

          <section aria-labelledby="review-task-heading" className="grid gap-4">
            {missing ? (
              <Alert variant="info" title={t("missingTitle")}>
                <p>{t("missingBody")}</p>
                <Button
                  size="sm"
                  variant="outline"
                  className="mt-3"
                  onClick={() => select(items[0]?.id ?? null)}
                >
                  {t("conflictNext")}
                </Button>
              </Alert>
            ) : current ? (
              <>
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <h2
                    id="review-task-heading"
                    className="text-lg font-semibold"
                  >
                    {t("taskHeading", {
                      reference: current.report.reference,
                      position: index + 1,
                      count: items.length,
                    })}
                  </h2>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="lg:hidden"
                    onClick={() => setListOpen(true)}
                  >
                    <ArrowLeft aria-hidden="true" className="rtl:rotate-180" />
                    {t("backToList", { count: items.length })}
                  </Button>
                </div>
                <Comparison
                  key={current.id}
                  task={current}
                  candidateIndex={candidateIndex}
                  onCandidate={setCandidateIndex}
                  onResolve={resolve}
                  pending={
                    mutation.isPending
                      ? (mutation.variables?.action.action ?? null)
                      : null
                  }
                  conflict={conflict}
                  error={serverError}
                  onNext={goNextAfterConflict}
                  hasNext={items.length > 1}
                />
              </>
            ) : null}
          </section>
        </div>
      )}
    </div>
  );
}
