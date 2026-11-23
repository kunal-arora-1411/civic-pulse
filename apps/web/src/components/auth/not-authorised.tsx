"use client";

import { ShieldX } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { Button, buttonVariants } from "@/components/ui/button";
import { Link, useRouter } from "@/i18n/navigation";
import { type CurrentUser, logout } from "@/lib/api";
import { homePathFor } from "@/lib/auth/access";
import { formatIndianPhone } from "@/lib/phone";

/**
 * Shown when a signed-in user opens a page their role doesn't cover. The
 * API would refuse the data anyway; this explains why the page is empty
 * and offers a way out.
 */
export function NotAuthorised({ user }: { user: CurrentUser }) {
  const t = useTranslations("access");
  const router = useRouter();
  const [signingOut, setSigningOut] = useState(false);
  const home = homePathFor(user);

  return (
    <section
      aria-labelledby="not-authorised-title"
      className="mx-auto grid max-w-lg justify-items-center gap-4 px-4 py-16 text-center"
    >
      <span className="grid size-14 place-items-center rounded-2xl bg-destructive-soft text-destructive-soft-foreground">
        <ShieldX aria-hidden="true" className="size-7" />
      </span>
      <h1 id="not-authorised-title" className="text-2xl font-semibold">
        {t("title")}
      </h1>
      <p className="text-muted-foreground">
        {t("body", {
          name: user.display_name || formatIndianPhone(user.phone),
        })}
      </p>
      <div className="flex flex-wrap justify-center gap-3">
        <Link href={home} className={buttonVariants()}>
          {t("goHome")}
        </Link>
        <Button
          variant="outline"
          loading={signingOut}
          onClick={async () => {
            setSigningOut(true);
            await logout();
            router.replace("/login");
          }}
        >
          {t("switchAccount")}
        </Button>
      </div>
    </section>
  );
}
