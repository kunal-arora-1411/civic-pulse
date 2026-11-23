"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useEffect, useId, useState } from "react";
import {
  CATEGORY_ICONS,
  type CategoryIconName,
  categoryIcon,
} from "@/components/issues/category-icon";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Dialog } from "@/components/ui/dialog";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { useToast } from "@/components/ui/toast";
import { useErrorMessage } from "@/hooks/use-error-message";
import {
  type Category,
  type CategoryInput,
  createCategory,
  isApiError,
  updateCategory,
} from "@/lib/api";
import {
  type DraftField,
  fromDraftFields,
  hasFieldErrors,
  toDraftFields,
  toI18n,
  validateFields,
} from "@/lib/categories/fields";
import { cn } from "@/lib/utils";
import { CategoryFieldsEditor } from "./category-fields-editor";

const CODE_PATTERN = /^[a-z][a-z0-9_]{1,39}$/;
const MAX_PHOTOS = 10;

type Form = {
  code: string;
  nameEn: string;
  nameHi: string;
  descriptionEn: string;
  descriptionHi: string;
  icon: CategoryIconName | "";
  minPhotos: string;
  maxPhotos: string;
  sortOrder: string;
  isActive: boolean;
  fields: DraftField[];
};

function toForm(category: Category | null, nextSortOrder: number): Form {
  return {
    code: category?.code ?? "",
    nameEn: category?.name_i18n.en ?? "",
    nameHi: category?.name_i18n.hi ?? "",
    descriptionEn: category?.description_i18n?.en ?? "",
    descriptionHi: category?.description_i18n?.hi ?? "",
    icon:
      category?.icon && category.icon in CATEGORY_ICONS
        ? (category.icon as CategoryIconName)
        : "",
    minPhotos: String(category?.evidence.min_photos ?? 1),
    maxPhotos: String(category?.evidence.max_photos ?? 5),
    sortOrder: String(category?.sort_order ?? nextSortOrder),
    isActive: category?.is_active ?? true,
    fields: toDraftFields(category?.fields ?? []),
  };
}

type FormErrors = Partial<
  Record<"code" | "nameEn" | "minPhotos" | "maxPhotos" | "sortOrder", string>
>;

function intIn(value: string, min: number, max: number): number | null {
  if (!/^\d+$/.test(value.trim())) return null;
  const number = Number(value);
  return number >= min && number <= max ? number : null;
}

