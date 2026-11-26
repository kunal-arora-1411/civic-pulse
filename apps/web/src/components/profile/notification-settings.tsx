"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BellRing } from "lucide-react";
import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Skeleton } from "@/components/ui/skeleton";
import { useErrorMessage } from "@/hooks/use-error-message";
import {
  DELIVERY_CHANNELS,
  getNotificationPreferences,
  type NotificationPreferences,
  type PreferenceChange,
  updateNotificationPreferences,
} from "@/lib/api";
import { disablePush, enablePush, type PushState, pushState } from "@/lib/push";

export const preferencesKey = ["notification-preferences"] as const;

function BrowserPush({ publicKey }: { publicKey: string | null }) {
  const t = useTranslations("profile.notifications");
  const errorMessage = useErrorMessage();
  const [state, setState] = useState<PushState | null>(null);

  useEffect(() => {
    let live = true;
    pushState()
      .then((value) => {
        if (live) setState(value);
      })
      .catch(() => {
        if (live) setState("unsupported");
      });
    return () => {
      live = false;
    };
  }, []);

  const toggle = useMutation({
    mutationFn: () =>
      state === "subscribed" || !publicKey
        ? disablePush()
        : enablePush(publicKey),
    onSuccess: setState,
  });

  let message: string;
  if (!publicKey) message = t("pushOff");
  else if (state === "unsupported") message = t("pushUnsupported");
  else if (state === "denied") message = t("pushDenied");
  else if (state === "subscribed") message = t("pushOn");
  else message = t("pushAsk");

  const canToggle =
    publicKey !== null && (state === "subscribed" || state === "unsubscribed");

  return (
    <div className="grid gap-3 rounded-lg border border-border p-4">
      <div className="flex items-start gap-3">
        <span className="grid size-10 shrink-0 place-items-center rounded-lg bg-secondary text-secondary-foreground">
          <BellRing aria-hidden="true" className="size-5" />
        </span>
        <div className="grid gap-0.5">
          <p className="text-sm font-semibold">{t("pushTitle")}</p>
          <p className="text-sm text-muted-foreground" aria-live="polite">
            {state === null && publicKey ? t("pushChecking") : message}
          </p>
        </div>
      </div>
      {canToggle ? (
        <div>
          <Button
            variant={state === "subscribed" ? "outline" : "primary"}
            loading={toggle.isPending}
            onClick={() => toggle.mutate()}
          >
            {state === "subscribed" ? t("pushDisable") : t("pushEnable")}
          </Button>
        </div>
      ) : null}
      {toggle.isError ? (
        <Alert variant="destructive" live="assertive">
          {errorMessage(toggle.error)}
        </Alert>
      ) : null}
    </div>
  );
}

function Matrix({ preferences }: { preferences: NotificationPreferences }) {
  const t = useTranslations("profile.notifications");
  const errorMessage = useErrorMessage();
  const queryClient = useQueryClient();

  const save = useMutation({
    mutationFn: (change: PreferenceChange) =>
      updateNotificationPreferences([change]),
    onSuccess: (updated) => {
      queryClient.setQueryData(preferencesKey, updated);
    },
  });

  return (
    <div className="grid gap-3">
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <caption className="sr-only">{t("tableCaption")}</caption>
          <thead>
            <tr className="border-b border-border text-left">
              <th scope="col" className="py-2 pr-4 font-semibold">
                {t("kindColumn")}
              </th>
              {DELIVERY_CHANNELS.map((channel) => (
                <th
                  key={channel}
                  scope="col"
                  className="px-3 py-2 text-center font-semibold"
                >
                  {t(`channels.${channel}`)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {preferences.items.map((item) => (
              <tr key={item.kind} className="border-b border-border">
                <th scope="row" className="py-3 pr-4 text-left font-normal">
                  {t(`kinds.${item.kind}`)}
                </th>
                {DELIVERY_CHANNELS.map((channel) => {
                  const choice = item.channels.find(
                    (c) => c.channel === channel,
                  );
                  return (
                    <td key={channel} className="px-3 py-3 text-center">
                      {choice ? (
                        <Checkbox
                          checked={choice.enabled}
                          disabled={save.isPending}
                          aria-label={t("toggleLabel", {
                            kind: t(`kinds.${item.kind}`),
                            channel: t(`channels.${channel}`),
                          })}
                          onChange={(event) =>
                            save.mutate({
                              kind: item.kind,
                              channel,
                              enabled: event.target.checked,
                            })
                          }
                        />
                      ) : (
                        <>
                          <span aria-hidden="true">—</span>
                          <span className="sr-only">{t("notOffered")}</span>
                        </>
                      )}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {!preferences.available.email ? (
        <p className="text-sm text-muted-foreground">{t("emailUnavailable")}</p>
      ) : null}
      <p className="sr-only" aria-live="polite">
        {save.isSuccess ? t("saved") : ""}
      </p>
      {save.isError ? (
        <Alert variant="destructive" live="assertive">
          {errorMessage(save.error)}
        </Alert>
      ) : null}
    </div>
  );
}

export function NotificationSettings() {
  const t = useTranslations("profile.notifications");
  const errorMessage = useErrorMessage();
  const query = useQuery({
    queryKey: preferencesKey,
    queryFn: ({ signal }) => getNotificationPreferences(signal),
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("title")}</CardTitle>
        <CardDescription>{t("description")}</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-5">
        {query.isPending ? (
          <div className="grid gap-2" aria-busy="true">
            <span className="sr-only">{t("loading")}</span>
            <Skeleton className="h-10" />
            <Skeleton className="h-24" />
          </div>
        ) : query.isError ? (
          <Alert variant="destructive" live="assertive">
            {errorMessage(query.error)}
          </Alert>
        ) : (
          <>
            <BrowserPush publicKey={query.data.push_public_key} />
            <Matrix preferences={query.data} />
          </>
        )}
      </CardContent>
    </Card>
  );
}
