"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Megaphone, Plus } from "lucide-react";
import { useFormatter, useTranslations } from "next-intl";
import { useState } from "react";
import { PageHeader } from "@/components/admin/page-header";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Field } from "@/components/ui/field";
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
import { useToast } from "@/components/ui/toast";
import { useErrorMessage } from "@/hooks/use-error-message";
import { useLocalized } from "@/hooks/use-reference-data";
import {
  ANNOUNCEMENT_STATES,
  type Announcement,
  type AnnouncementState,
  listAnnouncements,
  withdrawAnnouncement,
} from "@/lib/api";
import { hasPermission } from "@/lib/auth/access";
import { useSession } from "@/lib/auth/use-session";
import { AnnouncementDialog } from "./announcement-dialog";

const STATE_BADGE = {
  active: "success",
  scheduled: "info",
  ended: "neutral",
  withdrawn: "warning",
} as const;

const PAGE_SIZE = 50;

function WithdrawDialog({
  announcement,
  onClose,
}: {
  announcement: Announcement | null;
  onClose: () => void;
}) {
  const t = useTranslations("admin.announcements");
  const errorMessage = useErrorMessage();
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const title = announcement?.title_i18n.en ?? "";
  const mutation = useMutation({
    mutationFn: () => withdrawAnnouncement((announcement as Announcement).id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["announcements"] });
      toast({ variant: "success", title: t("withdrawn", { title }) });
      onClose();
    },
  });
  return (
    <Dialog
      open={announcement !== null}
      onOpenChange={(open) => {
        if (!open) {
          mutation.reset();
          onClose();
        }
      }}
      title={t("withdrawTitle", { title })}
      closeLabel={t("close")}
      footer={
        <>
          <Button variant="outline" onClick={onClose}>
            {t("cancel")}
          </Button>
          <Button
            variant="destructive"
            loading={mutation.isPending}
            onClick={() => mutation.mutate()}
          >
            {t("withdraw")}
          </Button>
        </>
      }
    >
      <p className="text-muted-foreground">{t("withdrawBody")}</p>
      {mutation.isError ? (
        <Alert variant="destructive" live="assertive" className="mt-3">
          {errorMessage(mutation.error)}
        </Alert>
      ) : null}
    </Dialog>
  );
}

