"use client";

import { useQuery } from "@tanstack/react-query";
import { Landmark } from "lucide-react";
import { useTranslations } from "next-intl";
import { getCurrentTenant } from "@/lib/api";

/**
 * Shows which municipality the user is signing in to. Purely informative,
 * so it renders nothing while loading or if the call fails.
 */
export function TenantName() {
  const t = useTranslations("login");
  const { data } = useQuery({
    queryKey: ["tenant", "current"],
    queryFn: ({ signal }) => getCurrentTenant(signal),
    staleTime: Number.POSITIVE_INFINITY,
    retry: false,
  });

  return (
    <p className="flex min-h-6 items-center justify-center gap-2 text-sm font-medium text-muted-foreground">
      {data ? (
        <>
          <Landmark aria-hidden="true" className="size-4" />
          {t("tenant", { name: data.name })}
        </>
      ) : null}
    </p>
  );
}
