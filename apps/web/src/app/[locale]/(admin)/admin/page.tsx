import { AdminOverview } from "@/components/admin/admin-overview";
import { RequireAdminAccess } from "@/components/auth/guards";

export default function AdminOverviewPage() {
  return (
    <RequireAdminAccess>
      <AdminOverview />
    </RequireAdminAccess>
  );
}
