"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Pencil, Plus } from "lucide-react";
import { useTranslations } from "next-intl";
import { useEffect, useId, useMemo, useState } from "react";
import { PageHeader } from "@/components/admin/page-header";
import { PageLoading } from "@/components/page-loading";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Dialog } from "@/components/ui/dialog";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { MultiSelect } from "@/components/ui/multi-select";
import { Select } from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useToast } from "@/components/ui/toast";
import { useErrorMessage } from "@/hooks/use-error-message";
import { useLocalized } from "@/hooks/use-reference-data";
import {
  createTeam,
  listAdminCategories,
  listDepartments,
  listJurisdictions,
  listTeams,
  listUsers,
  type Team,
  updateTeam,
} from "@/lib/api";
import { hasPermission } from "@/lib/auth/access";
import { useSession } from "@/lib/auth/use-session";

const TEAMS_KEY = ["admin", "teams"] as const;
/** Roles that can sit on a team (the API checks too). */
const STAFF_ROLES = new Set(["operator", "supervisor", "field_worker"]);

function useReferenceLists(enabled: boolean) {
  const departments = useQuery({
    queryKey: ["admin", "departments"],
    queryFn: ({ signal }) => listDepartments(signal),
    enabled,
  });
  const jurisdictions = useQuery({
    queryKey: ["admin", "jurisdictions", "all"],
    queryFn: ({ signal }) => listJurisdictions({}, signal),
    enabled,
  });
  const categories = useQuery({
    queryKey: ["admin", "categories", "all"],
    queryFn: ({ signal }) => listAdminCategories(signal),
    enabled,
  });
  const users = useQuery({
    queryKey: ["admin", "users", "staff"],
    queryFn: ({ signal }) => listUsers({ is_active: true, limit: 100 }, signal),
    enabled,
  });
  return { departments, jurisdictions, categories, users };
}

/** Create a team, or edit one. Lists replace what's stored (contract §1). */
function TeamDialog({
  team,
  open,
  onOpenChange,
}: {
  /** Null: a new team. */
  team: Team | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const t = useTranslations("admin.teams.dialog");
  const errorMessage = useErrorMessage();
  const localized = useLocalized();
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const leadId = useId();
  const refs = useReferenceLists(open);
  const [name, setName] = useState("");
  const [departmentId, setDepartmentId] = useState("");
  const [members, setMembers] = useState<string[]>([]);
  const [lead, setLead] = useState("");
  const [jurisdictions, setJurisdictions] = useState<string[]>([]);
  const [categories, setCategories] = useState<string[]>([]);
  const [active, setActive] = useState(true);
  const [attempted, setAttempted] = useState(false);

  useEffect(() => {
    if (!open) return;
    setName(team?.name ?? "");
    setDepartmentId(team?.department.id ?? "");
    setMembers(team?.members.map((member) => member.user.id) ?? []);
    setLead(
      team?.members.find((member) => member.team_role === "lead")?.user.id ??
        "",
    );
    setJurisdictions(team?.jurisdiction_ids ?? []);
    setCategories(team?.category_ids ?? []);
    setActive(team?.is_active ?? true);
    setAttempted(false);
  }, [open, team]);

  const staff = useMemo(
    () =>
      (refs.users.data?.items ?? []).filter((user) =>
        user.roles.some((role) => STAFF_ROLES.has(role.role)),
      ),
    [refs.users.data],
  );
  const nameOf = (id: string) =>
    staff.find((user) => user.id === id)?.display_name ??
    team?.members.find((member) => member.user.id === id)?.user.display_name ??
    id;

  const mutation = useMutation({
    mutationFn: () => {
      const body = {
        name: name.trim(),
        members: members.map((user_id) => ({
          user_id,
          team_role: user_id === lead ? ("lead" as const) : ("member" as const),
        })),
        jurisdiction_ids: jurisdictions,
        category_ids: categories,
      };
      return team
        ? updateTeam(team.id, { ...body, is_active: active })
        : createTeam({ ...body, department_id: departmentId });
    },
    onSuccess: (saved) => {
      queryClient.invalidateQueries({ queryKey: TEAMS_KEY });
      toast({
        variant: "success",
        title: t(team ? "updated" : "created", { name: saved.name }),
      });
      onOpenChange(false);
    },
  });

  const nameMissing = !name.trim();
  const departmentMissing = !team && !departmentId;
  const submit = () => {
    setAttempted(true);
    if (nameMissing || departmentMissing) return;
    mutation.mutate();
  };
  const loading = Object.values(refs).some((query) => query.isPending);

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={team ? t("editTitle", { name: team.name }) : t("createTitle")}
      description={t("description")}
      closeLabel={t("close")}
      className="max-w-2xl"
      footer={
        <>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t("cancel")}
          </Button>
          <Button onClick={submit} loading={mutation.isPending}>
            {team ? t("save") : t("create")}
          </Button>
        </>
      }
    >
      {loading ? (
        <PageLoading />
      ) : (
        <div className="grid gap-5">
          <Field
            label={t("name")}
            required
            error={attempted && nameMissing ? t("nameRequired") : undefined}
          >
            {(control) => (
              <Input
                {...control}
                value={name}
                maxLength={120}
                onChange={(event) => setName(event.target.value)}
              />
            )}
          </Field>
          {team ? null : (
            <Field
              label={t("department")}
              required
              error={
                attempted && departmentMissing
                  ? t("departmentRequired")
                  : undefined
              }
            >
              {(control) => (
                <Select
                  {...control}
                  value={departmentId}
                  onChange={(event) => setDepartmentId(event.target.value)}
                >
                  <option value="">{t("chooseDepartment")}</option>
                  {refs.departments.data?.items.map((department) => (
                    <option key={department.id} value={department.id}>
                      {department.name}
                    </option>
                  ))}
                </Select>
              )}
            </Field>
          )}
          <MultiSelect
            label={t("members")}
            options={staff.map((user) => ({
              value: user.id,
              label: user.display_name ?? user.phone,
            }))}
            value={members}
            onChange={(next) => {
              setMembers(next);
              if (!next.includes(lead)) setLead("");
            }}
            allLabel={t("noMembers")}
            selectedLabel={(count) => t("selected", { count })}
          />
          {members.length > 0 ? (
            <div className="grid gap-1.5">
              <label htmlFor={leadId} className="text-sm font-semibold">
                {t("lead")}
              </label>
              <Select
                id={leadId}
                value={lead}
                onChange={(event) => setLead(event.target.value)}
              >
                <option value="">{t("noLead")}</option>
                {members.map((id) => (
                  <option key={id} value={id}>
                    {nameOf(id)}
                  </option>
                ))}
              </Select>
            </div>
          ) : null}
          <MultiSelect
            label={t("area")}
            options={(refs.jurisdictions.data?.items ?? []).map((item) => ({
              value: item.id,
              label: item.name,
            }))}
            value={jurisdictions}
            onChange={setJurisdictions}
            allLabel={t("noArea")}
            selectedLabel={(count) => t("selected", { count })}
          />
          <MultiSelect
            label={t("categories")}
            options={(refs.categories.data?.items ?? []).map((item) => ({
              value: item.id,
              label: localized(item.name_i18n),
            }))}
            value={categories}
            onChange={setCategories}
            allLabel={t("noCategories")}
            selectedLabel={(count) => t("selected", { count })}
          />
          {team ? (
            <div className="flex items-center gap-2 text-sm">
              <Checkbox
                id={`${leadId}-active`}
                checked={active}
                onChange={(event) => setActive(event.target.checked)}
              />
              <label htmlFor={`${leadId}-active`}>{t("active")}</label>
            </div>
          ) : null}
          {mutation.isError ? (
            <Alert variant="destructive" live="assertive">
              {errorMessage(mutation.error)}
            </Alert>
          ) : null}
        </div>
      )}
    </Dialog>
  );
}