export function CategoryDialog({
  open,
  category,
  nextSortOrder,
  onOpenChange,
}: {
  open: boolean;
  /** Null to create a new category. */
  category: Category | null;
  nextSortOrder: number;
  onOpenChange: (open: boolean) => void;
}) {
  const t = useTranslations("admin.categories");
  const errorMessage = useErrorMessage();
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const iconId = useId();
  const activeId = useId();
  const [form, setForm] = useState<Form>(() => toForm(category, nextSortOrder));
  const [attempted, setAttempted] = useState(false);

  useEffect(() => {
    if (!open) return;
    setForm(toForm(category, nextSortOrder));
    setAttempted(false);
  }, [open, category, nextSortOrder]);

  const set = <K extends keyof Form>(key: K, value: Form[K]) =>
    setForm((current) => ({ ...current, [key]: value }));

  const min = intIn(form.minPhotos, 0, MAX_PHOTOS);
  const max = intIn(form.maxPhotos, 1, MAX_PHOTOS);
  const errors: FormErrors = {};
  if (!category && !CODE_PATTERN.test(form.code.trim())) {
    errors.code = t("errors.code");
  }
  if (form.nameEn.trim().length < 2) errors.nameEn = t("errors.nameEn");
  if (min === null) errors.minPhotos = t("errors.photos", { max: MAX_PHOTOS });
  if (max === null) errors.maxPhotos = t("errors.photos", { max: MAX_PHOTOS });
  else if (min !== null && min > max) errors.maxPhotos = t("errors.photoRange");
  if (intIn(form.sortOrder, 0, 9999) === null) {
    errors.sortOrder = t("errors.sortOrder");
  }
  const fieldErrors = validateFields(form.fields);
  const invalid = Object.keys(errors).length > 0 || hasFieldErrors(fieldErrors);

  const mutation = useMutation({
    mutationFn: () => {
      const body: CategoryInput = {
        code: form.code.trim(),
        name_i18n: toI18n(form.nameEn, form.nameHi),
        description_i18n: toI18n(form.descriptionEn, form.descriptionHi),
        icon: form.icon || null,
        evidence: { min_photos: min ?? 0, max_photos: max ?? 1 },
        fields: fromDraftFields(form.fields),
        sort_order: Number(form.sortOrder),
        is_active: form.isActive,
      };
      if (category) {
        // The code is the category's identity in data and URLs; it isn't
        // editable once created.
        const { code: _code, ...changes } = body;
        return updateCategory(category.id, changes);
      }
      return createCategory(body);
    },
    onSuccess: (saved) => {
      queryClient.invalidateQueries({ queryKey: ["categories"] });
      toast({
        variant: "success",
        title: category
          ? t("updated", { name: saved.name_i18n.en ?? saved.code })
          : t("created", { name: saved.name_i18n.en ?? saved.code }),
      });
      onOpenChange(false);
    },
  });

  const submit = () => {
    setAttempted(true);
    if (invalid) return;
    mutation.mutate();
  };

  const show = (error: string | undefined) => (attempted ? error : undefined);
  const PreviewIcon = categoryIcon(form.icon || null);
  const conflict = isApiError(mutation.error, "conflict");

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={
        category
          ? t("editTitle", { name: category.name_i18n.en ?? category.code })
          : t("createTitle")
      }
      description={t("dialogDescription")}
      closeLabel={t("close")}
      className="max-w-3xl"
      footer={
        <>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t("cancel")}
          </Button>
          <Button onClick={submit} loading={mutation.isPending}>
            {category ? t("save") : t("create")}
          </Button>
        </>
      }
    >
      <div className="grid gap-6 pb-2">
        {attempted && invalid ? (
          <Alert variant="destructive" live="assertive">
            {t("errors.summary")}
          </Alert>
        ) : null}

        <div className="grid items-start gap-4 sm:grid-cols-2">
          <Field label={t("nameEn")} required error={show(errors.nameEn)}>
            {(control) => (
              <Input
                {...control}
                value={form.nameEn}
                onChange={(event) => set("nameEn", event.target.value)}
              />
            )}
          </Field>
          <Field label={t("nameHi")}>
            {(control) => (
              <Input
                {...control}
                lang="hi"
                value={form.nameHi}
                onChange={(event) => set("nameHi", event.target.value)}
              />
            )}
          </Field>
          <Field
            label={t("code")}
            description={category ? t("codeLocked") : t("codeHelp")}
            required={!category}
            error={conflict ? t("errors.codeTaken") : show(errors.code)}
          >
            {(control) => (
              <Input
                {...control}
                value={form.code}
                readOnly={Boolean(category)}
                onChange={(event) => set("code", event.target.value)}
                className={cn(
                  "font-mono text-sm",
                  category && "bg-muted text-muted-foreground",
                )}
                autoCapitalize="off"
                spellCheck={false}
              />
            )}
          </Field>
          <div className="grid gap-1.5">
            <Label htmlFor={iconId}>{t("icon")}</Label>
            <div className="flex items-center gap-2">
              <span className="grid size-10 shrink-0 place-items-center rounded-lg bg-primary-soft text-primary-soft-foreground">
                <PreviewIcon aria-hidden="true" className="size-5" />
              </span>
              <Select
                id={iconId}
                className="flex-1"
                value={form.icon}
                onChange={(event) =>
                  set("icon", event.target.value as CategoryIconName | "")
                }
              >
                <option value="">{t("noIcon")}</option>
                {(Object.keys(CATEGORY_ICONS) as CategoryIconName[]).map(
                  (name) => (
                    <option key={name} value={name}>
                      {t(`icons.${name}`)}
                    </option>
                  ),
                )}
              </Select>
            </div>
          </div>
          <Field label={t("descriptionEn")}>
            {(control) => (
              <Input
                {...control}
                value={form.descriptionEn}
                onChange={(event) => set("descriptionEn", event.target.value)}
              />
            )}
          </Field>
          <Field label={t("descriptionHi")}>
            {(control) => (
              <Input
                {...control}
                lang="hi"
                value={form.descriptionHi}
                onChange={(event) => set("descriptionHi", event.target.value)}
              />
            )}
          </Field>
        </div>

        <fieldset className="grid gap-3">
          <legend className="mb-1 font-semibold">{t("evidence")}</legend>
          <div className="grid items-start gap-4 sm:grid-cols-3">
            <Field
              label={t("minPhotos")}
              required
              error={show(errors.minPhotos)}
            >
              {(control) => (
                <Input
                  {...control}
                  type="number"
                  inputMode="numeric"
                  min={0}
                  max={MAX_PHOTOS}
                  value={form.minPhotos}
                  onChange={(event) => set("minPhotos", event.target.value)}
                />
              )}
            </Field>
            <Field
              label={t("maxPhotos")}
              required
              error={show(errors.maxPhotos)}
            >
              {(control) => (
                <Input
                  {...control}
                  type="number"
                  inputMode="numeric"
                  min={1}
                  max={MAX_PHOTOS}
                  value={form.maxPhotos}
                  onChange={(event) => set("maxPhotos", event.target.value)}
                />
              )}
            </Field>
            <Field
              label={t("sortOrder")}
              description={t("sortOrderHelp")}
              required
              error={show(errors.sortOrder)}
            >
              {(control) => (
                <Input
                  {...control}
                  type="number"
                  inputMode="numeric"
                  min={0}
                  value={form.sortOrder}
                  onChange={(event) => set("sortOrder", event.target.value)}
                />
              )}
            </Field>
          </div>
        </fieldset>

        <CategoryFieldsEditor
          value={form.fields}
          onChange={(fields) => set("fields", fields)}
          errors={attempted ? fieldErrors : null}
        />

        {!category ? (
          <div className="flex items-center gap-2">
            <Checkbox
              id={activeId}
              checked={form.isActive}
              onChange={(event) => set("isActive", event.target.checked)}
            />
            <Label htmlFor={activeId}>{t("activeOnCreate")}</Label>
          </div>
        ) : null}

        {mutation.isError && !conflict ? (
          <Alert variant="destructive" live="assertive">
            {errorMessage(mutation.error)}
          </Alert>
        ) : null}
      </div>
    </Dialog>
  );
}
