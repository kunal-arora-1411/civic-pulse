"use client";

import "leaflet/dist/leaflet.css";
import { cellToBoundary } from "h3-js";
import L from "leaflet";
import { useEffect, useMemo } from "react";
import {
  MapContainer,
  Polygon,
  TileLayer,
  Tooltip,
  useMap,
} from "react-leaflet";
import {
  type LatLng,
  TILE_ATTRIBUTION,
  TILE_URL,
  toLeaflet,
} from "./map-config";

/*
 * Issue density as H3 hexagons: one cell per hotspot, more opaque where
 * there are more issues (one hue, so the scale reads light to dark). The
 * colour comes from the .cp-hotspot rule, which follows the theme. Loaded
 * only through next/dynamic (ssr: false).
 */

export type HotspotCell = {
  cell: string;
  issues: number;
  open: number;
  /** Tooltip text, already translated. */
  label: string;
};

export type HotspotMapProps = {
  cells: HotspotCell[];
  center: LatLng;
  zoom: number;
  /** Accessible name of the map region. */
  label: string;
};

function Setup({
  label,
  bounds,
}: {
  label: string;
  bounds: L.LatLngBounds | null;
}) {
  const map = useMap();
  useEffect(() => {
    const container = map.getContainer();
    container.setAttribute("aria-label", label);
    container.setAttribute("role", "region");
  }, [map, label]);
  useEffect(() => {
    if (bounds?.isValid()) map.fitBounds(bounds.pad(0.15), { animate: false });
  }, [map, bounds]);
  return null;
}

export function HotspotMap({ cells, center, zoom, label }: HotspotMapProps) {
  const max = Math.max(1, ...cells.map((c) => c.issues));
  const shapes = useMemo(
    () =>
      cells.map((c) => ({
        ...c,
        // h3-js returns [lat, lng] pairs, which is Leaflet's order already.
        positions: cellToBoundary(c.cell) as [number, number][],
      })),
    [cells],
  );
  const bounds = useMemo(
    () =>
      shapes.length ? L.latLngBounds(shapes.flatMap((s) => s.positions)) : null,
    [shapes],
  );
  return (
    <MapContainer
      center={toLeaflet(center)}
      zoom={zoom}
      scrollWheelZoom={false}
      className="size-full rounded-lg"
    >
      <TileLayer url={TILE_URL} attribution={TILE_ATTRIBUTION} />
      <Setup label={label} bounds={bounds} />
      {shapes.map((s) => (
        <Polygon
          key={s.cell}
          positions={s.positions}
          pathOptions={{
            className: "cp-hotspot",
            weight: 1,
            fillOpacity: 0.15 + (0.7 * s.issues) / max,
          }}
        >
          <Tooltip sticky>{s.label}</Tooltip>
        </Polygon>
      ))}
    </MapContainer>
  );
}
