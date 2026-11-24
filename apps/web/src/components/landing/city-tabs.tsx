"use client";

import {
  type KeyboardEvent,
  type ReactNode,
  useId,
  useRef,
  useState,
} from "react";
import { cn } from "@/lib/utils";

/**
 * Tabs over the console illustrations (WAI-ARIA tabs pattern: arrow keys
 * move between tabs, only the selected one is in the tab order). The
 * panels are rendered on the server and passed in.
 */
export function CityTabs({
  label,
  tabs,
}: {
  label: string;
  tabs: { label: string; panel: ReactNode }[];
}) {
  const [selected, setSelected] = useState(0);
  const id = useId();
  const refs = useRef<(HTMLButtonElement | null)[]>([]);

  const onKeyDown = (event: KeyboardEvent) => {
    const last = tabs.length - 1;
    const keys: Record<string, number> = {
      ArrowRight: selected === last ? 0 : selected + 1,
      ArrowLeft: selected === 0 ? last : selected - 1,
      Home: 0,
      End: last,
    };
    const next = keys[event.key];
    if (next === undefined) return;
    event.preventDefault();
    setSelected(next);
    refs.current[next]?.focus();
  };

  return (
    <div className="grid gap-6">
      <div
        role="tablist"
        aria-label={label}
        onKeyDown={onKeyDown}
        className="flex w-fit max-w-full gap-0.5 overflow-x-auto rounded-xl border border-white/10 bg-white/[0.06] p-1"
      >
        {tabs.map((tab, index) => (
          <button
            key={tab.label}
            ref={(node) => {
              refs.current[index] = node;
            }}
            type="button"
            role="tab"
            id={`${id}-tab-${index}`}
            aria-selected={index === selected}
            aria-controls={`${id}-panel-${index}`}
            tabIndex={index === selected ? 0 : -1}
            onClick={() => setSelected(index)}
            className={cn(
              "rounded-[9px] px-4 py-2 text-sm font-medium whitespace-nowrap transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-lp-mint",
              index === selected
                ? "bg-white text-lp-ink"
                : "text-white/70 hover:text-white",
            )}
          >
            {tab.label}
          </button>
        ))}
      </div>
      {tabs.map((tab, index) => (
        <div
          key={tab.label}
          role="tabpanel"
          id={`${id}-panel-${index}`}
          aria-labelledby={`${id}-tab-${index}`}
          hidden={index !== selected}
        >
          {tab.panel}
        </div>
      ))}
    </div>
  );
}
