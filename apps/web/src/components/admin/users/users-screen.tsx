"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import {
  CircleCheck,
  CircleSlash,
  Search,
  ShieldCheck,
  UserPlus,
  UsersRound,
} from "lucide-react";
import { useFormatter, useTranslations } from "next-intl";
import { useId, useState } from "react";
import { PageHeader } from "@/components/admin/page-header";
import { Pagination } from "@/components/admin/pagination";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useDebouncedValue } from "@/hooks/use-debounced-value";
import { useErrorMessage } from "@/hooks/use-error-message";
import { type AdminUser, listUsers, ROLES, type Role } from "@/lib/api";
import { useSession } from "@/lib/auth/use-session";
import { formatIndianPhone } from "@/lib/phone";
import { CreateUserDialog } from "./create-user-dialog";
import { EditRolesDialog } from "./edit-roles-dialog";
import { StatusDialog } from "./status-dialog";
import { useScopes } from "./use-scopes";

const PAGE_SIZE = 20;
type StatusFilter = "all" | "active" | "inactive";

export function UsersScreen() {
  const t = useTranslations("admin.users");
  const tRoles = useTranslations("roles");
  const format = useFormatter();
  const errorMessage = useErrorMessage();
  const { user: actor } = useSession();
  const scopes = useScopes();
  const ids = { search: useId(), role: useId(), status: useId() };

  const [search, setSearch] = useState("");
  const [role, setRole] = useState<Role | "">("");
  const [status, setStatus] = useState<StatusFilter>("all");
  const [offset, setOffset] = useState(0);
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<AdminUser | null>(null);
  const [toggling, setToggling] = useState<AdminUser | null>(null);

  const q = useDebouncedValue(search.trim(), 300);
  const params = {
    q: q || undefined,
    role: role || undefined,
    is_active: status === "all" ? undefined : status === "active",
    limit: PAGE_SIZE,
    offset,
    sort: "-created_at",
  };

  const users = useQuery({
    queryKey: ["admin", "users", params],
    queryFn: ({ signal }) => listUsers(params, signal),
    placeholderData: keepPreviousData,
  });

  const filtersActive = Boolean(q || role || status !== "all");
  const clearFilters = () => {
    setSearch("");
    setRole("");
    setStatus("all");
    setOffset(0);
  };

  const scopeLabel = (departmentId: string | null, wardId: string | null) =>
    [scopes.departmentName(departmentId), scopes.wardName(wardId)]
      .filter(Boolean)
      .join(" · ");

  return (
    <div className="motion-safe:animate-rise">
      <PageHeader
        section="users"
        title={t("title")}
        description={t("description")}
        actions={
          <Button onClick={() => setCreating(true)}>
            <UserPlus aria-hidden="true" />
            {t("addStaff")}
          </Button>
        }
      />

      <search className="mb-4 grid gap-3 rounded-xl border border-border bg-card p-4 shadow-card sm:grid-cols-[2fr_1fr_1fr]">
        <div className="grid gap-1.5">
          <Label htmlFor={ids.search}>{t("searchLabel")}</Label>
          <div className="relative">
            <Search
              aria-hidden="true"
              className="pointer-events-none absolute start-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground"
            />
            <Input
              id={ids.search}
              type="search"
              value={search}
              placeholder={t("searchPlaceholder")}
              className="ps-9"
              onChange={(event) => {
                setSearch(event.target.value);
                setOffset(0);
              }}
            />
          </div>
        </div>
        <div className="grid gap-1.5">
          <Label htmlFor={ids.role}>{t("roleFilter")}</Label>
          <Select
            id={ids.role}
            value={role}
            onChange={(event) => {
              setRole(event.target.value as Role | "");
              setOffset(0);
            }}
          >
            <option value="">{t("allRoles")}</option>
            {ROLES.map((value) => (
              <option key={value} value={value}>
                {tRoles(value)}
              </option>
            ))}
          </Select>
        </div>
        <div className="grid gap-1.5">
          <Label htmlFor={ids.status}>{t("statusFilter")}</Label>
          <Select
            id={ids.status}
            value={status}
            onChange={(event) => {
              setStatus(event.target.value as StatusFilter);
              setOffset(0);
            }}
          >
            <option value="all">{t("statusAll")}</option>
            <option value="active">{t("statusActive")}</option>
            <option value="inactive">{t("statusInactive")}</option>
          </Select>
        </div>
      </search>

      {users.isError ? (
        <Alert
          variant="destructive"
          live="assertive"
          title={t("loadError")}
          className="mb-4"
        >
          <p>{errorMessage(users.error)}</p>
          <Button
            variant="outline"
            size="sm"
            className="mt-3"
            onClick={() => users.refetch()}
          >
            {t("retry")}
          </Button>
        </Alert>
      ) : null}

      <Table
        label={t("tableLabel")}
        aria-busy={users.isFetching || undefined}
        aria-describedby={`${ids.search}-summary`}
      >
        <TableHeader>
          <TableRow className="hover:bg-transparent">
            <TableHead>{t("colName")}</TableHead>
            <TableHead>{t("colPhone")}</TableHead>
            <TableHead>{t("colRoles")}</TableHead>
            <TableHead>{t("colStatus")}</TableHead>
            <TableHead>{t("colCreated")}</TableHead>
            <TableHead className="text-end">
              <span className="sr-only">{t("colActions")}</span>
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {users.isPending ? (
            Array.from({ length: 5 }, (_, index) => (
              // biome-ignore lint/suspicious/noArrayIndexKey: static placeholder rows
              <TableRow key={index}>
                {Array.from({ length: 6 }, (_, cell) => (
                  // biome-ignore lint/suspicious/noArrayIndexKey: static placeholder cells
                  <TableCell key={cell}>
                    <Skeleton className="h-4 w-full max-w-36" />
                  </TableCell>
                ))}
              </TableRow>
            ))
          ) : users.data?.items.length ? (
            users.data.items.map((row) => {
              const isSelf = row.id === actor?.id;
              return (
                <TableRow key={row.id}>
                  <TableCell>
                    <div className="grid gap-0.5">
                      <span className="font-semibold">
                        {row.display_name || t("unnamed")}
                        {isSelf ? (
                          <span className="ms-1.5 text-xs font-medium text-muted-foreground">
                            {t("you")}
                          </span>
                        ) : null}
                      </span>
                      {row.email ? (
                        <span className="text-xs text-muted-foreground">
                          {row.email}
                        </span>
                      ) : null}
                    </div>
                  </TableCell>
                  <TableCell className="font-mono text-[0.8125rem] whitespace-nowrap">
                    {formatIndianPhone(row.phone)}
                  </TableCell>
                  <TableCell>
                    <ul className="flex max-w-xs flex-wrap gap-1">
                      {row.roles.map((assignment) => {
                        const scope = scopeLabel(
                          assignment.department_id,
                          assignment.jurisdiction_id,
                        );
                        return (
                          <li
                            key={`${assignment.role}-${assignment.department_id}-${assignment.jurisdiction_id}`}
                          >
                            <Badge
                              variant={
                                assignment.role === "citizen"
                                  ? "neutral"
                                  : "primary"
                              }
                            >
                              {assignment.role !== "citizen" ? (
                                <ShieldCheck aria-hidden="true" />
                              ) : null}
                              {tRoles(assignment.role)}
                              {scope ? (
                                <span className="font-normal">· {scope}</span>
                              ) : null}
                            </Badge>
                          </li>
                        );
                      })}
                    </ul>
                  </TableCell>
                  <TableCell>
                    {row.is_active ? (
                      <Badge variant="success">
                        <CircleCheck aria-hidden="true" />
                        {t("statusActive")}
                      </Badge>
                    ) : (
                      <Badge variant="neutral">
                        <CircleSlash aria-hidden="true" />
                        {t("statusInactive")}
                      </Badge>
                    )}
                  </TableCell>
                  <TableCell className="whitespace-nowrap text-muted-foreground">
                    {format.dateTime(new Date(row.created_at), {
                      dateStyle: "medium",
                    })}
                  </TableCell>
                  <TableCell>
                    <div className="flex justify-end gap-1">
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => setEditing(row)}
                        aria-label={t("editRolesFor", {
                          name:
                            row.display_name || formatIndianPhone(row.phone),
                        })}
                      >
                        {t("editRoles")}
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        disabled={isSelf}
                        title={isSelf ? t("cantDeactivateSelf") : undefined}
                        onClick={() => setToggling(row)}
                        aria-label={
                          row.is_active
                            ? t("deactivateFor", {
                                name:
                                  row.display_name ||
                                  formatIndianPhone(row.phone),
                              })
                            : t("activateFor", {
                                name:
                                  row.display_name ||
                                  formatIndianPhone(row.phone),
                              })
                        }
                        className={
                          row.is_active
                            ? "text-destructive-soft-foreground"
                            : undefined
                        }
                      >
                        {row.is_active ? t("deactivate") : t("activate")}
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              );
            })
          ) : users.isSuccess ? (
            <TableRow className="hover:bg-transparent">
              <TableCell colSpan={6}>
                <div className="grid justify-items-center gap-2 py-10 text-center">
                  <UsersRound
                    aria-hidden="true"
                    className="size-8 text-muted-foreground"
                  />
                  <p className="font-semibold">
                    {filtersActive ? t("emptyFiltered") : t("empty")}
                  </p>
                  {filtersActive ? (
                    <Button variant="outline" size="sm" onClick={clearFilters}>
                      {t("clearFilters")}
                    </Button>
                  ) : null}
                </div>
              </TableCell>
            </TableRow>
          ) : null}
        </TableBody>
      </Table>
      <span id={`${ids.search}-summary`} className="sr-only">
        {users.data ? t("resultCount", { count: users.data.total }) : ""}
      </span>

      {users.data ? (
        <Pagination
          label={t("paginationLabel")}
          offset={users.data.offset}
          limit={users.data.limit}
          total={users.data.total}
          onOffsetChange={setOffset}
        />
      ) : null}

      <CreateUserDialog open={creating} onOpenChange={setCreating} />
      <EditRolesDialog user={editing} onClose={() => setEditing(null)} />
      <StatusDialog user={toggling} onClose={() => setToggling(null)} />
    </div>
  );
}
