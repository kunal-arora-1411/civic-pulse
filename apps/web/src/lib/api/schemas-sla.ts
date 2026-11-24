import { z } from "zod";
import { priorityBandSchema } from "./schemas-ai";

/* SLA targets and per-issue deadlines (docs/api/sla-escalation.md). */

export const SLA_STATES = ["none", "on_track", "due_soon", "overdue"] as const;
export const slaStateSchema = z.enum(SLA_STATES);
export type SlaState = z.infer<typeof slaStateSchema>;

export const slaTargetInSchema = z.object({
  category_id: z.string(),
  /** Null: every band without a narrower target. */
  priority_band: priorityBandSchema.nullable(),
  resolve_hours: z.number().int(),
  escalate_after_hours: z.number().int(),
});
export type SlaTargetIn = z.infer<typeof slaTargetInSchema>;

export const slaTargetSchema = slaTargetInSchema.extend({ id: z.string() });
export type SlaTarget = z.infer<typeof slaTargetSchema>;

export const slaTargetsSchema = z.object({ items: z.array(slaTargetSchema) });
export type SlaTargets = z.infer<typeof slaTargetsSchema>;
