import { apiRequest } from "../client";
import {
  type SlaTargetIn,
  type SlaTargets,
  slaTargetsSchema,
} from "../schemas-sla";

export function getSlaTargets(signal?: AbortSignal): Promise<SlaTargets> {
  return apiRequest({
    path: "/admin/sla-targets",
    schema: slaTargetsSchema,
    signal,
  });
}

/** Replaces the whole set; open issues are rescheduled against it. */
export function updateSlaTargets(items: SlaTargetIn[]): Promise<SlaTargets> {
  return apiRequest({
    method: "PUT",
    path: "/admin/sla-targets",
    body: { items },
    schema: slaTargetsSchema,
  });
}
