import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { Suspense } from "react";
import { RequireFieldAccess } from "@/components/auth/guards";
import { WorkOrderScreen } from "@/components/field/work-order-screen";
import { PageLoading } from "@/components/page-loading";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("field.detail");
  return { title: t("metaTitle") };
}

/** Same pattern as the admin issue page: params are unwrapped in Suspense. */
export default function WorkOrderPage({
  params,
}: PageProps<"/[locale]/field/work-orders/[id]">) {
  return (
    <RequireFieldAccess>
      <Suspense fallback={<PageLoading />}>
        <WorkOrderScreen params={params} />
      </Suspense>
    </RequireFieldAccess>
  );
}
