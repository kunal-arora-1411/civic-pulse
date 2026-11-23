/*
 * Tile source for every map. NEXT_PUBLIC_* values are inlined at build
 * time, so read them with literal expressions. The default is the OSM
 * standard layer, which is fine for development and small pilots; a
 * production deployment should point this at its own or a commercial
 * tile server (the OSM tile usage policy forbids heavy use).
 */
export const TILE_URL =
  process.env.NEXT_PUBLIC_MAP_TILE_URL ||
  "https://tile.openstreetmap.org/{z}/{x}/{y}.png";

export const TILE_ATTRIBUTION =
  process.env.NEXT_PUBLIC_MAP_ATTRIBUTION ||
  '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';

/** Used when the tenant has no map configured yet. Bengaluru. */
export const FALLBACK_VIEW = {
  center: { lat: 12.9716, lng: 77.5946 },
  zoom: 12,
};

export type LatLng = { lat: number; lng: number };

/**
 * The API speaks GeoJSON order (`[lng, lat]`); Leaflet wants `[lat, lng]`.
 * Every conversion goes through these two helpers so the order is decided
 * in exactly one place.
 */
export function fromLngLat(tuple: readonly [number, number]): LatLng {
  return { lng: tuple[0], lat: tuple[1] };
}

export function toLeaflet(point: LatLng): [number, number] {
  return [point.lat, point.lng];
}
