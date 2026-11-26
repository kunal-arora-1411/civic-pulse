"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  isApiError,
  type WorkOrder,
  type WorkOrderState,
  workOrderSchema,
} from "@/lib/api";
import { FIELD_KEY } from "./work-order-list";

export const workOrderKey = (id: string) => [...FIELD_KEY, "detail", id];

/** What the worker is told after a 409: the job moved on without them. */
export type WorkOrderConflict = {
  /** The state the server says the work order is in now. */
  state: WorkOrderState;
};

/**
 * A work order mutation. On success the detail cache takes the returned
 * field view and the queue refetches.
 *
 * On `409 version_conflict` the API sends the current work order in
 * `details.work_order`. That replaces the cached copy, so the screen shows
 * what really happened (a reassignment, an approval, the same action from
 * another tab) and offers only the actions that still fit. The request is
 * never retried with the new version: the worker decides again.
 */
export function useWorkOrderAction<V>(
  orderId: string,
  run: (variables: V) => Promise<WorkOrder>,
  {
    onSuccess,
    onConflict,
  }: {
    onSuccess?: (order: WorkOrder) => void;
    onConflict?: (conflict: WorkOrderConflict) => void;
  } = {},
) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: run,
    onSuccess: (order) => {
      queryClient.setQueryData(workOrderKey(orderId), order);
      queryClient.invalidateQueries({ queryKey: [...FIELD_KEY, "list"] });
      onSuccess?.(order);
    },
    onError: (error) => {
      if (
        !isApiError(error, "version_conflict") &&
        !isApiError(error, "invalid_work_order_action")
      ) {
        return;
      }
      const current = workOrderSchema.safeParse(error.details.work_order);
      if (current.success) {
        queryClient.setQueryData(workOrderKey(orderId), current.data);
        onConflict?.({ state: current.data.state });
      } else {
        // invalid_work_order_action carries only the state; fetch the rest.
        queryClient.invalidateQueries({ queryKey: workOrderKey(orderId) });
        const state = error.details.state;
        if (typeof state === "string") {
          onConflict?.({ state: state as WorkOrderState });
        }
      }
      queryClient.invalidateQueries({ queryKey: [...FIELD_KEY, "list"] });
    },
  });
}
