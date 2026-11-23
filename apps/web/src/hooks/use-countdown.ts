"use client";

import { useEffect, useState } from "react";

/** Whole seconds left until `deadline` (epoch ms), ticking once a second. */
export function useCountdown(deadline: number | null): number {
  const compute = () =>
    deadline === null
      ? 0
      : Math.max(0, Math.ceil((deadline - Date.now()) / 1000));
  const [remaining, setRemaining] = useState(compute);

  // biome-ignore lint/correctness/useExhaustiveDependencies: compute only depends on deadline
  useEffect(() => {
    setRemaining(compute());
    if (deadline === null) return;
    const timer = setInterval(() => {
      const next = compute();
      setRemaining(next);
      if (next === 0) clearInterval(timer);
    }, 1000);
    return () => clearInterval(timer);
  }, [deadline]);

  return remaining;
}

/** 75 → "1:15" */
export function formatSeconds(total: number): string {
  const minutes = Math.floor(total / 60);
  const seconds = total % 60;
  return `${minutes}:${seconds.toString().padStart(2, "0")}`;
}
