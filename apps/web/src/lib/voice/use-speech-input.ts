"use client";

import { useCallback, useEffect, useRef, useState } from "react";

/*
 * Voice input for the report description (P6-02, FR-013), on the
 * browser's own speech recognition (Web Speech API). What the citizen says
 * is appended to the text box as a transcript they can edit before
 * sending; no audio is stored or sent to CivicPulse. Browsers without the
 * API (Firefox, for one) don't get the button.
 *
 * A server-side engine (Bhashini or faster-whisper) can replace this later
 * behind the same hook, for regional languages the browsers don't cover.
 */

type RecognitionResult = { isFinal: boolean; 0: { transcript: string } };
type RecognitionEvent = {
  resultIndex: number;
  results: ArrayLike<RecognitionResult>;
};
type Recognition = {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  onresult: ((event: RecognitionEvent) => void) | null;
  onerror: ((event: { error: string }) => void) | null;
  onend: (() => void) | null;
  start(): void;
  stop(): void;
  abort(): void;
};
type RecognitionConstructor = new () => Recognition;

function recognitionConstructor(): RecognitionConstructor | null {
  if (typeof window === "undefined") return null;
  const w = window as unknown as {
    SpeechRecognition?: RecognitionConstructor;
    webkitSpeechRecognition?: RecognitionConstructor;
  };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

/** BCP 47 tags for recognition; Indian English and Hindi by default. */
export function speechLang(locale: string): string {
  if (locale.includes("-")) return locale;
  return `${locale}-IN`;
}

/** Add a spoken phrase to what's already typed, with one space between. */
export function appendTranscript(current: string, spoken: string): string {
  const addition = spoken.trim();
  if (!addition) return current;
  if (!current.trim()) return addition;
  return /\s$/.test(current) ? current + addition : `${current} ${addition}`;
}

export type SpeechError = "not-allowed" | "no-speech" | "network" | "other";

export function useSpeechInput({
  locale,
  onFinal,
}: {
  locale: string;
  onFinal: (text: string) => void;
}) {
  const [supported, setSupported] = useState(false);
  const [listening, setListening] = useState(false);
  const [interim, setInterim] = useState("");
  const [error, setError] = useState<SpeechError | null>(null);
  const recognition = useRef<Recognition | null>(null);
  const onFinalRef = useRef(onFinal);
  onFinalRef.current = onFinal;

  // Feature-detect after mount, so server and first client render agree.
  useEffect(() => {
    setSupported(recognitionConstructor() !== null);
    return () => recognition.current?.abort();
  }, []);

  const stop = useCallback(() => {
    recognition.current?.stop();
  }, []);

  const start = useCallback(() => {
    const Ctor = recognitionConstructor();
    if (!Ctor || recognition.current) return;
    const r = new Ctor();
    r.lang = speechLang(locale);
    r.continuous = true;
    r.interimResults = true;
    r.onresult = (event) => {
      let pending = "";
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const result = event.results[i];
        if (result.isFinal) onFinalRef.current(result[0].transcript);
        else pending += result[0].transcript;
      }
      setInterim(pending);
    };
    r.onerror = (event) => {
      const known: SpeechError[] = ["not-allowed", "no-speech", "network"];
      setError(
        known.includes(event.error as SpeechError)
          ? (event.error as SpeechError)
          : event.error === "service-not-allowed"
            ? "not-allowed"
            : "other",
      );
    };
    r.onend = () => {
      recognition.current = null;
      setListening(false);
      setInterim("");
    };
    setError(null);
    recognition.current = r;
    try {
      r.start();
      setListening(true);
    } catch {
      recognition.current = null;
      setError("other");
    }
  }, [locale]);

  return { supported, listening, interim, error, start, stop };
}
