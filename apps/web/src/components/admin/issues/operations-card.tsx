"use client";

import { CircleCheckBig, CircleX, UserCheck } from "lucide-react";
import { useFormatter, useTranslations } from "next-intl";
import { WorkOrderStateBadge } from "@/components/field/work-order-state-badge";
import { PhotoGallery } from "@/components/media/photo-gallery";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import type { IssueDetail } from "@/lib/api";
import { isAssignable } from "./operations-dialogs";

/**
 * Who has the issue and, while one is pending, the field worker's closure
 * request with its after photos (Phase 3 §2 and §5).
 */
export function OperationsCard({
  issue,
  canAssign,
  canApprove,
  onAssign,
  onApprove,
  onReject,
}: {
  issue: IssueDetail;
  canAssign: boolean;
  canApprove: boolean;
  onAssign: () => void;
  onApprove: () => void;
  onReject: () => void;
}) {
  const t = useTranslations("admin.issueDetail.operations");
  const format = useFormatter();
  const assignment = issue.operations?.assignment ?? null;
  const closure = issue.operations?.closure_request ?? null;
  const when = (at: string) =>
    format.dateTime(new Date(at), { dateStyle: "medium", timeStyle: "short" });

  return (
    <>
      <Card className="grid gap-3 p-5">
        <h2 className="eyebrow">{t("assignment")}</h2>
        {assignment ? (
          <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-sm">
            <dt className="text-muted-foreground">{t("team")}</dt>
            <dd className="font-medium">{assignment.team.name}</dd>
            <dt className="text-muted-foreground">{t("assignee")}</dt>
            <dd className="font-medium">
              {assignment.assignee?.display_name ?? t("teamOnly")}
            </dd>
            {assignment.work_order ? (
              <>
                <dt className="text-muted-foreground">{t("workOrder")}</dt>
                <dd>
                  <WorkOrderStateBadge state={assignment.work_order.state} />
                </dd>
              </>
            ) : null}
            <dt className="text-muted-foreground">{t("assignedAt")}</dt>
            <dd>
              {when(assignment.assigned_at)}
              {assignment.assigned_by?.display_name
                ? ` · ${assignment.assigned_by.display_name}`
                : ""}
            </dd>
            {assignment.note ? (
              <>
                <dt className="text-muted-foreground">{t("note")}</dt>
                <dd className="whitespace-pre-line">{assignment.note}</dd>
              </>
            ) : null}
          </dl>
        ) : (
          <p className="text-sm text-muted-foreground">{t("unassigned")}</p>
        )}
        {canAssign && isAssignable(issue) ? (
          <Button variant="outline" className="w-fit" onClick={onAssign}>
            <UserCheck aria-hidden="true" />
            {assignment ? t("reassign") : t("assign")}
          </Button>
        ) : null}
      </Card>

      {closure && closure.state === "pending" ? (
        <Card className="grid gap-3 border-info-soft-foreground/30 p-5">
          <h2 className="eyebrow">{t("closureRequest")}</h2>
          <p className="text-sm">
            {t("requestedBy", {
              name: closure.requested_by?.display_name ?? t("someone"),
              when: when(closure.requested_at),
            })}
          </p>
          {closure.after_photos.length > 0 ? (
            <PhotoGallery
              media={closure.after_photos}
              label={t("afterPhotosOf", { reference: issue.reference })}
              showOriginal
            />
          ) : (
            <p className="text-sm text-muted-foreground">{t("noPhoto")}</p>
          )}
          {closure.after_photos.length > 0 ? (
            <p className="text-sm text-muted-foreground">
              {closure.scene_match
                ? t("sceneMatch", {
                    percent: Math.round(closure.scene_match.similarity * 100),
                  })
                : t("sceneMatchPending")}{" "}
              {t("sceneMatchAdvice")}
            </p>
          ) : null}
          {closure.reason_code ? (
            <p className="text-sm">
              {t("reasonCode", {
                code: closure.reason_code.replaceAll("_", " "),
              })}
            </p>
          ) : null}
          {closure.note ? (
            <p className="whitespace-pre-line text-sm">{closure.note}</p>
          ) : null}
          <p className="text-xs text-muted-foreground">
            {closure.requires_approval
              ? t("needsApproval")
              : t("citizensConfirm")}{" "}
            {t("answers", {
              confirmations: closure.confirmations,
              unresolved: closure.unresolved,
            })}
          </p>
          {canApprove ? (
            <div className="flex flex-wrap gap-2">
              <Button onClick={onApprove}>
                <CircleCheckBig aria-hidden="true" />
                {t("approve")}
              </Button>
              <Button variant="outline" onClick={onReject}>
                <CircleX aria-hidden="true" />
                {t("reject")}
              </Button>
            </div>
          ) : null}
        </Card>
      ) : null}
    </>
  );
}
