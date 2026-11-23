"use client";

import { Plus, Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";
import {
  type Control,
  type FieldErrors,
  type UseFormRegister,
  useFieldArray,
} from "react-hook-form";
import { z } from "zod";
import { Button } from "@/components/ui/button";
import { Field } from "@/components/ui/field";
import { Select } from "@/components/ui/select";
import {
  type CurrentUser,
  ROLES,
  type Role,
  type RoleAssignment,
  type RoleAssignmentInput,
} from "@/lib/api";
import { hasRole } from "@/lib/auth/access";
import { useScopes } from "./use-scopes";

export type RoleRow = {
  role: string;
  department_id: string;
  jurisdiction_id: string;
};

export type RoleRowsForm = { roles: RoleRow[] };

export function roleRowsSchema(messages: {
  roleRequired: string;
  rolesRequired: string;
  duplicate: string;
}) {
  return z
    .array(
      z.object({
        role: z.string().min(1, messages.roleRequired),
        department_id: z.string(),
        jurisdiction_id: z.string(),
      }),
    )
    .min(1, messages.rolesRequired)
    .refine(
      (rows) =>
        new Set(
          rows.map((r) => `${r.role}|${r.department_id}|${r.jurisdiction_id}`),
        ).size === rows.length,
      messages.duplicate,
    );
}

export const emptyRoleRow: RoleRow = {
  role: "",
  department_id: "",
  jurisdiction_id: "",
};

export function toRoleRows(assignments: RoleAssignment[]): RoleRow[] {
  return assignments.map((a) => ({
    role: a.role,
    department_id: a.department_id ?? "",
    jurisdiction_id: a.jurisdiction_id ?? "",
  }));
}

export function toRoleInputs(rows: RoleRow[]): RoleAssignmentInput[] {
  return rows.map((row) => ({
    role: row.role as Role,
    department_id: row.department_id || null,
    jurisdiction_id: row.jurisdiction_id || null,
  }));
}

/**
 * Roles the current admin may hand out. Only a platform admin can grant
 * platform_admin; the API enforces this too.
 */
export function assignableRoles(
  actor: CurrentUser | null,
  options: { staffOnly: boolean },
): Role[] {
  return ROLES.filter((role) => {
    if (role === "platform_admin" && !hasRole(actor, "platform_admin")) {
      return false;
    }
    if (options.staffOnly) {
      return role !== "citizen" && role !== "community_contributor";
    }
    return true;
  });
}

export function RoleFields<T extends RoleRowsForm>({
  control,
  register,
  errors,
  roles,
}: {
  control: Control<T>;
  register: UseFormRegister<T>;
  errors: FieldErrors<T>;
  roles: Role[];
}) {
  const t = useTranslations("admin.users");
  const tRoles = useTranslations("roles");
  const scopes = useScopes();
  // The generic form type can't be narrowed for react-hook-form's path
  // helpers, so work against the shared shape.
  const typedControl = control as unknown as Control<RoleRowsForm>;
  const typedRegister = register as unknown as UseFormRegister<RoleRowsForm>;
  const typedErrors = errors as FieldErrors<RoleRowsForm>;
  const { fields, append, remove } = useFieldArray({
    control: typedControl,
    name: "roles",
  });

  const listError =
    typedErrors.roles?.root?.message ?? typedErrors.roles?.message;

  return (
    <fieldset className="grid gap-3">
      <legend className="mb-1 text-sm font-semibold">{t("rolesLegend")}</legend>
      <p className="-mt-1 text-sm text-muted-foreground">
        {scopes.enabled ? t("rolesHint") : t("rolesHintNoScopes")}
      </p>

      <ol className="grid gap-3">
        {fields.map((field, index) => (
          <li
            key={field.id}
            className="grid gap-3 rounded-lg border border-border bg-muted/40 p-3 sm:grid-cols-[1fr_1fr_1fr_auto] sm:items-end"
          >
            <Field
              label={t("roleLabel", { number: index + 1 })}
              error={typedErrors.roles?.[index]?.role?.message}
              required
            >
              {(controlProps) => (
                <Select
                  {...controlProps}
                  {...typedRegister(`roles.${index}.role`)}
                >
                  <option value="">{t("chooseRole")}</option>
                  {roles.map((role) => (
                    <option key={role} value={role}>
                      {tRoles(role)}
                    </option>
                  ))}
                </Select>
              )}
            </Field>
            <Field label={t("departmentLabel")}>
              {(controlProps) => (
                <Select
                  {...controlProps}
                  {...typedRegister(`roles.${index}.department_id`)}
                  disabled={!scopes.enabled}
                >
                  <option value="">{t("allDepartments")}</option>
                  {scopes.departments.map((department) => (
                    <option key={department.id} value={department.id}>
                      {department.name}
                    </option>
                  ))}
                </Select>
              )}
            </Field>
            <Field label={t("wardLabel")}>
              {(controlProps) => (
                <Select
                  {...controlProps}
                  {...typedRegister(`roles.${index}.jurisdiction_id`)}
                  disabled={!scopes.enabled}
                >
                  <option value="">{t("allWards")}</option>
                  {scopes.wards.map((ward) => (
                    <option key={ward.id} value={ward.id}>
                      {ward.name}
                    </option>
                  ))}
                </Select>
              )}
            </Field>
            <Button
              variant="ghost"
              size="icon"
              disabled={fields.length === 1}
              aria-label={t("removeRole", { number: index + 1 })}
              onClick={() => remove(index)}
              className="justify-self-end"
            >
              <Trash2 aria-hidden="true" />
            </Button>
          </li>
        ))}
      </ol>

      {listError ? (
        <p
          role="alert"
          className="text-sm font-medium text-destructive-soft-foreground"
        >
          {listError}
        </p>
      ) : null}

      <Button
        variant="outline"
        size="sm"
        className="justify-self-start"
        onClick={() => append({ ...emptyRoleRow })}
      >
        <Plus aria-hidden="true" />
        {t("addRole")}
      </Button>
    </fieldset>
  );
}
