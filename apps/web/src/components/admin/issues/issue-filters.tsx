"use client";

import { useQuery } from "@tanstack/react-query";
import { ChevronDown, Search, SlidersHorizontal, X } from "lucide-react";
import { useTranslations } from "next-intl";
import { useEffect, useId, useRef, useState } from "react";
import { CategoryIcon } from "@/components/issues/category-icon";
import { PRIORITY_STYLE } from "@/components/issues/priority-badge";
import { STATUS_STYLE } from "@/components/issues/status-badge";
import { Button } from "@/components/ui/button";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { MultiSelect } from "@/components/ui/multi-select";
import { useDebouncedValue } from "@/hooks/use-debounced-value";
import { useLocalized } from "@/hooks/use-reference-data";
import {
  ISSUE_STATUSES,
  listAdminCategories,
  listCategories,
  listJurisdictions,
  PRIORITY_BANDS,
  SEVERITY_LEVELS,
} from "@/lib/api";
import { hasPermission } from "@/lib/auth/access";
import { useSession } from "@/lib/auth/use-session";
import {
  activeFilterCount,
  type IssueFilters,
  isRangeInverted,
} from "@/lib/issues/filters";
import { cn } from "@/lib/utils";

export function useWards() {
  return useQuery({
    queryKey: ["admin", "wards"],
    queryFn: ({ signal }) => listJurisdictions({ kind: "ward" }, signal),
    staleTime: 10 * 60_000,
    // The list can include the city and zones; only wards are filters.
    select: (page) => page.items.filter((item) => item.kind === "ward"),
  });
}

/** Staff filter on every category, including deactivated ones. */
export function useFilterCategories() {
  const { user } = useSession();
  const canSeeAll = hasPermission(user, "config:read");
  return useQuery({
    queryKey: ["categories", canSeeAll ? "all" : "active"],
    queryFn: async ({ signal }) =>
      canSeeAll
        ? (await listAdminCategories(signal)).items
        : listCategories(signal),
    staleTime: 10 * 60_000,
  });
}

