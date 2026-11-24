import type { PriorityBand } from "@/lib/api";

/*
 * Map markers by priority band. Each band has its own shape as well as a
 * colour, from a diamond for critical down to a small square for low, so
 * the map and its legend read the same without colour. The markup is
 * plain SVG so Leaflet's div icons and the React legend share it.
 */

const SHAPES: Record<PriorityBand, string> = {
  critical: '<path d="M10 1.5 18.5 10 10 18.5 1.5 10Z"/>',
  high: '<path d="M10 2.5 18.5 17H1.5Z"/>',
  medium: '<circle cx="10" cy="10" r="7.5"/>',
  low: '<rect x="4.5" y="4.5" width="11" height="11" rx="1.5"/>',
};

/** The marker's SVG; colours come from `.cp-band[data-band]` in CSS. */
export function priorityShapeSvg(band: PriorityBand): string {
  return `<svg class="cp-band" data-band="${band}" viewBox="0 0 20 20" aria-hidden="true">${SHAPES[band]}</svg>`;
}

export function PriorityShape({
  band,
  className,
}: {
  band: PriorityBand;
  className?: string;
}) {
  return (
    <svg
      className={`cp-band ${className ?? ""}`}
      data-band={band}
      viewBox="0 0 20 20"
      aria-hidden="true"
      // Static, trusted markup from SHAPES above.
      // biome-ignore lint/security/noDangerouslySetInnerHtml: constant shapes, no user input
      dangerouslySetInnerHTML={{ __html: SHAPES[band] }}
    />
  );
}
