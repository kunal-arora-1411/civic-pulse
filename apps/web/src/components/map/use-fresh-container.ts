import { useEffect, useState } from "react";

/**
 * A key for `<MapContainer>` that changes whenever the map is hidden.
 *
 * Routes stay mounted inside `<Activity>`. Hiding a route runs effect
 * cleanups (react-leaflet removes the map) but keeps the DOM, and showing
 * it again re-attaches the old container, which Leaflet refuses with "Map
 * container is being reused by another instance". Bumping the key on hide
 * lets React render a fresh container in the background, so the map that
 * comes back is a new one.
 */
export function useFreshContainerKey(): number {
  const [generation, setGeneration] = useState(0);
  useEffect(() => () => setGeneration((n) => n + 1), []);
  return generation;
}
