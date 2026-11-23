"use client";

import { useQuery } from "@tanstack/react-query";
import { listDepartments, listJurisdictions } from "@/lib/api";
import { hasPermission } from "@/lib/auth/access";
import { useSession } from "@/lib/auth/use-session";

/**
 * Departments and wards that a role can be scoped to. Both need
 * config:read; without it, roles can still be assigned tenant-wide.
 */
export function useScopes() {
  const { user } = useSession();
  const enabled = hasPermission(user, "config:read");

  const departments = useQuery({
    queryKey: ["admin", "departments"],
    queryFn: ({ signal }) => listDepartments(signal),
    enabled,
    staleTime: 5 * 60_000,
  });
  const wards = useQuery({
    queryKey: ["admin", "jurisdictions", "ward"],
    queryFn: ({ signal }) => listJurisdictions({ kind: "ward" }, signal),
    enabled,
    staleTime: 5 * 60_000,
  });

  const departmentList = departments.data?.items ?? [];
  const wardList = wards.data?.items ?? [];

  return {
    enabled,
    departments: departmentList,
    wards: wardList,
    departmentName: (id: string | null) =>
      id ? (departmentList.find((d) => d.id === id)?.name ?? null) : null,
    wardName: (id: string | null) =>
      id ? (wardList.find((w) => w.id === id)?.name ?? null) : null,
  };
}
