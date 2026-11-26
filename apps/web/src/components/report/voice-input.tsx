"use client";

import { Mic, Square } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { Button } from "@/components/ui/button";
import { useSpeechInput } from "@/lib/voice/use-speech-input";

/** "Speak instead" for the description; renders nothing without support. */
export function VoiceInput({ onText }: { onText: (spoken: string) => void }) {
  const t = useTranslations("report.voice");
  const locale = useLocale();
  const speech = useSpeechInput({ locale, onFinal: onText });

  if (!speech.supported) return null;

  return (
    <div className="grid gap-1">
      <div className="flex flex-wrap items-center gap-2">
        <Button
          type="button"
          variant={speech.listening ? "destructive" : "outline"}
          size="sm"
          aria-pressed={speech.listening}
          onClick={speech.listening ? speech.stop : speech.start}
        >
          {speech.listening ? (
            <Square aria-hidden="true" />
          ) : (
            <Mic aria-hidden="true" />
          )}
          {speech.listening ? t("stop") : t("start")}
        </Button>
        <output aria-live="polite" className="text-sm text-muted-foreground">
          {speech.listening ? speech.interim || t("listening") : ""}
          {speech.error ? t(`error.${speech.error}`) : ""}
        </output>
      </div>
      <p className="text-xs text-muted-foreground">{t("privacy")}</p>
    </div>
  );
}