/** Service announcements (FR-087): publish, edit and withdraw notices. */
export function AnnouncementsScreen() {
  const t = useTranslations("admin.announcements");
  const tKind = useTranslations("announcementKind");
  const format = useFormatter();
  const localized = useLocalized();
  const errorMessage = useErrorMessage();
  const { user } = useSession();
  const canManage = hasPermission(user, "config:manage");
  const [state, setState] = useState<AnnouncementState | "">("");
  const [editing, setEditing] = useState<Announcement | null>(null);
  const [creating, setCreating] = useState(false);
  const [withdrawing, setWithdrawing] = useState<Announcement | null>(null);

  const announcements = useQuery({
    queryKey: ["announcements", "admin", state],
    queryFn: ({ signal }) =>
      listAnnouncements(
        { state: state || undefined, limit: PAGE_SIZE },
        signal,
      ),
  });
  const rows = announcements.data?.items ?? [];
  const columns = canManage ? 6 : 5;
  const when = (iso: string) =>
    format.dateTime(new Date(iso), {
      dateStyle: "medium",
      timeStyle: "short",
      timeZone: "Asia/Kolkata",
    });

  return (
    <div className="motion-safe:animate-rise">
      <PageHeader
        section="announcements"
        title={t("title")}
        description={t("description")}
        actions={
          canManage ? (
            <Button onClick={() => setCreating(true)}>
              <Plus aria-hidden="true" />
              {t("add")}
            </Button>
          ) : null
        }
      />
      {!canManage ? (
        <Alert variant="info" className="mb-4">
          {t("readOnly")}
        </Alert>
      ) : null}
      <div className="mb-4 flex">
        <Field label={t("stateFilter")} className="w-full sm:w-52">
          {(control) => (
            <Select
              {...control}
              value={state}
              onChange={(event) =>
                setState(event.target.value as AnnouncementState | "")
              }
            >
              <option value="">{t("allStates")}</option>
              {ANNOUNCEMENT_STATES.map((value) => (
                <option key={value} value={value}>
                  {t(`states.${value}`)}
                </option>
              ))}
            </Select>
          )}
        </Field>
      </div>
      {announcements.isError ? (
        <Alert
          variant="destructive"
          live="assertive"
          title={t("loadError")}
          className="mb-4"
        >
          <p>{errorMessage(announcements.error)}</p>
          <Button
            variant="outline"
            size="sm"
            className="mt-3"
            onClick={() => announcements.refetch()}
          >
            {t("retry")}
          </Button>
        </Alert>
      ) : null}

      <Table
        label={t("tableLabel")}
        aria-busy={announcements.isFetching || undefined}
      >
        <TableHeader>
          <TableRow className="hover:bg-transparent">
            <TableHead>{t("colTitle")}</TableHead>
            <TableHead>{t("colArea")}</TableHead>
            <TableHead>{t("colStarts")}</TableHead>
            <TableHead>{t("colEnds")}</TableHead>
            <TableHead>{t("colState")}</TableHead>
            {canManage ? (
              <TableHead className="text-end">
                <span className="sr-only">{t("colActions")}</span>
              </TableHead>
            ) : null}
          </TableRow>
        </TableHeader>
        <TableBody>
          {announcements.isPending ? (
            Array.from({ length: 4 }, (_, row) => (
              // biome-ignore lint/suspicious/noArrayIndexKey: static placeholders
              <TableRow key={row}>
                {Array.from({ length: columns }, (_, cell) => (
                  // biome-ignore lint/suspicious/noArrayIndexKey: static placeholders
                  <TableCell key={cell}>
                    <Skeleton className="h-4 w-full max-w-28" />
                  </TableCell>
                ))}
              </TableRow>
            ))
          ) : rows.length > 0 ? (
            rows.map((item) => {
              const title = item.title_i18n.en ?? "";
              const open = item.state !== "withdrawn" && item.state !== "ended";
              return (
                <TableRow key={item.id}>
                  <TableCell>
                    <div className="grid gap-0.5">
                      <span className="font-semibold">
                        {localized(item.title_i18n)}
                      </span>
                      <span className="text-xs text-muted-foreground">
                        {tKind(item.kind)}
                      </span>
                    </div>
                  </TableCell>
                  <TableCell>
                    <div className="grid gap-0.5">
                      <span>{item.ward?.name ?? t("wholeCity")}</span>
                      {item.category ? (
                        <span className="text-xs text-muted-foreground">
                          {localized(item.category.name_i18n)}
                        </span>
                      ) : null}
                    </div>
                  </TableCell>
                  <TableCell className="whitespace-nowrap">
                    {when(item.starts_at)}
                  </TableCell>
                  <TableCell className="whitespace-nowrap">
                    {when(item.ends_at)}
                  </TableCell>
                  <TableCell>
                    <Badge variant={STATE_BADGE[item.state]}>
                      {t(`states.${item.state}`)}
                    </Badge>
                  </TableCell>
                  {canManage ? (
                    <TableCell>
                      {open ? (
                        <div className="flex justify-end gap-1">
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => setEditing(item)}
                            aria-label={t("editFor", { title })}
                          >
                            {t("edit")}
                          </Button>
                          <Button
                            variant="ghost"
                            size="sm"
                            className="text-destructive-soft-foreground"
                            onClick={() => setWithdrawing(item)}
                            aria-label={t("withdrawFor", { title })}
                          >
                            {t("withdraw")}
                          </Button>
                        </div>
                      ) : null}
                    </TableCell>
                  ) : null}
                </TableRow>
              );
            })
          ) : announcements.isSuccess ? (
            <TableRow className="hover:bg-transparent">
              <TableCell colSpan={columns}>
                <div className="grid justify-items-center gap-2 py-10 text-center">
                  <Megaphone
                    aria-hidden="true"
                    className="size-8 text-muted-foreground"
                  />
                  <p className="font-semibold">{t("empty")}</p>
                </div>
              </TableCell>
            </TableRow>
          ) : null}
        </TableBody>
      </Table>

      <AnnouncementDialog
        open={creating || editing !== null}
        announcement={editing}
        onOpenChange={(next) => {
          if (!next) {
            setCreating(false);
            setEditing(null);
          }
        }}
      />
      <WithdrawDialog
        announcement={withdrawing}
        onClose={() => setWithdrawing(null)}
      />
    </div>
  );
}
