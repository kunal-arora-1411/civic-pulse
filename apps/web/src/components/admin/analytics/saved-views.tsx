"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BookmarkPlus, Star, Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { type FormEvent, useEffect, useId, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Dialog } from "@/components/ui/dialog";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { useToast } from "@/components/ui/toast";
import { useErrorMessage } from "@/hooks/use-error-message";
import {
  type AnalyticsFilters,
  fromSavedFilters,
  matchesSaved,
  toSavedFilters,
} from "@/lib/analytics/filters";
import {
  type AnalyticsView,
  createAnalyticsView,
  deleteAnalyticsView,
  isApiError,
  listAnalyticsViews,
  updateAnalyticsView,
} from "@/lib/api";

const VIEWS_KEY = ["analytics", "views"] as const;

/**
 * The caller's saved filter combinations (FR-077): pick one to apply it,
 * save what's on screen, mark one as the default the dashboard opens on.
 * Views are personal; the API only ever returns the caller's own.
 */
export function SavedViews({
  filters,
  onApply,
}: {
  filters: AnalyticsFilters;
  onApply: (filters: AnalyticsFilters, options?: { replace?: boolean }) => void;
}) {
  const t = useTranslations("admin.analytics.views");
  const { toast } = useToast();
  const errorMessage = useErrorMessage();
  const queryClient = useQueryClient();
  const [saving, setSaving] = useState(false);

  const views = useQuery({
    queryKey: VIEWS_KEY,
    queryFn: ({ signal }) => listAnalyticsViews(signal),
    staleTime: 5 * 60_000,
  });
  const items = views.data ?? [];
  const current = items.find((view) => matchesSaved(filters, view.filters));

  // Open on the default view, once, when the URL carries no filters.
  const appliedDefault = useRef(false);
  useEffect(() => {
    if (appliedDefault.current || !views.data) return;
    appliedDefault.current = true;
    const fallback = views.data.find((view) => view.is_default);
    if (fallback && window.location.search === "") {
      onApply(fromSavedFilters(fallback.filters), { replace: true });
    }
  }, [views.data, onApply]);

  const refresh = () => queryClient.invalidateQueries({ queryKey: VIEWS_KEY });
  const failed = (error: unknown) =>
    toast({
      title: t("failed"),
      description: errorMessage(error),
      variant: "error",
    });

  const makeDefault = useMutation({
    mutationFn: (view: AnalyticsView) =>
      updateAnalyticsView(view.id, { is_default: !view.is_default }),
    onSuccess: (view) => {
      toast({
        title: view.is_default
          ? t("defaultSet", { name: view.name })
          : t("defaultCleared", { name: view.name }),
        variant: "success",
      });
      return refresh();
    },
    onError: failed,
  });
  const remove = useMutation({
    mutationFn: (view: AnalyticsView) =>
      deleteAnalyticsView(view.id).then(() => view),
    onSuccess: (view) => {
      toast({ title: t("deleted", { name: view.name }), variant: "success" });
      return refresh();
    },
    onError: failed,
  });

  return (
    <div className="mb-3 flex flex-wrap items-end gap-2">
      <Field label={t("label")} className="w-full sm:w-64">
        {(control) => (
          <Select
            {...control}
            value={current?.id ?? ""}
            disabled={views.isPending || items.length === 0}
            onChange={(event) => {
              const view = items.find((v) => v.id === event.target.value);
              if (view) onApply(fromSavedFilters(view.filters));
            }}
          >
            <option value="">
              {items.length === 0 ? t("none") : t("choose")}
            </option>
            {items.map((view) => (
              <option key={view.id} value={view.id}>
                {view.is_default
                  ? t("defaultOption", { name: view.name })
                  : view.name}
              </option>
            ))}
          </Select>
        )}
      </Field>
      <Button variant="outline" onClick={() => setSaving(true)}>
        <BookmarkPlus aria-hidden="true" />
        {t("save")}
      </Button>
      {current ? (
        <>
          <Button
            variant="ghost"
            aria-pressed={current.is_default}
            disabled={makeDefault.isPending}
            onClick={() => makeDefault.mutate(current)}
          >
            <Star
              aria-hidden="true"
              className={current.is_default ? "fill-current" : undefined}
            />
            {current.is_default ? t("isDefault") : t("makeDefault")}
          </Button>
          <Button
            variant="ghost"
            disabled={remove.isPending}
            onClick={() => remove.mutate(current)}
          >
            <Trash2 aria-hidden="true" />
            {t("delete", { name: current.name })}
          </Button>
        </>
      ) : null}
      <SaveViewDialog
        open={saving}
        onOpenChange={setSaving}
        filters={filters}
        onSaved={(view) => {
          toast({ title: t("saved", { name: view.name }), variant: "success" });
          void refresh();
        }}
      />
    </div>
  );
}

function SaveViewDialog({
  open,
  onOpenChange,
  filters,
  onSaved,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  filters: AnalyticsFilters;
  onSaved: (view: AnalyticsView) => void;
}) {
  const t = useTranslations("admin.analytics.views");
  const tCommon = useTranslations("common");
  const errorMessage = useErrorMessage();
  const [name, setName] = useState("");
  const [isDefault, setIsDefault] = useState(false);
  const defaultId = useId();

  const save = useMutation({
    mutationFn: () =>
      createAnalyticsView({
        name: name.trim(),
        filters: toSavedFilters(filters),
        is_default: isDefault,
      }),
    onSuccess: (view) => {
      onSaved(view);
      setName("");
      setIsDefault(false);
      onOpenChange(false);
    },
  });
  const taken = isApiError(save.error, "name_taken");
  const empty = name.trim() === "";

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!empty) save.mutate();
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) save.reset();
        onOpenChange(next);
      }}
      title={t("dialogTitle")}
      description={t("dialogDescription")}
      closeLabel={tCommon("close")}
    >
      <form className="grid gap-4" onSubmit={submit}>
        <Field
          label={t("name")}
          required
          error={taken ? t("nameTaken") : undefined}
        >
          {(control) => (
            <Input
              {...control}
              value={name}
              maxLength={80}
              autoComplete="off"
              onChange={(event) => {
                setName(event.target.value);
                if (save.error) save.reset();
              }}
            />
          )}
        </Field>
        <div className="flex items-center gap-2 text-sm">
          <Checkbox
            id={defaultId}
            checked={isDefault}
            onChange={(event) => setIsDefault(event.target.checked)}
          />
          <label htmlFor={defaultId}>{t("openByDefault")}</label>
        </div>
        {save.error && !taken ? (
          <p role="alert" className="text-sm text-destructive">
            {errorMessage(save.error)}
          </p>
        ) : null}
        <div className="flex justify-end gap-2">
          <Button
            type="button"
            variant="ghost"
            onClick={() => onOpenChange(false)}
          >
            {t("cancel")}
          </Button>
          <Button type="submit" disabled={empty || save.isPending}>
            {t("saveSubmit")}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
