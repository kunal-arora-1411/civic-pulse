"use client";

import { ArrowDown, ArrowUp, Plus, Trash2, X } from "lucide-react";
import { useTranslations } from "next-intl";
import { useId } from "react";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { CATEGORY_FIELD_TYPES, type CategoryFieldType } from "@/lib/api";
import {
  type DraftField,
  type DraftOption,
  type FieldError,
  type FieldErrors,
  MAX_FIELDS,
  MAX_OPTIONS,
  moveItem,
  newField,
  newOption,
  slugifyKey,
} from "@/lib/categories/fields";

function OptionRow({
  option,
  number,
  fieldNumber,
  errors,
  onChange,
  onRemove,
}: {
  option: DraftOption;
  number: number;
  fieldNumber: number;
  errors: FieldError[] | undefined;
  onChange: (option: DraftOption) => void;
  onRemove: () => void;
}) {
  const t = useTranslations("admin.categories.fields");
  const has = (error: FieldError) => errors?.includes(error);
  return (
    <li className="grid gap-2 rounded-lg border border-border p-3 sm:grid-cols-[1fr_1fr_1fr_auto] sm:items-start">
      <Field
        label={t("optionValue")}
        required
        error={
          has("option_value_required")
            ? t("errors.option_value_required")
            : has("option_value_duplicate")
              ? t("errors.option_value_duplicate")
              : undefined
        }
      >
        {(control) => (
          <Input
            {...control}
            value={option.value}
            onChange={(event) =>
              onChange({ ...option, value: event.target.value })
            }
            className="font-mono text-sm"
          />
        )}
      </Field>
      <Field
        label={t("optionLabelEn")}
        required
        error={
          has("option_label_required")
            ? t("errors.option_label_required")
            : undefined
        }
      >
        {(control) => (
          <Input
            {...control}
            value={option.en}
            onChange={(event) => {
              const en = event.target.value;
              const autoValue =
                !option.value || option.value === slugifyKey(option.en);
              onChange({
                ...option,
                en,
                value: autoValue ? slugifyKey(en) : option.value,
              });
            }}
          />
        )}
      </Field>
      <Field label={t("optionLabelHi")}>
        {(control) => (
          <Input
            {...control}
            lang="hi"
            value={option.hi}
            onChange={(event) =>
              onChange({ ...option, hi: event.target.value })
            }
          />
        )}
      </Field>
      <Button
        variant="ghost"
        size="icon-sm"
        className="sm:mt-6"
        onClick={onRemove}
        aria-label={t("removeOption", { number, field: fieldNumber })}
      >
        <X aria-hidden="true" />
      </Button>
    </li>
  );
}

