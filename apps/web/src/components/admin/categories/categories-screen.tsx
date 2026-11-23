"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CircleCheck, CircleSlash, Plus, Tags } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { PageHeader } from "@/components/admin/page-header";
import { CategoryIcon } from "@/components/issues/category-icon";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
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
import { type Category, listAdminCategories, updateCategory } from "@/lib/api";
import { hasPermission } from "@/lib/auth/access";
import { useSession } from "@/lib/auth/use-session";
import { CategoryDialog } from "./category-dialog";

function ToggleDialog({
  category,
  onClose,
}: {
  category: Category | null;
  onClose: () => void;
}) {
  const t = useTranslations("admin.categories");
  const errorMessage = useErrorMessage();
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const name = category?.name_i18n.en ?? category?.code ?? "";
  const activating = category ? !category.is_active : false;
  const mutation = useMutation({
    mutationFn: () =>
      updateCategory((category as Category).id, { is_active: activating }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["categories"] });
      toast({
        variant: "success",
        title: activating
          ? t("activated", { name })
          : t("deactivated", { name }),
      });
      onClose();
    },
  });

  return (
    <Dialog
      open={category !== null}
      onOpenChange={(open) => {
        if (!open) {
          mutation.reset();
          onClose();
        }
      }}
      title={
        activating
          ? t("activateTitle", { name })
          : t("deactivateTitle", { name })
      }
      closeLabel={t("close")}
      footer={
        <>
          <Button variant="outline" onClick={onClose}>
            {t("cancel")}
          </Button>
          <Button
            variant={activating ? "primary" : "destructive"}
            loading={mutation.isPending}
            onClick={() => mutation.mutate()}
          >
            {activating ? t("activate") : t("deactivate")}
          </Button>
        </>
      }
    >
      <p className="text-muted-foreground">
        {activating ? t("activateBody") : t("deactivateBody")}
      </p>
      {mutation.isError ? (
        <Alert variant="destructive" live="assertive" className="mt-3">
          {errorMessage(mutation.error)}
        </Alert>
      ) : null}
    </Dialog>
  );
}

