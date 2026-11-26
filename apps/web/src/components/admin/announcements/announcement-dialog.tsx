"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { type FormEvent, useEffect, useState } from "react";
import {
  useFilterCategories,
  useWards,
} from "@/components/admin/issues/issue-filters";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Field } from "@/components/ui/field";
import { Input, inputClasses } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { useToast } from "@/components/ui/toast";
import { useErrorMessage } from "@/hooks/use-error-message";
import { useLocalized } from "@/hooks/use-reference-data";
import {
  isoToIstInput,
  istInputFromNow,
  istInputToIso,
} from "@/lib/announcements";
import {
  ANNOUNCEMENT_KINDS,
  type Announcement,
  type AnnouncementInput,
  type AnnouncementKind,
  createAnnouncement,
  updateAnnouncement,
} from "@/lib/api";
import { cn } from "@/lib/utils";

const TITLE_MAX = 200;
const BODY_MAX = 2000;

type Draft = {
  kind: AnnouncementKind;
  titleEn: string;
  titleHi: string;
  bodyEn: string;
  bodyHi: string;
  ward: string;
  category: string;
  startsAt: string;
  endsAt: string;
};

function draftOf(announcement: Announcement | null): Draft {
  if (!announcement) {
    return {
      kind: "planned_works",
      titleEn: "",
      titleHi: "",
      bodyEn: "",
      bodyHi: "",
      ward: "",
      category: "",
      startsAt: istInputFromNow(0),
      endsAt: istInputFromNow(24),
    };
  }
  return {
    kind: announcement.kind,
    titleEn: announcement.title_i18n.en ?? "",
    titleHi: announcement.title_i18n.hi ?? "",
    bodyEn: announcement.body_i18n.en ?? "",
    bodyHi: announcement.body_i18n.hi ?? "",
    ward: announcement.ward?.id ?? "",
    category: announcement.category?.id ?? "",
    startsAt: isoToIstInput(announcement.starts_at),
    endsAt: isoToIstInput(announcement.ends_at),
  };
}

function i18n(en: string, hi: string): Record<string, string> {
  return hi.trim() ? { en: en.trim(), hi: hi.trim() } : { en: en.trim() };
}