function FieldCard({
  field,
  number,
  total,
  errors,
  onChange,
  onMove,
  onRemove,
}: {
  field: DraftField;
  number: number;
  total: number;
  errors: FieldErrors[string] | undefined;
  onChange: (field: DraftField) => void;
  onMove: (delta: -1 | 1) => void;
  onRemove: () => void;
}) {
  const t = useTranslations("admin.categories.fields");
  const legendId = useId();
  const has = (error: FieldError) => errors?.field.includes(error);
  const keyError = has("key_required")
    ? t("errors.key_required")
    : has("key_format")
      ? t("errors.key_format")
      : has("key_duplicate")
        ? t("errors.key_duplicate")
        : undefined;

  return (
    <li>
      <fieldset
        aria-labelledby={legendId}
        className="grid gap-4 rounded-xl border border-border bg-muted/30 p-4"
      >
        <div className="flex items-center justify-between gap-2">
          <h4 id={legendId} className="font-semibold">
            {t("fieldNumber", { number })}
            {field.en.trim() ? (
              <span className="font-normal text-muted-foreground">
                {" "}
                · {field.en.trim()}
              </span>
            ) : null}
          </h4>
          <div className="flex gap-1">
            <Button
              variant="ghost"
              size="icon-sm"
              disabled={number === 1}
              onClick={() => onMove(-1)}
              aria-label={t("moveUp", { number })}
            >
              <ArrowUp aria-hidden="true" />
            </Button>
            <Button
              variant="ghost"
              size="icon-sm"
              disabled={number === total}
              onClick={() => onMove(1)}
              aria-label={t("moveDown", { number })}
            >
              <ArrowDown aria-hidden="true" />
            </Button>
            <Button
              variant="ghost"
              size="icon-sm"
              onClick={onRemove}
              aria-label={t("removeField", { number })}
              className="text-destructive-soft-foreground"
            >
              <Trash2 aria-hidden="true" />
            </Button>
          </div>
        </div>

        <div className="grid gap-3 sm:grid-cols-2">
          <Field
            label={t("labelEn")}
            required
            error={
              has("label_required") ? t("errors.label_required") : undefined
            }
          >
            {(control) => (
              <Input
                {...control}
                value={field.en}
                onChange={(event) => {
                  const en = event.target.value;
                  // Suggest a key from the label until someone edits it.
                  const autoKey =
                    !field.key || field.key === slugifyKey(field.en);
                  onChange({
                    ...field,
                    en,
                    key: autoKey ? slugifyKey(en) : field.key,
                  });
                }}
              />
            )}
          </Field>
          <Field label={t("labelHi")}>
            {(control) => (
              <Input
                {...control}
                lang="hi"
                value={field.hi}
                onChange={(event) =>
                  onChange({ ...field, hi: event.target.value })
                }
              />
            )}
          </Field>
          <Field
            label={t("key")}
            description={t("keyHelp")}
            required
            error={keyError}
          >
            {(control) => (
              <Input
                {...control}
                value={field.key}
                onChange={(event) =>
                  onChange({ ...field, key: event.target.value })
                }
                className="font-mono text-sm"
                autoCapitalize="off"
                spellCheck={false}
              />
            )}
          </Field>
          <Field label={t("type")}>
            {(control) => (
              <Select
                {...control}
                value={field.type}
                onChange={(event) => {
                  const type = event.target.value as CategoryFieldType;
                  onChange({
                    ...field,
                    type,
                    options:
                      type === "select" && field.options.length === 0
                        ? [newOption()]
                        : field.options,
                  });
                }}
              >
                {CATEGORY_FIELD_TYPES.map((type) => (
                  <option key={type} value={type}>
                    {t(`types.${type}`)}
                  </option>
                ))}
              </Select>
            )}
          </Field>
        </div>

        <div className="flex w-fit items-center gap-2">
          <Checkbox
            id={`${legendId}-required`}
            checked={field.required}
            onChange={(event) =>
              onChange({ ...field, required: event.target.checked })
            }
          />
          <Label htmlFor={`${legendId}-required`}>{t("required")}</Label>
        </div>

        {field.type === "select" ? (
          <div className="grid gap-2">
            <p className="text-sm font-semibold">{t("options")}</p>
            {has("options_required") ? (
              <p className="text-sm font-medium text-destructive-soft-foreground">
                {t("errors.options_required")}
              </p>
            ) : null}
            <ul className="grid gap-2">
              {field.options.map((option, index) => (
                <OptionRow
                  key={option.id}
                  option={option}
                  number={index + 1}
                  fieldNumber={number}
                  errors={errors?.options[option.id]}
                  onChange={(next) =>
                    onChange({
                      ...field,
                      options: field.options.map((item) =>
                        item.id === option.id ? next : item,
                      ),
                    })
                  }
                  onRemove={() =>
                    onChange({
                      ...field,
                      options: field.options.filter(
                        (item) => item.id !== option.id,
                      ),
                    })
                  }
                />
              ))}
            </ul>
            <Button
              variant="outline"
              size="sm"
              className="justify-self-start"
              disabled={field.options.length >= MAX_OPTIONS}
              onClick={() =>
                onChange({ ...field, options: [...field.options, newOption()] })
              }
            >
              <Plus aria-hidden="true" />
              {t("addOption")}
            </Button>
          </div>
        ) : null}
      </fieldset>
    </li>
  );
}

/**
 * Editor for the extra questions a category asks on the report form.
 * Plain form controls, one fieldset per question, and buttons (not drag
 * and drop) to reorder, so it works with a keyboard and a screen reader.
 */
export function CategoryFieldsEditor({
  value,
  onChange,
  errors,
}: {
  value: DraftField[];
  onChange: (fields: DraftField[]) => void;
  /** Shown after a submit attempt. */
  errors: FieldErrors | null;
}) {
  const t = useTranslations("admin.categories.fields");
  return (
    <section className="grid gap-3" aria-labelledby="category-fields-heading">
      <div className="grid gap-1">
        <h3 id="category-fields-heading" className="font-semibold">
          {t("title")}
        </h3>
        <p className="text-sm text-muted-foreground">{t("description")}</p>
      </div>
      {value.length === 0 ? (
        <p className="rounded-lg border border-dashed border-border px-4 py-6 text-center text-sm text-muted-foreground">
          {t("empty")}
        </p>
      ) : (
        <ol className="grid gap-3">
          {value.map((field, index) => (
            <FieldCard
              key={field.id}
              field={field}
              number={index + 1}
              total={value.length}
              errors={errors?.[field.id]}
              onChange={(next) =>
                onChange(
                  value.map((item) => (item.id === field.id ? next : item)),
                )
              }
              onMove={(delta) =>
                onChange(moveItem(value, index, index + delta))
              }
              onRemove={() =>
                onChange(value.filter((item) => item.id !== field.id))
              }
            />
          ))}
        </ol>
      )}
      <Button
        variant="outline"
        className="justify-self-start"
        disabled={value.length >= MAX_FIELDS}
        onClick={() => onChange([...value, newField()])}
      >
        <Plus aria-hidden="true" />
        {t("addField")}
      </Button>
    </section>
  );
}
