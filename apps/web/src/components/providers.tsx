"use client";

import {
  QueryClient,
  QueryClientProvider,
  useQueryClient,
} from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { type ReactNode, useEffect, useState } from "react";
import { ToastProvider, useToast } from "@/components/ui/toast";
import { isApiError, restoreSession, session } from "@/lib/api";

function makeQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        // Retrying a 4xx won't change the answer; only retry network
        // trouble and server errors, and only briefly.
        retry: (failureCount, error) =>
          failureCount < 2 &&
          (!isApiError(error) || error.status === 0 || error.status >= 500),
      },
      mutations: { retry: false },
    },
  });
}

/**
 * Exchanges the refresh cookie for an access token once on load, and
 * drops all cached server data when the session ends so the next person
 * on a shared device can't see it.
 */
function SessionBootstrap() {
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const t = useTranslations("session");

  useEffect(() => {
    let cancelled = false;
    if (session.getSnapshot().status === "unknown") {
      restoreSession().then((result) => {
        if (!cancelled && result === "offline") {
          toast({
            variant: "error",
            title: t("offlineTitle"),
            description: t("offlineDescription"),
          });
        }
      });
    }
    return () => {
      cancelled = true;
    };
  }, [toast, t]);

  useEffect(() => {
    let previous = session.getSnapshot().status;
    return session.subscribe(() => {
      const { status } = session.getSnapshot();
      if (previous === "authenticated" && status === "anonymous") {
        queryClient.clear();
      }
      previous = status;
    });
  }, [queryClient]);

  return null;
}

export function AppProviders({ children }: { children: ReactNode }) {
  const [queryClient] = useState(makeQueryClient);
  const t = useTranslations("common");
  return (
    <QueryClientProvider client={queryClient}>
      <ToastProvider dismissLabel={t("dismissNotification")}>
        <SessionBootstrap />
        {children}
      </ToastProvider>
    </QueryClientProvider>
  );
}
