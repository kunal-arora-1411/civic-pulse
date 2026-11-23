import { apiRequest } from "../client";
import { type Tenant, tenantSchema } from "../schemas";

export function getCurrentTenant(signal?: AbortSignal): Promise<Tenant> {
  return apiRequest({
    path: "/tenants/current",
    schema: tenantSchema,
    auth: false,
    signal,
  });
}
