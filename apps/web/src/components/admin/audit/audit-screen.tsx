"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { ChevronRight, ScrollText } from "lucide-react";
import { useFormatter, useTranslations } from "next-intl";
import { Fragment, useId, useState } from "react";
import { PageHeader } from "@/components/admin/page-header";
import { Pagination } from "@/components/admin/pagination";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useDebouncedValue } from "@/hooks/use-debounced-value";
import { useErrorMessage } from "@/hooks/use-error-message";
import { type AuditEvent, listAuditEvents } from "@/lib/api";
import { cn } from "@/lib/utils";
import { changedKeys, prettyJson } from "./json-diff";

const PAGE_SIZE = 25;
// Date inputs give a calendar day; interpret it in the municipality's zone.
const IST_OFFSET = "+05:30";

function dayStart(date: string): string | undefined {
  return date
    ? new Date(`${date}T00:00:00${IST_OFFSET}`).toISOString()
    : undefined;
}
function dayEnd(date: string): string | undefined {
  return date
    ? new Date(`${date}T23:59:59.999${IST_OFFSET}`).toISOString()
    : undefined;
}

type Filters = {
  action: string;
  entity_type: string;
  entity_id: string;
  actor_id: string;
  from: string;
  to: string;
};

const emptyFilters: Filters = {
  action: "",
  entity_type: "",
  entity_id: "",
  actor_id: "",
  from: "",
  to: "",
};

export function AuditScreen() {
  const t = useTranslations("admin.audit");
  const format = useFormatter();
  const errorMessage = useErrorMessage();
  const baseId = useId();
  const [filters, setFilters] = useState<Filters>(emptyFilters);
  const [offset, setOffset] = useState(0);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const debounced = useDebouncedValue(filters, 300);
  const params = {
    action: debounced.action.trim() || undefined,
    entity_type: debounced.entity_type.trim() || undefined,
    entity_id: debounced.entity_id.trim() || undefined,
    actor_id: debounced.actor_id.trim() || undefined,
    from: dayStart(debounced.from),
    to: dayEnd(debounced.to),
    limit: PAGE_SIZE,
    offset,
    sort: "-occurred_at",
  };

  const events = useQuery({
    queryKey: ["admin", "audit-events", params],
    queryFn: ({ signal }) => listAuditEvents(params, signal),
    placeholderData: keepPreviousData,
    // Don't ask the API for an impossible range; the field explains why.
    enabled: !(debounced.from && debounced.to && debounced.from > debounced.to),
  });

  const update = (key: keyof Filters) => (value: string) => {
    setFilters((current) => ({ ...current, [key]: value }));
    setOffset(0);
  };
  const filtersActive = Object.values(filters).some(Boolean);
  const rangeInvalid = Boolean(
    filters.from && filters.to && filters.from > filters.to,
  );

  const toggle = (id: string) =>
    setExpanded((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const textFilters: {
    key: keyof Filters;
    label: string;
    placeholder: string;
  }[] = [
    {
      key: "action",
      label: t("filterAction"),
      placeholder: "user.roles_changed",
    },
    { key: "entity_type", label: t("filterEntityType"), placeholder: "user" },
    {
      key: "entity_id",
      label: t("filterEntityId"),
      placeholder: t("idPlaceholder"),
    },
    {
      key: "actor_id",
      label: t("filterActorId"),
      placeholder: t("idPlaceholder"),
    },
  ];

  return (
    <div className="motion-safe:animate-rise">
      <PageHeader title={t("title")} description={t("description")} />

      <search className="mb-4 grid gap-3 rounded-xl border border-border bg-card p-4 shadow-card sm:grid-cols-2 lg:grid-cols-3">
        {textFilters.map(({ key, label, placeholder }) => (
          <div key={key} className="grid gap-1.5">
            <Label htmlFor={`${baseId}-${key}`}>{label}</Label>
            <Input
              id={`${baseId}-${key}`}
              value={filters[key]}
              placeholder={placeholder}
              spellCheck={false}
              className="font-mono text-sm"
              onChange={(event) => update(key)(event.target.value)}
            />
          </div>
        ))}
        <div className="grid gap-1.5">
          <Label htmlFor={`${baseId}-from`}>{t("filterFrom")}</Label>
          <Input
            id={`${baseId}-from`}
            type="date"
            value={filters.from}
            max={filters.to || undefined}
            onChange={(event) => update("from")(event.target.value)}
          />
        </div>
        <div className="grid gap-1.5">
          <Label htmlFor={`${baseId}-to`}>{t("filterTo")}</Label>
          <Input
            id={`${baseId}-to`}
            type="date"
            value={filters.to}
            min={filters.from || undefined}
            aria-invalid={rangeInvalid || undefined}
            aria-describedby={
              rangeInvalid ? `${baseId}-range-error` : undefined
            }
            onChange={(event) => update("to")(event.target.value)}
          />
          {rangeInvalid ? (
            <p
              id={`${baseId}-range-error`}
              className="text-sm font-medium text-destructive-soft-foreground"
            >
              {t("rangeInvalid")}
            </p>
          ) : null}
        </div>
        {filtersActive ? (
          <div className="flex items-end sm:col-span-2 lg:col-span-3">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                setFilters(emptyFilters);
                setOffset(0);
              }}
            >
              {t("clearFilters")}
            </Button>
          </div>
        ) : null}
      </search>

      {events.isError ? (
        <Alert
          variant="destructive"
          live="assertive"
          title={t("loadError")}
          className="mb-4"
        >
          <p>{errorMessage(events.error)}</p>
          <Button
            variant="outline"
            size="sm"
            className="mt-3"
            onClick={() => events.refetch()}
          >
            {t("retry")}
          </Button>
        </Alert>
      ) : null}

      <Table label={t("tableLabel")} aria-busy={events.isFetching || undefined}>
        <TableHeader>
          <TableRow className="hover:bg-transparent">
            <TableHead className="w-10">
              <span className="sr-only">{t("colDetails")}</span>
            </TableHead>
            <TableHead>{t("colWhen")}</TableHead>
            <TableHead>{t("colActor")}</TableHead>
            <TableHead>{t("colAction")}</TableHead>
            <TableHead>{t("colEntity")}</TableHead>
            <TableHead>{t("colRequest")}</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {events.isPending ? (
            Array.from({ length: 6 }, (_, index) => (
              // biome-ignore lint/suspicious/noArrayIndexKey: static placeholder rows
              <TableRow key={index}>
                {Array.from({ length: 6 }, (_, cell) => (
                  // biome-ignore lint/suspicious/noArrayIndexKey: static placeholder cells
                  <TableCell key={cell}>
                    <Skeleton className="h-4 w-full max-w-32" />
                  </TableCell>
                ))}
              </TableRow>
            ))
          ) : events.data?.items.length ? (
            events.data.items.map((event) => (
              <AuditRow
                key={event.id}
                event={event}
                open={expanded.has(String(event.id))}
                onToggle={() => toggle(String(event.id))}
                whenLabel={format.dateTime(new Date(event.occurred_at), {
                  dateStyle: "medium",
                  timeStyle: "medium",
                })}
              />
            ))
          ) : events.isSuccess ? (
            <TableRow className="hover:bg-transparent">
              <TableCell colSpan={6}>
                <div className="grid justify-items-center gap-2 py-10 text-center">
                  <ScrollText
                    aria-hidden="true"
                    className="size-8 text-muted-foreground"
                  />
                  <p className="font-semibold">
                    {filtersActive ? t("emptyFiltered") : t("empty")}
                  </p>
                </div>
              </TableCell>
            </TableRow>
          ) : null}
        </TableBody>
      </Table>

      {events.data ? (
        <Pagination
          label={t("paginationLabel")}
          offset={events.data.offset}
          limit={events.data.limit}
          total={events.data.total}
          onOffsetChange={setOffset}
        />
      ) : null}
    </div>
  );
}

