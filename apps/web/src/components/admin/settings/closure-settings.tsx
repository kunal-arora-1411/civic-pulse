"use client";

import { useTranslations } from "next-intl";
import { PageHeader } from "@/components/admin/page-header";
import { getClosureConfig, updateClosureConfig } from "@/lib/api";
import {
  CLOSURE_CONFIRMATIONS_MAX,
  CLOSURE_WINDOW_MAX_HOURS,
  DEFAULT_CLOSURE_CONFIG,
  fromClosureForm,
  validateClosure,
} from "@/lib/settings/config";
import {
  NumberField,
  SettingsFrame,
  SettingsSection,
  useSettingsForm,
} from "./settings-form";

/**
 * How long a resolved issue stays open for citizens to dispute, and how
 * many reporters must confirm a fix in categories that don't need a
 * supervisor's approval (Phase 3 §6).
 */
export function ClosureSettings() {
  const t = useTranslations("admin.settings.closure");
  const tErr = useTranslations("admin.settings.errors");
  const form = useSettingsForm({
    queryKey: ["admin", "closure-config"],
    load: getClosureConfig,
    save: updateClosureConfig,
    validate: validateClosure,
    fromValues: fromClosureForm,
    defaults: DEFAULT_CLOSURE_CONFIG,
  });
  const error = (path: string) => {
    const key = form.errors[path];
    if (!key) return undefined;
    if (key === "hoursRange")
      return tErr("hoursRange", { max: CLOSURE_WINDOW_MAX_HOURS });
    if (key === "confirmationsRange")
      return tErr("confirmationsRange", { max: CLOSURE_CONFIRMATIONS_MAX });
    return tErr(key as "number");
  };
  const d = DEFAULT_CLOSURE_CONFIG;

  return (
    <div className="motion-safe:animate-rise">
      <PageHeader
        section="closure"
        title={t("title")}
        description={t("description")}
      />
      <SettingsFrame form={form} savedMessage={t("saved")}>
        <SettingsSection title={t("sectionTitle")}>
          <div className="grid gap-5 sm:grid-cols-2">
            <NumberField
              form={form}
              path="resolution_window_hours"
              label={t("window")}
              help={t("windowHelp")}
              suffix={t("hours")}
              step="1"
              defaultValue={d.resolution_window_hours}
              errorText={error("resolution_window_hours")}
            />
            <NumberField
              form={form}
              path="confirmations_required"
              label={t("confirmations")}
              help={t("confirmationsHelp")}
              step="1"
              defaultValue={d.confirmations_required}
              errorText={error("confirmations_required")}
            />
          </div>
        </SettingsSection>
      </SettingsFrame>
    </div>
  );
}
