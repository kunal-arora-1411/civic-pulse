import {
  fieldAccept,
  fieldDecline,
  fieldGetWorkOrder,
  fieldListWorkOrders,
  fieldProgress,
  fieldRequestClosure,
  fieldStart,
} from "@civicpulse/api-client";
import { call, queryParams } from "../generated-client";
import {
  type WorkOrder,
  type WorkOrderPage,
  type WorkOrderState,
  workOrderPageSchema,
  workOrderSchema,
} from "../schemas-operations";

/*
 * The field worker's own work orders (Phase 3 §3). Every mutation carries
 * the work order version the worker last saw. A stale one is a 409
 * `version_conflict` whose `details.work_order` is the current field view,
 * so a retried request after a lost response is never applied twice.
 */

export type WorkOrderFilters = {
  /** Default (none given): every state except declined and cancelled. */
  state?: readonly WorkOrderState[];
  limit?: number;
  offset?: number;
};

export function listWorkOrders(
  filters: WorkOrderFilters = {},
  signal?: AbortSignal,
): Promise<WorkOrderPage> {
  return call(
    workOrderPageSchema,
    (o) => fieldListWorkOrders(queryParams(filters), o),
    { signal },
  );
}

export function getWorkOrder(
  id: string,
  signal?: AbortSignal,
): Promise<WorkOrder> {
  return call(workOrderSchema, (o) => fieldGetWorkOrder(id, o), { signal });
}

export function acceptWorkOrder(id: string, version: number) {
  return call(workOrderSchema, (o) => fieldAccept(id, { version }, o));
}

export function declineWorkOrder(id: string, version: number, reason: string) {
  return call(workOrderSchema, (o) => fieldDecline(id, { version, reason }, o));
}

export function startWorkOrder(id: string, version: number) {
  return call(workOrderSchema, (o) => fieldStart(id, { version }, o));
}

export type ProgressBody = {
  version: number;
  note?: string;
  location?: { lat: number; lng: number } | null;
  media_ids?: string[];
};

/** At least a note or a photo. */
export function postProgress(id: string, body: ProgressBody) {
  return call(workOrderSchema, (o) => fieldProgress(id, body, o));
}

export type RequestClosureBody = {
  version: number;
  media_ids?: string[];
  reason_code?: string;
  note?: string;
};

/** Needs an `after` photo on the work order or an allowed reason code. */
export function requestClosure(id: string, body: RequestClosureBody) {
  return call(workOrderSchema, (o) => fieldRequestClosure(id, body, o));
}
