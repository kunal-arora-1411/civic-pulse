"use client";

import "leaflet/dist/leaflet.css";
import L from "leaflet";
import { useEffect, useMemo } from "react";
import {
  Circle,
  MapContainer,
  Marker,
  TileLayer,
  useMap,
  useMapEvents,
} from "react-leaflet";
import { cn } from "@/lib/utils";
import {
  type LatLng,
  TILE_ATTRIBUTION,
  TILE_URL,
  toLeaflet,
} from "./map-config";
import { useFreshContainerKey } from "./use-fresh-container";

/*
 * Leaflet touches `window` on import, so this module is only ever loaded
 * through next/dynamic with ssr: false (see lazy-maps.tsx). That also
 * keeps Leaflet out of the bundles of pages without a map.
 */

const PIN_SVG = `<svg viewBox="0 0 36 44" width="36" height="44" aria-hidden="true"><path d="M18 43c-1-1.6-14-15.4-14-25.2a14 14 0 1 1 28 0C32 27.6 19 41.4 18 43z" fill="var(--cp-pin-fill)" stroke="var(--cp-pin-stroke)" stroke-width="2"/><circle cx="18" cy="17.5" r="5.5" fill="var(--cp-pin-stroke)"/></svg>`;

/**
 * A div icon rather than Leaflet's default PNG marker: no image assets to
 * wire through the bundler, and it picks up the theme's colours.
 */
export const pinIcon = L.divIcon({
  className: "cp-pin",
  html: PIN_SVG,
  iconSize: [36, 44],
  iconAnchor: [18, 42],
});

export type PinMapProps = {
  center: LatLng;
  zoom: number;
  pin: LatLng | null;
  /** GPS accuracy radius drawn around the pin. */
  accuracyM?: number | null;
  /** Makes the pin draggable and the map clickable. */
  onPinChange?: (point: LatLng) => void;
  /** Reports the centre after every pan or zoom. */
  onCenterChange?: (point: LatLng) => void;
  /** Bump to pan to the pin, e.g. after a GPS fix. */
  recenterKey?: number;
  /** Accessible name of the map region. */
  label: string;
  /** Tooltip and accessible name of the pin. */
  pinLabel?: string;
  /** Small read-only maps: no scroll-wheel zoom or dragging. */
  static?: boolean;
  className?: string;
};

function MapBehaviour({
  label,
  pin,
  recenterKey,
  onPinChange,
  onCenterChange,
}: Pick<
  PinMapProps,
  "label" | "pin" | "recenterKey" | "onPinChange" | "onCenterChange"
>) {
  const map = useMap();

  useEffect(() => {
    const container = map.getContainer();
    container.setAttribute("aria-label", label);
    container.setAttribute("role", "region");
  }, [map, label]);

  // biome-ignore lint/correctness/useExhaustiveDependencies: only recenter when asked, not on every pin move
  useEffect(() => {
    if (recenterKey && pin) {
      map.setView(toLeaflet(pin), Math.max(map.getZoom(), 17));
    }
  }, [map, recenterKey]);

  useMapEvents({
    click(event) {
      onPinChange?.({ lat: event.latlng.lat, lng: event.latlng.lng });
    },
    moveend() {
      const center = map.getCenter();
      onCenterChange?.({ lat: center.lat, lng: center.lng });
    },
  });
  return null;
}

export function PinMap({
  center,
  zoom,
  pin,
  accuracyM,
  onPinChange,
  onCenterChange,
  recenterKey,
  label,
  pinLabel,
  static: isStatic = false,
  className,
}: PinMapProps) {
  const initialCenter = useMemo(() => toLeaflet(pin ?? center), [pin, center]);
  const handlers = useMemo(
    () => ({
      dragend(event: L.DragEndEvent) {
        const { lat, lng } = (event.target as L.Marker).getLatLng();
        onPinChange?.({ lat, lng });
      },
    }),
    [onPinChange],
  );

  const containerKey = useFreshContainerKey();
  return (
    <MapContainer
      key={containerKey}
      center={initialCenter}
      zoom={zoom}
      scrollWheelZoom={!isStatic}
      dragging={!isStatic}
      doubleClickZoom={!isStatic}
      touchZoom={!isStatic}
      keyboard={!isStatic}
      zoomControl={!isStatic}
      className={cn("size-full rounded-xl", className)}
    >
      <TileLayer url={TILE_URL} attribution={TILE_ATTRIBUTION} />
      <MapBehaviour
        label={label}
        pin={pin}
        recenterKey={recenterKey}
        onPinChange={onPinChange}
        onCenterChange={onCenterChange}
      />
      {pin && accuracyM && accuracyM > 0 ? (
        <Circle
          center={toLeaflet(pin)}
          radius={accuracyM}
          pathOptions={{
            className: "cp-accuracy",
            weight: 1,
            fillOpacity: 0.12,
          }}
        />
      ) : null}
      {pin ? (
        <Marker
          position={toLeaflet(pin)}
          icon={pinIcon}
          draggable={Boolean(onPinChange)}
          eventHandlers={handlers}
          title={pinLabel}
          alt={pinLabel}
          keyboard={false}
        />
      ) : null}
    </MapContainer>
  );
}
