"use client";

import { useLocale } from "next-intl";
import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";

const QUERY = "(prefers-reduced-motion: reduce)";

function subscribe(onChange: () => void) {
  const list = window.matchMedia?.(QUERY);
  list?.addEventListener("change", onChange);
  return () => list?.removeEventListener("change", onChange);
}

/**
 * True when motion should be skipped. The server, and any browser without
 * matchMedia, gets true, so the first paint always shows the final state.
 */
export function useReducedMotion(): boolean {
  return useSyncExternalStore(
    subscribe,
    () => window.matchMedia?.(QUERY).matches ?? true,
    () => true,
  );
}

const TYPE_MS = 38;
const ERASE_MS = 14;
const HOLD_MS = 2400;

/**
 * The composer's example text, typing itself and cycling through a few
 * reports. Purely decorative (its container is aria-hidden); without
 * JavaScript or with reduced motion it simply shows the first example.
 */
export function TypedText({ examples }: { examples: string[] }) {
  const reduced = useReducedMotion();
  const [text, setText] = useState(examples[0] ?? "");

  useEffect(() => {
    if (reduced || examples.length < 2) return;
    let index = 0;
    let shown = examples[0]?.length ?? 0;
    let erasing = false;
    let timer: ReturnType<typeof setTimeout>;

    const step = () => {
      const current = examples[index] ?? "";
      if (!erasing && shown >= current.length) {
        erasing = true;
        timer = setTimeout(step, HOLD_MS);
        return;
      }
      if (erasing && shown === 0) {
        erasing = false;
        index = (index + 1) % examples.length;
        timer = setTimeout(step, 300);
        return;
      }
      shown += erasing ? -1 : 1;
      setText(current.slice(0, shown));
      timer = setTimeout(step, erasing ? ERASE_MS : TYPE_MS);
    };

    timer = setTimeout(step, HOLD_MS);
    return () => clearTimeout(timer);
  }, [reduced, examples]);

  return <>{text}</>;
}

/**
 * A number that counts up the first time it scrolls into view. Screen
 * readers get the final value only; the counting copy is hidden from them.
 */
export function CountUp({
  value,
  decimals = 0,
  suffix = "",
}: {
  value: number;
  decimals?: number;
  suffix?: string;
}) {
  const locale = useLocale();
  const reduced = useReducedMotion();
  const ref = useRef<HTMLSpanElement>(null);
  const [shown, setShown] = useState(value);
  const format = (n: number) =>
    `${new Intl.NumberFormat(locale === "hi" ? "en-IN" : locale, {
      minimumFractionDigits: decimals,
      maximumFractionDigits: decimals,
    }).format(n)}${suffix}`;

  // Reset before paint so the count starts from zero, not from the
  // prerendered final value.
  useLayoutEffect(() => {
    if (!reduced && typeof IntersectionObserver !== "undefined") setShown(0);
  }, [reduced]);

  useEffect(() => {
    const node = ref.current;
    if (reduced || !node || typeof IntersectionObserver === "undefined") {
      setShown(value);
      return;
    }
    let frame = 0;
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (!entry?.isIntersecting) return;
        observer.disconnect();
        const start = performance.now();
        const duration = 1400;
        const tick = (now: number) => {
          const t = Math.min(1, (now - start) / duration);
          const eased = 1 - (1 - t) ** 4;
          setShown(value * eased);
          if (t < 1) frame = requestAnimationFrame(tick);
        };
        frame = requestAnimationFrame(tick);
      },
      { threshold: 0.4 },
    );
    observer.observe(node);
    return () => {
      observer.disconnect();
      cancelAnimationFrame(frame);
    };
  }, [reduced, value]);

  return (
    <span ref={ref} className="tabular-nums">
      <span aria-hidden="true">{format(shown)}</span>
      <span className="sr-only">{format(value)}</span>
    </span>
  );
}
