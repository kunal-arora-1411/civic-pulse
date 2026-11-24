"use client";

import { useEffect, useRef } from "react";

/** Keys are matched case-insensitively against `KeyboardEvent.key`. */
export type ShortcutMap = Record<string, () => void>;

function isTyping(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  if (target.isContentEditable) return true;
  const tag = target.tagName;
  if (tag === "TEXTAREA" || tag === "SELECT") return true;
  if (tag !== "INPUT") return false;
  const type = (target as HTMLInputElement).type;
  // Radios and checkboxes don't take text, so shortcuts still apply.
  return !["radio", "checkbox", "button", "submit", "reset"].includes(type);
}

/**
 * Single-key shortcuts for a screen, like a mail client's. They stay out
 * of the way: nothing fires while the user is typing in a field, holds a
 * modifier (so browser and screen reader shortcuts keep working), or has
 * a modal dialog open. The handlers can change on every render.
 *
 * Effects are torn down while a route is hidden inside <Activity>, so a
 * hidden screen never reacts to keys meant for the visible one.
 */
export function useShortcuts(shortcuts: ShortcutMap, enabled = true) {
  const ref = useRef(shortcuts);
  ref.current = shortcuts;

  useEffect(() => {
    if (!enabled) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.defaultPrevented || event.repeat) return;
      if (event.ctrlKey || event.metaKey || event.altKey) return;
      if (isTyping(event.target)) return;
      if (document.querySelector("dialog[open]")) return;
      const handler = ref.current[event.key.toLowerCase()];
      if (!handler) return;
      event.preventDefault();
      handler();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [enabled]);
}
