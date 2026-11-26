import { tenantsGetCurrent } from "@civicpulse/api-client";
import { call } from "../generated-client";
import { type Tenant, tenantSchema } from "../schemas";

export function getCurrentTenant(signal?: AbortSignal): Promise<Tenant> {
  return call(tenantSchema, (o) => tenantsGetCurrent(o), {
    auth: false,
    signal,
  });
}
