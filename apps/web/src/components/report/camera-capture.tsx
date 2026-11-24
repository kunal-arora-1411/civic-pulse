"use client";

import { Camera, SwitchCamera } from "lucide-react";
import { useTranslations } from "next-intl";
import { useEffect, useRef, useState } from "react";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Spinner } from "@/components/ui/spinner";

type Facing = "environment" | "user";
type CameraState = "starting" | "live" | "denied" | "unavailable";

/**
 * Whether the page can show a live camera itself. getUserMedia needs a
 * secure context (https or localhost); over plain http on a LAN address,
 * for example, the photo step falls back to the file input's `capture`
 * hint, which phones honour by opening their camera app.
 */
export function canUseLiveCamera(): boolean {
  return (
    typeof window !== "undefined" &&
    window.isSecureContext &&
    typeof navigator.mediaDevices?.getUserMedia === "function"
  );
}

/**
 * Takes a photo with the device camera inside the page. Desktop browsers
 * ignore the `capture` attribute and only offer a file picker, so this
 * is what makes "Take a photo" open the webcam on Windows and macOS; on
 * phones it opens the back camera.
 */
export function CameraCapture({
  open,
  onOpenChange,
  onCapture,
  onFallback,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCapture: (file: File) => void;
  /** Use the file input instead (camera blocked or missing). */
  onFallback: () => void;
}) {
  const t = useTranslations("report.photos.camera");
  const videoRef = useRef<HTMLVideoElement>(null);
  const [state, setState] = useState<CameraState>("starting");
  const [facing, setFacing] = useState<Facing>("environment");
  const [cameras, setCameras] = useState(0);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open) return;
    let stream: MediaStream | null = null;
    let cancelled = false;
    setState("starting");

    navigator.mediaDevices
      .getUserMedia({
        audio: false,
        video: {
          facingMode: { ideal: facing },
          width: { ideal: 1920 },
          height: { ideal: 1080 },
        },
      })
      .then(async (media) => {
        if (cancelled) {
          for (const track of media.getTracks()) track.stop();
          return;
        }
        stream = media;
        const video = videoRef.current;
        if (video) {
          video.srcObject = media;
          await video.play().catch(() => undefined);
        }
        setState("live");
        const devices = await navigator.mediaDevices
          .enumerateDevices()
          .catch(() => []);
        if (!cancelled) {
          setCameras(devices.filter((d) => d.kind === "videoinput").length);
        }
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        const name = error instanceof DOMException ? error.name : "";
        setState(
          name === "NotAllowedError" || name === "SecurityError"
            ? "denied"
            : "unavailable",
        );
      });

    return () => {
      cancelled = true;
      for (const track of stream?.getTracks() ?? []) track.stop();
      if (videoRef.current) videoRef.current.srcObject = null;
    };
  }, [open, facing]);

  const capture = () => {
    const video = videoRef.current;
    if (!video || !video.videoWidth) return;
    setBusy(true);
    const canvas = document.createElement("canvas");
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    canvas.getContext("2d")?.drawImage(video, 0, 0);
    canvas.toBlob(
      (blob) => {
        setBusy(false);
        if (!blob) return;
        onCapture(
          new File([blob], `photo-${Date.now()}.jpg`, {
            type: "image/jpeg",
            lastModified: Date.now(),
          }),
        );
        onOpenChange(false);
      },
      "image/jpeg",
      0.92,
    );
  };

  const failed = state === "denied" || state === "unavailable";

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={t("title")}
      closeLabel={t("close")}
      className="max-w-2xl"
      footer={
        failed ? (
          <Button
            onClick={() => {
              onOpenChange(false);
              onFallback();
            }}
          >
            {t("useFiles")}
          </Button>
        ) : (
          <>
            {cameras > 1 ? (
              <Button
                variant="outline"
                onClick={() =>
                  setFacing((value) =>
                    value === "environment" ? "user" : "environment",
                  )
                }
              >
                <SwitchCamera aria-hidden="true" />
                {t("switch")}
              </Button>
            ) : null}
            <Button
              size="lg"
              disabled={state !== "live" || busy}
              onClick={capture}
            >
              <Camera aria-hidden="true" />
              {t("capture")}
            </Button>
          </>
        )
      }
    >
      {failed ? (
        <Alert variant="warning" live="polite">
          {state === "denied" ? t("denied") : t("unavailable")}
        </Alert>
      ) : (
        <div className="relative grid aspect-[4/3] place-items-center overflow-hidden rounded-xl bg-black">
          <video
            ref={videoRef}
            playsInline
            muted
            aria-label={t("preview")}
            className={
              facing === "user"
                ? "size-full -scale-x-100 object-cover"
                : "size-full object-cover"
            }
          />
          {state === "starting" ? (
            <div className="absolute inset-0 grid place-items-center">
              <span className="grid justify-items-center gap-2 text-sm text-white/80">
                <Spinner
                  label={t("starting")}
                  className="[&_svg]:text-white/80"
                />
                <span aria-hidden="true">{t("starting")}</span>
              </span>
            </div>
          ) : null}
        </div>
      )}
    </Dialog>
  );
}
