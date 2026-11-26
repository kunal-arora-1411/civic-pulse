"use client";

import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { PageHeader } from "@/components/admin/page-header";
import { PageLoading } from "@/components/page-loading";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useErrorMessage } from "@/hooks/use-error-message";
import { getWorkload } from "@/lib/api";

/**
 * Open work per team and per member (FR-068), so a supervisor can see who
 * has room before assigning. Limited to teams in the caller's scope.
 */
export function WorkloadScreen() {
  const t = useTranslations("admin.workload");
  const errorMessage = useErrorMessage();
  const query = useQuery({
    queryKey: ["admin", "workload"],
    queryFn: ({ signal }) => getWorkload(signal),
  });

  return (
    <div className="grid gap-6 motion-safe:animate-rise">
      <PageHeader
        section="workload"
        title={t("title")}
        description={t("description")}
      />
      {query.isPending ? (
        <PageLoading />
      ) : query.isError ? (
        <Alert variant="destructive" live="assertive" title={t("loadError")}>
          <p>{errorMessage(query.error)}</p>
          <Button
            variant="outline"
            size="sm"
            className="mt-2"
            onClick={() => query.refetch()}
          >
            {t("retry")}
          </Button>
        </Alert>
      ) : query.data.items.length === 0 ? (
        <Card className="p-6 text-center text-muted-foreground">
          {t("empty")}
        </Card>
      ) : (
        query.data.items.map((load) => (
          <section key={load.team.id} className="grid gap-3">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <h2 className="text-lg font-semibold">{load.team.name}</h2>
              <p className="text-sm text-muted-foreground">
                {t("summary", {
                  open: load.open,
                  pending: load.pending_acceptance,
                  inProgress: load.in_progress,
                })}
                {load.overdue
                  ? ` · ${t("overdue", { count: load.overdue })}`
                  : ""}
              </p>
            </div>
            <Table label={t("membersOf", { team: load.team.name })}>
              <TableHeader>
                <TableRow>
                  <TableHead>{t("member")}</TableHead>
                  <TableHead className="text-end">{t("open")}</TableHead>
                  <TableHead className="text-end">{t("inProgress")}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {load.members.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={3} className="text-muted-foreground">
                      {t("noMembers")}
                    </TableCell>
                  </TableRow>
                ) : (
                  load.members.map((member) => (
                    <TableRow key={member.user.id}>
                      <TableCell className="font-medium">
                        {member.user.display_name ?? t("unnamed")}
                      </TableCell>
                      <TableCell className="text-end tabular-nums">
                        {member.open}
                      </TableCell>
                      <TableCell className="text-end tabular-nums">
                        {member.in_progress}
                      </TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          </section>
        ))
      )}
    </div>
  );
}
