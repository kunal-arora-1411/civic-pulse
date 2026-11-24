"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Search, X } from "lucide-react";
import { useTranslations } from "next-intl";
import { useId, useState } from "react";
import { CategoryIcon } from "@/components/issues/category-icon";
import { StatusBadge } from "@/components/issues/status-badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useDebouncedValue } from "@/hooks/use-debounced-value";
import { useLocalized } from "@/hooks/use-reference-data";
import { type IssueListItem, listIssues } from "@/lib/api";
import { cn } from "@/lib/utils";

function IssueSummary({ issue }: { issue: IssueListItem }) {
  const t = useTranslations("admin.issueDetail.picker");
  const localized = useLocalized();
  return (
    <span className="grid min-w-0 flex-1 gap-0.5">
      <span className="flex flex-wrap items-center gap-2">
        <span className="font-mono text-sm font-semibold">
          {issue.reference}
        </span>
        <StatusBadge status={issue.status} />
      </span>
      <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
        <CategoryIcon icon={issue.category.icon} className="size-3.5" />
        <span className="truncate">
          {localized(issue.category.name_i18n)} ·{" "}
          {issue.address_text || t("noAddress")} ·{" "}
          {t("reports", { count: issue.report_count })}
        </span>
      </span>
    </span>
  );
}

/**
 * Find other issues by reference or address and pick one or several.
 * The results are native checkboxes or radios; picked issues stay listed
 * above the search, with a remove button, whatever is typed next.
 */
export function IssuePicker({
  label,
  excludeIds,
  selected,
  onChange,
  multiple = false,
  error,
}: {
  label: string;
  /** Never offered, e.g. the issue being edited. */
  excludeIds: readonly string[];
  selected: IssueListItem[];
  onChange: (issues: IssueListItem[]) => void;
  multiple?: boolean;
  error?: string;
}) {
  const t = useTranslations("admin.issueDetail.picker");
  const searchId = useId();
  const name = useId();
  const errorId = useId();
  const [text, setText] = useState("");
  const q = useDebouncedValue(text.trim(), 300);

  const results = useQuery({
    queryKey: ["issues", "list", "picker", q],
    queryFn: ({ signal }) =>
      listIssues({ q, limit: 8, sort: "-created_at" }, signal),
    enabled: q.length >= 2,
    placeholderData: keepPreviousData,
  });
  const offered = (results.data?.items ?? []).filter(
    (issue) => !excludeIds.includes(issue.id),
  );
  const isSelected = (issue: IssueListItem) =>
    selected.some((item) => item.id === issue.id);
  const toggle = (issue: IssueListItem) => {
    if (!multiple) return onChange([issue]);
    onChange(
      isSelected(issue)
        ? selected.filter((item) => item.id !== issue.id)
        : [...selected, issue],
    );
  };

  return (
    <div className="grid gap-2">
      {selected.length > 0 ? (
        <ul className="grid gap-2" aria-label={t("selected")}>
          {selected.map((issue) => (
            <li
              key={issue.id}
              className="flex items-center gap-2 rounded-lg border border-primary bg-primary-soft px-3 py-2"
            >
              <IssueSummary issue={issue} />
              <Button
                variant="ghost"
                size="icon-sm"
                aria-label={t("remove", { reference: issue.reference })}
                onClick={() =>
                  onChange(selected.filter((item) => item.id !== issue.id))
                }
              >
                <X aria-hidden="true" />
              </Button>
            </li>
          ))}
        </ul>
      ) : null}

      <Label htmlFor={searchId}>{label}</Label>
      <p
        id={`${searchId}-help`}
        className="-mt-1 text-sm text-muted-foreground"
      >
        {t("help")}
      </p>
      <div className="relative">
        <Search
          aria-hidden="true"
          className="pointer-events-none absolute start-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground"
        />
        <Input
          id={searchId}
          type="search"
          value={text}
          onChange={(event) => setText(event.target.value)}
          placeholder={t("placeholder")}
          aria-describedby={[`${searchId}-help`, error ? errorId : null]
            .filter(Boolean)
            .join(" ")}
          aria-invalid={error ? true : undefined}
          className="ps-9"
          autoComplete="off"
        />
      </div>
      {error ? (
        <p
          id={errorId}
          className="text-sm font-medium text-destructive-soft-foreground"
        >
          {error}
        </p>
      ) : null}

      <output className="text-sm text-muted-foreground">
        {q.length < 2
          ? ""
          : results.isPending
            ? t("searching")
            : offered.length === 0
              ? t("noResults")
              : t("resultCount", { count: offered.length })}
      </output>
      {q.length >= 2 && offered.length > 0 ? (
        <fieldset className="grid max-h-64 gap-1.5 overflow-y-auto">
          <legend className="sr-only">{t("results")}</legend>
          {offered.map((issue) => (
            <label
              key={issue.id}
              className={cn(
                "flex cursor-pointer items-center gap-3 rounded-lg border px-3 py-2 has-focus-visible:ring-3 has-focus-visible:ring-ring/30",
                isSelected(issue)
                  ? "border-primary bg-primary-soft"
                  : "border-input hover:bg-muted",
              )}
            >
              <input
                type={multiple ? "checkbox" : "radio"}
                name={name}
                checked={isSelected(issue)}
                onChange={() => toggle(issue)}
                className="size-4 shrink-0 accent-primary"
                aria-label={issue.reference}
              />
              <IssueSummary issue={issue} />
            </label>
          ))}
        </fieldset>
      ) : null}
    </div>
  );
}
