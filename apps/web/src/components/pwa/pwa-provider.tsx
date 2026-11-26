"use client";

import { WifiOff } from "lucide-react";
import { useOffline } from "next/offline";
import { useTranslations } from "next-intl";
import { useEffect } from "react";
import { useToast } from "@/components/ui/toast";
import { session } from "@/lib/api";
import {
  flushReportQueue,
  onQueueFlushed,
} from "@/lib/offline/use-report-queue";

/**
 * Registers the service worker (production builds, or NEXT_PUBLIC_SW=on
 * for testing in development) and sends queued reports whenever the
 * network or the session comes back.
 */
export function PwaProvider() {
  const { toast } = useToast();
  const t = useTranslations("offline");

  useEffect(() => {
    const enabled =
      process.env.NODE_ENV === "production" ||
      process.env.NEXT_PUBLIC_SW === "on";
    if (!enabled || !("serviceWorker" in navigator)) return;
    navigator.serviceWorker
      .register("/sw.js", { scope: "/", updateViaCache: "none" })
      .catch(() => {
        // Not fatal: the app works online without it.
      });
  }, []);

  useEffect(() => {
    const flush = () => void flushReportQueue();
    const onMessage = (event: MessageEvent) => {
      if (event.data?.type === "flush-report-queue") flush();
    };
    window.addEventListener("online", flush);
    navigator.serviceWorker?.addEventListener("message", onMessage);
    // Flush once signed in: the session is restored after load.
    const unsubscribe = session.subscribe(() => {
      if (session.getSnapshot().status === "authenticated") flush();
    });
    flush();
    return () => {
      window.removeEventListener("online", flush);
      navigator.serviceWorker?.removeEventListener("message", onMessage);
      unsubscribe();
    };
  }, []);

  useEffect(
    () =>
      onQueueFlushed(({ sent, failed }) => {
        if (sent.length) {
          toast({
            variant: "success",
            title: t("sentTitle", { count: sent.length }),
            description: t("sentDescription"),
          });
        }
        if (failed.length) {
          toast({
            variant: "error",
            title: t("failedTitle", { count: failed.length }),
            description: t("failedDescription"),
          });
        }
      }),
    [toast, t],
  );

  return <OfflineBanner />;
}

function OfflineBanner() {
  const offline = useOffline();
  const t = useTranslations("offline");
  return (
    <output aria-live="polite">
      {offline ? (
        <div className="fixed inset-x-0 bottom-0 z-50 flex items-center justify-center gap-2 bg-foreground px-4 py-2 text-background text-sm">
          <WifiOff aria-hidden className="size-4 shrink-0" />
          <span>{t("banner")}</span>
        </div>
      ) : null}
    </output>
  );
}
