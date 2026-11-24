"use client";

import { CircleAlert } from "lucide-react";
import { useTranslations } from "next-intl";
import { useFilterCategories } from "@/components/admin/issues/issue-filters";
import { PageHeader } from "@/components/admin/page-header";
import { CategoryIcon } from "@/components/issues/category-icon";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useLocalized } from "@/hooks/use-reference-data";
import { getSlaTargets, updateSlaTargets } from "@/lib/api";
import {
  fromSlaDoc,
  fromSlaForm,
  MAX_HOURS,
  SLA_COLUMNS,
  type SlaColumn,
  type SlaDoc,
  toSlaDoc,
  validateSla,
} from "@/lib/settings/sla";
import {
  SettingsFrame,
  SettingsSection,
  useSettingsForm,
} from "./settings-form";

const NO_TARGETS: SlaDoc = {};

async function load(signal: AbortSignal): Promise<SlaDoc> {
  return toSlaDoc(await getSlaTargets(signal));
}

async function save(doc: SlaDoc): Promise<SlaDoc> {
  return toSlaDoc(await updateSlaTargets(fromSlaDoc(doc)));
}

/**
 * Resolution targets per category and priority band, and when a breach
 * escalates from the department's supervisors to the municipal admins
 * (FR-056, FR-081). One row per category; a blank band uses the "All
 * bands" target, and a category with no target has no deadline.
 */
export function SlaSettings() {
  const t = useTranslations("admin.settings.sla");
  const tErr = useTranslations("admin.settings.errors");
  const tBand = useTranslations("priority.band");
  const localized = useLocalized();
  const categories = useFilterCategories();
  const form = useSettingsForm({
    queryKey: ["admin", "sla-targets"],
    load,
    save,
    validate: validateSla,
    fromValues: fromSlaForm,
    defaults: NO_TARGETS,
  });

  const heading = (column: SlaColumn) =>
    column === "any"
      ? t("allBands")
      : column === "escalate"
        ? t("escalateAfter")
        : tBand(column);
  const rows = categories.data ?? [];
  const problems = rows.flatMap((category) =>
    SLA_COLUMNS.filter((column) => form.errors[`${category.id}.${column}`]).map(
      (column) => ({
        path: `${category.id}.${column}`,
        text: `${localized(category.name_i18n)}, ${heading(column)}: ${tErr(
          form.errors[`${category.id}.${column}`] as "hoursRange",
          { max: MAX_HOURS },
        )}`,
      }),
    ),
  );

  return (
    <div className="motion-safe:animate-rise">
      <PageHeader title={t("title")} description={t("description")} />
      <SettingsFrame form={form} savedMessage={t("saved")}>
        <SettingsSection
          title={t("targetsTitle")}
          description={t("targetsIntro")}
        >
          <Table label={t("tableLabel")}>
            <TableHeader>
              <TableRow>
                <TableHead scope="col">{t("category")}</TableHead>
                {SLA_COLUMNS.map((column) => (
                  <TableHead
                    key={column}
                    scope="col"
                    className="whitespace-nowrap"
                  >
                    {heading(column)}
                  </TableHead>
                ))}
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((category) => {
                const name = localized(category.name_i18n);
                return (
                  <TableRow key={category.id}>
                    <TableHead scope="row" className="font-medium">
                      <span className="flex items-center gap-2 whitespace-nowrap">
                        <CategoryIcon
                          icon={category.icon}
                          className="size-4 text-muted-foreground"
                        />
                        {name}
                      </span>
                    </TableHead>
                    {SLA_COLUMNS.map((column) => {
                      const path = `${category.id}.${column}`;
                      return (
                        <TableCell key={column}>
                          <Input
                            type="number"
                            inputMode="numeric"
                            min={1}
                            max={MAX_HOURS}
                            step={1}
                            aria-label={t("cellLabel", {
                              category: name,
                              column: heading(column),
                            })}
                            placeholder={
                              column !== "any" && column !== "escalate"
                                ? (form.values?.[`${category.id}.any`] ?? "")
                                : ""
                            }
                            value={form.values?.[path] ?? ""}
                            onChange={(event) =>
                              form.setValue(path, event.target.value)
                            }
                            disabled={!form.canManage}
                            aria-invalid={form.errors[path] ? true : undefined}
                            className="w-24 tabular-nums"
                          />
                        </TableCell>
                      );
                    })}
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
          <p className="text-sm text-muted-foreground">{t("hoursNote")}</p>
          {problems.length > 0 ? (
            <ul className="grid gap-1">
              {problems.map((problem) => (
                <li
                  key={problem.path}
                  className="flex items-start gap-1.5 text-sm font-medium text-destructive-soft-foreground"
                >
                  <CircleAlert
                    aria-hidden="true"
                    className="mt-0.5 size-4 shrink-0"
                  />
                  {problem.text}
                </li>
              ))}
            </ul>
          ) : null}
        </SettingsSection>
        <SettingsSection title={t("escalationTitle")}>
          <ol className="grid list-decimal gap-1 ps-5 text-sm">
            <li>{t("escalationStep1")}</li>
            <li>{t("escalationStep2")}</li>
          </ol>
        </SettingsSection>
      </SettingsFrame>
    </div>
  );
}
