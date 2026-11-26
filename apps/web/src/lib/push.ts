/*
 * Web Push in the browser: register the service worker, ask permission,
 * subscribe with the server's VAPID key and hand the subscription to the
 * API. Everything degrades: an unsupported browser, a denied permission or
 * a server without push configured each leave the rest of the page usable.
 */

import {
  deletePushSubscription,
  savePushSubscription,
} from "@/lib/api/endpoints/notifications";

export const SERVICE_WORKER_URL = "/sw.js";

export type PushState =
  | "unsupported"
  | "denied"
  | "subscribed"
  | "unsubscribed";

export function pushSupported(): boolean {
  return (
    typeof window !== "undefined" &&
    "serviceWorker" in navigator &&
    "PushManager" in window &&
    "Notification" in window
  );
}

/** The VAPID key arrives as base64url; `subscribe` wants the raw bytes. */
export function urlBase64ToUint8Array(value: string): Uint8Array<ArrayBuffer> {
  const padded = value + "=".repeat((4 - (value.length % 4)) % 4);
  const binary = atob(padded.replace(/-/g, "+").replace(/_/g, "/"));
  const bytes = new Uint8Array(new ArrayBuffer(binary.length));
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
  return bytes;
}

async function registration(): Promise<ServiceWorkerRegistration> {
  return (
    (await navigator.serviceWorker.getRegistration(SERVICE_WORKER_URL)) ??
    navigator.serviceWorker.register(SERVICE_WORKER_URL)
  );
}

async function currentSubscription(): Promise<PushSubscription | null> {
  const existing =
    await navigator.serviceWorker.getRegistration(SERVICE_WORKER_URL);
  return existing ? existing.pushManager.getSubscription() : null;
}

export async function pushState(): Promise<PushState> {
  if (!pushSupported()) return "unsupported";
  if (Notification.permission === "denied") return "denied";
  return (await currentSubscription()) ? "subscribed" : "unsubscribed";
}

function toBody(subscription: PushSubscription) {
  const json = subscription.toJSON();
  return {
    endpoint: subscription.endpoint,
    keys: { p256dh: json.keys?.p256dh ?? "", auth: json.keys?.auth ?? "" },
  };
}

/** Ask permission, subscribe and register with the API. */
export async function enablePush(publicKey: string): Promise<PushState> {
  if (!pushSupported()) return "unsupported";
  const permission = await Notification.requestPermission();
  if (permission !== "granted") {
    return permission === "denied" ? "denied" : "unsubscribed";
  }
  const reg = await registration();
  await navigator.serviceWorker.ready;
  const subscription =
    (await reg.pushManager.getSubscription()) ??
    (await reg.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlBase64ToUint8Array(publicKey),
    }));
  try {
    await savePushSubscription(toBody(subscription));
  } catch (error) {
    // Don't leave a subscription the server never heard of.
    await subscription.unsubscribe().catch(() => undefined);
    throw error;
  }
  return "subscribed";
}

export async function disablePush(): Promise<PushState> {
  const subscription = await currentSubscription();
  if (subscription) {
    await deletePushSubscription(subscription.endpoint);
    await subscription.unsubscribe();
  }
  return "unsubscribed";
}