/** Field and operator teams that issues are assigned to (FR-061). */
export function TeamsScreen() {
  const t = useTranslations("admin.teams");
  const errorMessage = useErrorMessage();
  const { user } = useSession();
  const canManage = hasPermission(user, "config:manage");
  const [editing, setEditing] = useState<Team | null | undefined>(undefined);
  const query = useQuery({
    queryKey: [...TEAMS_KEY, "list"],
    queryFn: ({ signal }) => listTeams({ limit: 100 }, signal),
  });

  return (
    <div className="grid gap-6 motion-safe:animate-rise">
      <PageHeader
        section="teams"
        title={t("title")}
        description={t("description")}
        actions={
          canManage ? (
            <Button onClick={() => setEditing(null)}>
              <Plus aria-hidden="true" />
              {t("new")}
            </Button>
          ) : null
        }
      />
      {query.isPending ? (
        <PageLoading />
      ) : query.isError ? (
        <Alert variant="destructive" live="assertive" title={t("loadError")}>
          {errorMessage(query.error)}
        </Alert>
      ) : (
        <Table label={t("title")}>
          <TableHeader>
            <TableRow>
              <TableHead>{t("name")}</TableHead>
              <TableHead>{t("department")}</TableHead>
              <TableHead>{t("members")}</TableHead>
              <TableHead>{t("status")}</TableHead>
              {canManage ? (
                <TableHead>
                  <span className="sr-only">{t("actions")}</span>
                </TableHead>
              ) : null}
            </TableRow>
          </TableHeader>
          <TableBody>
            {query.data.items.length === 0 ? (
              <TableRow>
                <TableCell colSpan={5} className="text-muted-foreground">
                  {t("empty")}
                </TableCell>
              </TableRow>
            ) : (
              query.data.items.map((team) => (
                <TableRow key={team.id}>
                  <TableCell className="font-medium">{team.name}</TableCell>
                  <TableCell>{team.department.name}</TableCell>
                  <TableCell>
                    {team.members
                      .map(
                        (member) =>
                          `${member.user.display_name ?? "—"}${
                            member.team_role === "lead"
                              ? ` (${t("leadShort")})`
                              : ""
                          }`,
                      )
                      .join(", ") || "—"}
                  </TableCell>
                  <TableCell>
                    <Badge variant={team.is_active ? "success" : "neutral"}>
                      {team.is_active ? t("active") : t("inactive")}
                    </Badge>
                  </TableCell>
                  {canManage ? (
                    <TableCell className="text-end">
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => setEditing(team)}
                        aria-label={t("edit", { name: team.name })}
                      >
                        <Pencil aria-hidden="true" />
                      </Button>
                    </TableCell>
                  ) : null}
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      )}
      <TeamDialog
        team={editing ?? null}
        open={editing !== undefined}
        onOpenChange={(open) => {
          if (!open) setEditing(undefined);
        }}
      />
    </div>
  );
}