/** Create or edit an announcement. Times are entered in IST. */
export function AnnouncementDialog({
  open,
  announcement,
  onOpenChange,
}: {
  open: boolean;
  /** null: a new announcement. */
  announcement: Announcement | null;
  onOpenChange: (open: boolean) => void;
}) {
  const t = useTranslations("admin.announcements");
  const tKind = useTranslations("announcementKind");
  const errorMessage = useErrorMessage();
  const localized = useLocalized();
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const wards = useWards();
  const categories = useFilterCategories();
  const [draft, setDraft] = useState<Draft>(() => draftOf(announcement));
  const [submitted, setSubmitted] = useState(false);

  useEffect(() => {
    if (open) {
      setDraft(draftOf(announcement));
      setSubmitted(false);
    }
  }, [open, announcement]);

  const set = (changes: Partial<Draft>) =>
    setDraft((current) => ({ ...current, ...changes }));

  const startsAt = istInputToIso(draft.startsAt);
  const endsAt = istInputToIso(draft.endsAt);
  const errors = {
    titleEn: draft.titleEn.trim() ? undefined : t("errors.titleRequired"),
    bodyEn: draft.bodyEn.trim() ? undefined : t("errors.bodyRequired"),
    startsAt: startsAt ? undefined : t("errors.timeRequired"),
    endsAt: !endsAt
      ? t("errors.timeRequired")
      : startsAt && endsAt <= startsAt
        ? t("errors.endBeforeStart")
        : undefined,
  };
  const valid = Object.values(errors).every((e) => e === undefined);

  const mutation = useMutation({
    mutationFn: () => {
      const body: AnnouncementInput = {
        kind: draft.kind,
        title_i18n: i18n(draft.titleEn, draft.titleHi),
        body_i18n: i18n(draft.bodyEn, draft.bodyHi),
        ward_id: draft.ward || null,
        category_id: draft.category || null,
        starts_at: startsAt as string,
        ends_at: endsAt as string,
      };
      return announcement
        ? updateAnnouncement(announcement.id, body)
        : createAnnouncement(body);
    },
    onSuccess: (saved) => {
      queryClient.invalidateQueries({ queryKey: ["announcements"] });
      toast({
        variant: "success",
        title: announcement
          ? t("updated", { title: saved.title_i18n.en ?? "" })
          : t("created", { title: saved.title_i18n.en ?? "" }),
      });
      onOpenChange(false);
    },
  });

  const shown = (error: string | undefined) => (submitted ? error : undefined);
  const submit = (event: FormEvent) => {
    event.preventDefault();
    setSubmitted(true);
    if (valid) mutation.mutate();
  };
  const textarea = cn(inputClasses, "h-auto py-2");

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) mutation.reset();
        onOpenChange(next);
      }}
      title={announcement ? t("editTitle") : t("createTitle")}
      description={t("dialogDescription")}
      closeLabel={t("close")}
      className="sm:max-w-2xl"
    >
      <form className="grid gap-4" onSubmit={submit} noValidate>
        <div className="grid gap-4 sm:grid-cols-3">
          <Field label={t("kind")}>
            {(control) => (
              <Select
                {...control}
                value={draft.kind}
                onChange={(event) =>
                  set({ kind: event.target.value as AnnouncementKind })
                }
              >
                {ANNOUNCEMENT_KINDS.map((kind) => (
                  <option key={kind} value={kind}>
                    {tKind(kind)}
                  </option>
                ))}
              </Select>
            )}
          </Field>
          <Field label={t("ward")}>
            {(control) => (
              <Select
                {...control}
                value={draft.ward}
                onChange={(event) => set({ ward: event.target.value })}
              >
                <option value="">{t("wholeCity")}</option>
                {(wards.data ?? []).map((ward) => (
                  <option key={ward.id} value={ward.id}>
                    {ward.name}
                  </option>
                ))}
              </Select>
            )}
          </Field>
          <Field label={t("category")}>
            {(control) => (
              <Select
                {...control}
                value={draft.category}
                onChange={(event) => set({ category: event.target.value })}
              >
                <option value="">{t("allCategories")}</option>
                {(categories.data ?? []).map((category) => (
                  <option key={category.id} value={category.id}>
                    {localized(category.name_i18n)}
                  </option>
                ))}
              </Select>
            )}
          </Field>
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label={t("titleEn")} required error={shown(errors.titleEn)}>
            {(control) => (
              <Input
                {...control}
                lang="en"
                value={draft.titleEn}
                maxLength={TITLE_MAX}
                onChange={(event) => set({ titleEn: event.target.value })}
              />
            )}
          </Field>
          <Field label={t("titleHi")} description={t("optional")}>
            {(control) => (
              <Input
                {...control}
                lang="hi"
                value={draft.titleHi}
                maxLength={TITLE_MAX}
                onChange={(event) => set({ titleHi: event.target.value })}
              />
            )}
          </Field>
          <Field label={t("bodyEn")} required error={shown(errors.bodyEn)}>
            {(control) => (
              <textarea
                {...control}
                lang="en"
                rows={4}
                value={draft.bodyEn}
                maxLength={BODY_MAX}
                onChange={(event) => set({ bodyEn: event.target.value })}
                className={textarea}
              />
            )}
          </Field>
          <Field label={t("bodyHi")} description={t("optional")}>
            {(control) => (
              <textarea
                {...control}
                lang="hi"
                rows={4}
                value={draft.bodyHi}
                maxLength={BODY_MAX}
                onChange={(event) => set({ bodyHi: event.target.value })}
                className={textarea}
              />
            )}
          </Field>
          <Field
            label={t("startsAt")}
            description={t("timesInIst")}
            required
            error={shown(errors.startsAt)}
          >
            {(control) => (
              <Input
                {...control}
                type="datetime-local"
                value={draft.startsAt}
                onChange={(event) => set({ startsAt: event.target.value })}
              />
            )}
          </Field>
          <Field
            label={t("endsAt")}
            description={t("timesInIst")}
            required
            error={shown(errors.endsAt)}
          >
            {(control) => (
              <Input
                {...control}
                type="datetime-local"
                value={draft.endsAt}
                min={draft.startsAt || undefined}
                onChange={(event) => set({ endsAt: event.target.value })}
              />
            )}
          </Field>
        </div>
        {mutation.isError ? (
          <Alert variant="destructive" live="assertive">
            {errorMessage(mutation.error)}
          </Alert>
        ) : null}
        <div className="flex justify-end gap-2">
          <Button
            type="button"
            variant="outline"
            onClick={() => onOpenChange(false)}
          >
            {t("cancel")}
          </Button>
          <Button type="submit" loading={mutation.isPending}>
            {announcement ? t("saveChanges") : t("publish")}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