export function IssueFiltersBar({
  filters,
  onChange,
  className,
}: {
  filters: IssueFilters;
  onChange: (
    changes: Partial<IssueFilters>,
    options?: { replace?: boolean },
  ) => void;
  className?: string;
}) {
  const t = useTranslations("admin.issues.filters");
  const tStatus = useTranslations("issueStatus");
  const tPriority = useTranslations("priority");
  const tSeverity = useTranslations("severity");
  const localized = useLocalized();
  const wards = useWards();
  const categories = useFilterCategories();
  const searchId = useId();

  // The search box keeps its own state and writes to the URL after a
  // pause, replacing the history entry rather than adding one per key.
  const [search, setSearch] = useState(filters.q);
  const debounced = useDebouncedValue(search.trim(), 350);
  const lastWritten = useRef(filters.q);
  useEffect(() => {
    if (filters.q !== lastWritten.current) {
      lastWritten.current = filters.q;
      setSearch(filters.q);
    }
  }, [filters.q]);
  useEffect(() => {
    if (debounced === lastWritten.current) return;
    lastWritten.current = debounced;
    onChange({ q: debounced }, { replace: true });
  }, [debounced, onChange]);

  const inverted = isRangeInverted(filters);
  const count = activeFilterCount(filters);
  // On phones only the search box shows until the filters are opened;
  // five stacked controls would push the results off the first screen.
  const [expanded, setExpanded] = useState(false);
  const collapsible = expanded ? undefined : "max-sm:hidden";
  const extraCount = count - (filters.q ? 1 : 0);
  const selectedLabel = (n: number) => t("selected", { count: n });

  return (
    <search
      className={cn(
        "grid gap-3 rounded-xl border border-border bg-card p-4 shadow-card",
        className,
      )}
    >
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-[2fr_repeat(3,minmax(0,1fr))]">
        <div className="grid gap-1.5 sm:col-span-2 xl:col-span-1">
          <Label htmlFor={searchId}>{t("search")}</Label>
          <div className="relative">
            <Search
              aria-hidden="true"
              className="pointer-events-none absolute start-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground"
            />
            <Input
              id={searchId}
              type="search"
              value={search}
              placeholder={t("searchPlaceholder")}
              className="ps-9"
              onChange={(event) => setSearch(event.target.value)}
            />
          </div>
          <Button
            variant="outline"
            size="sm"
            className="mt-1 justify-self-start sm:hidden"
            aria-expanded={expanded}
            onClick={() => setExpanded((value) => !value)}
          >
            <SlidersHorizontal aria-hidden="true" />
            {extraCount > 0
              ? t("moreFiltersCount", { count: extraCount })
              : t("moreFilters")}
            <ChevronDown
              aria-hidden="true"
              className={cn("transition-transform", expanded && "rotate-180")}
            />
          </Button>
        </div>
        <MultiSelect
          className={collapsible}
          label={t("status")}
          allLabel={t("allStatuses")}
          selectedLabel={selectedLabel}
          value={filters.status}
          onChange={(status) =>
            onChange({ status: status as IssueFilters["status"] })
          }
          options={ISSUE_STATUSES.map((status) => {
            const Icon = STATUS_STYLE[status].icon;
            return {
              value: status,
              label: tStatus(status),
              icon: (
                <Icon
                  aria-hidden="true"
                  className="size-4 text-muted-foreground"
                />
              ),
            };
          })}
        />
        <MultiSelect
          className={collapsible}
          label={t("category")}
          allLabel={t("allCategories")}
          selectedLabel={selectedLabel}
          value={filters.category}
          onChange={(category) => onChange({ category })}
          options={(categories.data ?? []).map((category) => ({
            value: category.id,
            label: localized(category.name_i18n),
            icon: (
              <CategoryIcon
                icon={category.icon}
                className="size-4 text-muted-foreground"
              />
            ),
          }))}
        />
        <MultiSelect
          className={collapsible}
          label={t("ward")}
          allLabel={t("allWards")}
          selectedLabel={selectedLabel}
          value={filters.ward}
          onChange={(ward) => onChange({ ward })}
          options={(wards.data ?? []).map((ward) => ({
            value: ward.id,
            label: ward.name,
          }))}
        />
      </div>
      <div className={cn("flex flex-wrap items-end gap-3", collapsible)}>
        <MultiSelect
          className="w-full sm:w-48"
          label={t("priority")}
          allLabel={t("allPriorities")}
          selectedLabel={selectedLabel}
          value={filters.band}
          onChange={(band) => onChange({ band: band as IssueFilters["band"] })}
          options={PRIORITY_BANDS.map((band) => {
            const Icon = PRIORITY_STYLE[band].icon;
            return {
              value: band,
              label: tPriority(`band.${band}`),
              icon: (
                <Icon
                  aria-hidden="true"
                  className="size-4 text-muted-foreground"
                />
              ),
            };
          })}
        />
        <MultiSelect
          className="w-full sm:w-48"
          label={t("severity")}
          allLabel={t("allSeverities")}
          selectedLabel={selectedLabel}
          value={filters.severity}
          onChange={(severity) =>
            onChange({ severity: severity as IssueFilters["severity"] })
          }
          options={[...SEVERITY_LEVELS].reverse().map((level) => ({
            value: level,
            label: tSeverity(`level.${level}`),
          }))}
        />
        <Field label={t("from")} className="w-40">
          {(control) => (
            <Input
              {...control}
              type="date"
              value={filters.from ?? ""}
              max={filters.to ?? undefined}
              onChange={(event) =>
                onChange({ from: event.target.value || null })
              }
            />
          )}
        </Field>
        <Field
          label={t("to")}
          className="w-40"
          error={inverted ? t("rangeInvalid") : undefined}
        >
          {(control) => (
            <Input
              {...control}
              type="date"
              value={filters.to ?? ""}
              min={filters.from ?? undefined}
              onChange={(event) => onChange({ to: event.target.value || null })}
            />
          )}
        </Field>
        {count > 0 ? (
          <Button
            variant="ghost"
            size="sm"
            className="mb-1"
            onClick={() => {
              setSearch("");
              lastWritten.current = "";
              onChange({
                status: [],
                category: [],
                ward: [],
                severity: [],
                band: [],
                from: null,
                to: null,
                q: "",
              });
            }}
          >
            <X aria-hidden="true" />
            {t("clear", { count })}
          </Button>
        ) : null}
      </div>
    </search>
  );
}