export function CategoriesScreen() {
  const t = useTranslations("admin.categories");
  const tFields = useTranslations("admin.categories.fields");
  const errorMessage = useErrorMessage();
  const { user } = useSession();
  const canManage = hasPermission(user, "config:manage");
  const categories = useQuery({
    queryKey: ["categories", "all"],
    queryFn: async ({ signal }) => (await listAdminCategories(signal)).items,
  });
  const [editing, setEditing] = useState<Category | null>(null);
  const [creating, setCreating] = useState(false);
  const [toggling, setToggling] = useState<Category | null>(null);

  const rows = [...(categories.data ?? [])].sort(
    (a, b) => a.sort_order - b.sort_order,
  );
  const nextSortOrder =
    rows.length > 0 ? Math.max(...rows.map((c) => c.sort_order)) + 10 : 10;

  return (
    <div className="motion-safe:animate-rise">
      <PageHeader
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
      {categories.isError ? (
        <Alert
          variant="destructive"
          live="assertive"
          title={t("loadError")}
          className="mb-4"
        >
          <p>{errorMessage(categories.error)}</p>
          <Button
            variant="outline"
            size="sm"
            className="mt-3"
            onClick={() => categories.refetch()}
          >
            {t("retry")}
          </Button>
        </Alert>
      ) : null}

      <Table
        label={t("tableLabel")}
        aria-busy={categories.isFetching || undefined}
      >
        <TableHeader>
          <TableRow className="hover:bg-transparent">
            <TableHead>{t("colName")}</TableHead>
            <TableHead>{t("colCode")}</TableHead>
            <TableHead>{t("colPhotos")}</TableHead>
            <TableHead>{t("colFields")}</TableHead>
            <TableHead>{t("colOrder")}</TableHead>
            <TableHead>{t("colStatus")}</TableHead>
            {canManage ? (
              <TableHead className="text-end">
                <span className="sr-only">{t("colActions")}</span>
              </TableHead>
            ) : null}
          </TableRow>
        </TableHeader>
        <TableBody>
          {categories.isPending ? (
            Array.from({ length: 5 }, (_, row) => (
              // biome-ignore lint/suspicious/noArrayIndexKey: static placeholders
              <TableRow key={row}>
                {Array.from({ length: canManage ? 7 : 6 }, (_, cell) => (
                  // biome-ignore lint/suspicious/noArrayIndexKey: static placeholders
                  <TableCell key={cell}>
                    <Skeleton className="h-4 w-full max-w-28" />
                  </TableCell>
                ))}
              </TableRow>
            ))
          ) : rows.length > 0 ? (
            rows.map((category) => {
              const name = category.name_i18n.en ?? category.code;
              return (
                <TableRow key={category.id}>
                  <TableCell>
                    <div className="flex items-center gap-3">
                      <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-secondary text-secondary-foreground">
                        <CategoryIcon icon={category.icon} className="size-4" />
                      </span>
                      <div className="grid">
                        <span className="font-semibold">{name}</span>
                        <span
                          lang="hi"
                          className="text-xs text-muted-foreground"
                        >
                          {category.name_i18n.hi ?? t("noHindi")}
                        </span>
                      </div>
                    </div>
                  </TableCell>
                  <TableCell className="font-mono text-[0.8125rem]">
                    {category.code}
                  </TableCell>
                  <TableCell className="whitespace-nowrap tabular-nums">
                    {t("photoRange", {
                      min: category.evidence.min_photos,
                      max: category.evidence.max_photos,
                    })}
                  </TableCell>
                  <TableCell>
                    {category.fields.length > 0 ? (
                      <ul className="flex max-w-xs flex-wrap gap-1">
                        {category.fields.map((field) => (
                          <li key={field.key}>
                            <Badge
                              variant="outline"
                              title={tFields(`types.${field.type}`)}
                            >
                              {field.label_i18n.en ?? field.key}
                              {field.required ? (
                                <>
                                  <span aria-hidden="true">*</span>
                                  <span className="sr-only">
                                    ({tFields("required")})
                                  </span>
                                </>
                              ) : null}
                            </Badge>
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <span className="text-muted-foreground">—</span>
                    )}
                  </TableCell>
                  <TableCell className="tabular-nums">
                    {category.sort_order}
                  </TableCell>
                  <TableCell>
                    {category.is_active ? (
                      <Badge variant="success">
                        <CircleCheck aria-hidden="true" />
                        {t("active")}
                      </Badge>
                    ) : (
                      <Badge variant="neutral">
                        <CircleSlash aria-hidden="true" />
                        {t("inactive")}
                      </Badge>
                    )}
                  </TableCell>
                  {canManage ? (
                    <TableCell>
                      <div className="flex justify-end gap-1">
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => setEditing(category)}
                          aria-label={t("editFor", { name })}
                        >
                          {t("edit")}
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => setToggling(category)}
                          aria-label={
                            category.is_active
                              ? t("deactivateFor", { name })
                              : t("activateFor", { name })
                          }
                          className={
                            category.is_active
                              ? "text-destructive-soft-foreground"
                              : undefined
                          }
                        >
                          {category.is_active ? t("deactivate") : t("activate")}
                        </Button>
                      </div>
                    </TableCell>
                  ) : null}
                </TableRow>
              );
            })
          ) : categories.isSuccess ? (
            <TableRow className="hover:bg-transparent">
              <TableCell colSpan={canManage ? 7 : 6}>
                <div className="grid justify-items-center gap-2 py-10 text-center">
                  <Tags
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

      <CategoryDialog
        open={creating || editing !== null}
        category={editing}
        nextSortOrder={nextSortOrder}
        onOpenChange={(open) => {
          if (!open) {
            setCreating(false);
            setEditing(null);
          }
        }}
      />
      <ToggleDialog category={toggling} onClose={() => setToggling(null)} />
    </div>
  );
}
