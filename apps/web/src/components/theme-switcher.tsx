"use client";

import { Monitor, Moon, Sun } from "lucide-react";
import { useTranslations } from "next-intl";
import { useId, useSyncExternalStore } from "react";
import { cn } from "@/lib/utils";

export type ThemeChoice = "system" | "light" | "dark";

export const THEME_STORAGE_KEY = "theme";

/**
 * Runs in <head> before first paint (see the root layout), so a saved
 * light or dark choice is applied without a flash and pages stay
 * statically prerendered. Keep it tiny and dependency-free.
 */
export const themeScript = `(function(){try{var t=localStorage.getItem("${THEME_STORAGE_KEY}");if(t==="light"||t==="dark")document.documentElement.setAttribute("data-theme",t)}catch(e){}})()`;

const EVENT = "civicpulse:theme";

function read(): ThemeChoice {
  try {
    const value = localStorage.getItem(THEME_STORAGE_KEY);
    return value === "light" || value === "dark" ? value : "system";
  } catch {
    return "system";
  }
}

function subscribe(onChange: () => void) {
  window.addEventListener(EVENT, onChange);
  window.addEventListener("storage", onChange);
  return () => {
    window.removeEventListener(EVENT, onChange);
    window.removeEventListener("storage", onChange);
  };
}

export function applyTheme(choice: ThemeChoice) {
  try {
    if (choice === "system") localStorage.removeItem(THEME_STORAGE_KEY);
    else localStorage.setItem(THEME_STORAGE_KEY, choice);
  } catch {
    // Private mode or blocked storage: the choice lasts for this page only.
  }
  const root = document.documentElement;
  if (choice === "system") root.removeAttribute("data-theme");
  else root.setAttribute("data-theme", choice);
  window.dispatchEvent(new Event(EVENT));
}

const options = [
  { value: "system", icon: Monitor },
  { value: "light", icon: Sun },
  { value: "dark", icon: Moon },
] as const;

/**
 * Light, dark, or follow the device. Native radios (keyboard behaviour
 * for free) styled as a compact icon toggle; each has a text label for
 * assistive technology and a tooltip.
 */
export function ThemeSwitcher({ className }: { className?: string }) {
  const t = useTranslations("theme");
  const name = useId();
  const choice = useSyncExternalStore(subscribe, read, () => "system");

  return (
    <fieldset
      className={cn(
        "m-0 flex h-9 min-w-0 items-center gap-0.5 rounded-full border border-border bg-muted p-0.5",
        className,
      )}
    >
      <legend className="sr-only">{t("label")}</legend>
      {options.map(({ value, icon: Icon }) => (
        <label
          key={value}
          title={t(value)}
          className={cn(
            "grid size-7 cursor-pointer place-items-center rounded-full text-muted-foreground transition-colors hover:text-foreground",
            "has-checked:bg-card has-checked:text-foreground has-checked:shadow-card",
            "has-focus-visible:outline-2 has-focus-visible:outline-offset-1 has-focus-visible:outline-ring",
          )}
        >
          <input
            type="radio"
            name={name}
            value={value}
            checked={choice === value}
            onChange={() => applyTheme(value)}
            className="sr-only"
          />
          <Icon aria-hidden="true" className="size-4" />
          <span className="sr-only">{t(value)}</span>
        </label>
      ))}
    </fieldset>
  );
}