function AuditRow({
  event,
  open,
  onToggle,
  whenLabel,
}: {
  event: AuditEvent;
  open: boolean;
  onToggle: () => void;
  whenLabel: string;
}) {
  const t = useTranslations("admin.audit");
  const detailsId = `audit-${event.id}-details`;
  const changed = changedKeys(event.before, event.after);

  return (
    <Fragment>
      <TableRow className={cn(open && "bg-muted/40")}>
        <TableCell className="py-2">
          <Button
            variant="ghost"
            size="icon-sm"
            aria-expanded={open}
            aria-controls={detailsId}
            aria-label={t("toggleDetails", {
              action: event.action,
              when: whenLabel,
            })}
            onClick={onToggle}
          >
            <ChevronRight
              aria-hidden="true"
              className={cn(
                "transition-transform rtl:rotate-180",
                open && "rotate-90 rtl:rotate-90",
              )}
            />
          </Button>
        </TableCell>
        <TableCell className="whitespace-nowrap">
          <time dateTime={event.occurred_at}>{whenLabel}</time>
        </TableCell>
        <TableCell>
          {event.actor ? (
            event.actor.display_name || (
              <span className="font-mono text-xs">{event.actor.id}</span>
            )
          ) : (
            <span className="text-muted-foreground">{t("system")}</span>
          )}
        </TableCell>
        <TableCell>
          <Badge variant="info" className="font-mono font-medium">
            {event.action}
          </Badge>
        </TableCell>
        <TableCell>
          <div className="grid gap-0.5">
            <span className="font-medium">{event.entity_type}</span>
            {event.entity_id ? (
              <span className="max-w-48 truncate font-mono text-xs text-muted-foreground">
                {event.entity_id}
              </span>
            ) : null}
          </div>
        </TableCell>
        <TableCell className="max-w-40 truncate font-mono text-xs text-muted-foreground">
          {event.request_id ?? "—"}
        </TableCell>
      </TableRow>
      <TableRow id={detailsId} hidden={!open} className="hover:bg-transparent">
        <TableCell colSpan={6} className="bg-muted/40 pt-0">
          {open ? (
            <div className="grid gap-3 pb-2">
              <p className="text-sm">
                <span className="font-semibold">{t("changed")}</span>{" "}
                {changed.length ? (
                  changed.map((key) => (
                    <code
                      key={key}
                      className="me-1 rounded bg-accent-soft px-1.5 py-0.5 font-mono text-xs"
                    >
                      {key}
                    </code>
                  ))
                ) : (
                  <span className="text-muted-foreground">
                    {t("noChanges")}
                  </span>
                )}
              </p>
              <div className="grid gap-3 md:grid-cols-2">
                {(
                  [
                    ["before", event.before],
                    ["after", event.after],
                  ] as const
                ).map(([label, value]) => (
                  <figure key={label} className="grid gap-1.5">
                    <figcaption className="text-xs font-semibold tracking-wide text-muted-foreground uppercase">
                      {t(label)}
                    </figcaption>
                    <pre className="max-h-80 overflow-auto rounded-lg border border-border bg-card p-3 font-mono text-xs leading-relaxed">
                      {prettyJson(value)}
                    </pre>
                  </figure>
                ))}
              </div>
            </div>
          ) : null}
        </TableCell>
      </TableRow>
    </Fragment>
  );
}
