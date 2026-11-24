"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { HandHeart, Users } from "lucide-react";
import { useTranslations } from "next-intl";
import { buttonVariants } from "@/components/ui/button";
import { useToast } from "@/components/ui/toast";
import { Link } from "@/i18n/navigation";
import {
  getSupport,
  isApiError,
  type SupportState,
  setSupport,
} from "@/lib/api";
import { useSession } from "@/lib/auth/use-session";
import { cn } from "@/lib/utils";

export const supportKey = (issueId: string) => ["support", issueId] as const;

export type SupportButtonProps = {
  issueId: string;
  /** The count the page already knows, shown until the caller's state loads. */
  count: number;
  /** False for closed, rejected or merged issues: the count only. */
  open?: boolean;
  /** Where sign-in should bring a signed-out visitor back to. */
  returnTo: string;
  className?: string;
};

/**
 * "I face this too". Signed-in citizens toggle it optimistically: the
 * count and the pressed state change at once and roll back if the server
 * refuses. Signed-out visitors see the count and a sign-in link. Staff
 * accounts can't support (403), so they see the count only.
 */
export function SupportButton({
  issueId,
  count,
  open = true,
  returnTo,
  className,
}: SupportButtonProps) {
  const t = useTranslations("community.support");
  const { status } = useSession();
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const signedIn = status === "authenticated";

  const query = useQuery({
    queryKey: supportKey(issueId),
    queryFn: ({ signal }) => getSupport(issueId, signal),
    enabled: signedIn && open,
  });

  const mutation = useMutation({
    mutationFn: (supported: boolean) => setSupport(issueId, supported),
    onMutate: async (supported) => {
      await queryClient.cancelQueries({ queryKey: supportKey(issueId) });
      const previous = queryClient.getQueryData<SupportState>(
        supportKey(issueId),
      );
      const base = previous?.support_count ?? count;
      queryClient.setQueryData<SupportState>(supportKey(issueId), {
        issue_id: issueId,
        supported,
        support_count: Math.max(0, base + (supported ? 1 : -1)),
      });
      return { previous };
    },
    onError: (error, _supported, context) => {
      queryClient.setQueryData(supportKey(issueId), context?.previous);
      toast({
        variant: "error",
        title: isApiError(error, "issue_merged")
          ? t("merged")
          : isApiError(error, "invalid_transition")
            ? t("closed")
            : t("failed"),
      });
    },
    onSuccess: (state) => {
      queryClient.setQueryData(supportKey(issueId), state);
    },
  });

  const state = query.data;
  const total = state?.support_count ?? count;
  const countText = (
    <span className="inline-flex items-center gap-1.5 text-sm text-muted-foreground">
      <Users aria-hidden="true" className="size-4" />
      {t("count", { count: total })}
    </span>
  );

  // Staff (403) and failed loads fall back to the count alone.
  if (!open || query.isError) {
    return <div className={cn("flex", className)}>{countText}</div>;
  }

  if (status === "unknown") {
    return (
      <div className={cn("flex flex-wrap items-center gap-3", className)}>
        <span
          aria-hidden="true"
          className="h-10 w-40 rounded-lg bg-muted motion-safe:animate-pulse"
        />
        {countText}
      </div>
    );
  }

  if (!signedIn) {
    return (
      <div className={cn("flex flex-wrap items-center gap-3", className)}>
        <Link
          href={`/login?next=${encodeURIComponent(returnTo)}`}
          className={buttonVariants({ variant: "outline" })}
        >
          <HandHeart aria-hidden="true" />
          {t("signIn")}
        </Link>
        {countText}
      </div>
    );
  }

  const supported = state?.supported ?? false;
  return (
    <div className={cn("flex flex-wrap items-center gap-3", className)}>
      <button
        type="button"
        aria-pressed={supported}
        disabled={!state}
        aria-busy={!state || undefined}
        onClick={() => mutation.mutate(!supported)}
        title={supported ? t("pressedHint") : undefined}
        className={cn(
          buttonVariants({ variant: supported ? "primary" : "outline" }),
        )}
      >
        <HandHeart aria-hidden="true" />
        {supported ? t("supported") : t("button")}
      </button>
      <output aria-live="polite">{countText}</output>
    </div>
  );
}
