"use client";

import "leaflet/dist/leaflet.css";
import "leaflet.markercluster/dist/MarkerCluster.css";
import L from "./leaflet-global";
import "leaflet.markercluster";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  GeoJSON,
  MapContainer,
  TileLayer,
  useMap,
  useMapEvents,
} from "react-leaflet";
import { STATUS_STYLE } from "@/components/issues/status-badge";
import type { IssueFeature, JurisdictionWithGeometry } from "@/lib/api";
import type { Bbox } from "@/lib/issues/map-selection";
import {
  type LatLng,
  TILE_ATTRIBUTION,
  TILE_URL,
  toLeaflet,
} from "./map-config";
import { priorityShapeSvg } from "./priority-shapes";

/*
 * The staff map: clustered issue markers and ward outlines. Loaded only
 * through next/dynamic (ssr: false) from lazy-maps.tsx.
 */

export type IssuesMapProps = {
  features: IssueFeature[];
  wards: JurisdictionWithGeometry[];
  selectedId: string | null;
  /** Pan to this issue (a row was picked in the list). */
  focusId: string | null;
  onSelect: (id: string) => void;
  onClusterSelect: (ids: string[]) => void;
  /** minLng, minLat, maxLng, maxLat; fired after every move. */
  onBoundsChange: (bbox: Bbox) => void;
  initialView: { center: LatLng; zoom: number };
  label: string;
  /** "CP-26-000123, Reported, High priority": each marker's name. */
  markerLabel: (properties: IssueFeature["properties"]) => string;
  /** Tint markers by status (the default) or shape them by priority band. */
  styleBy?: MarkerStyle;
};

export type MarkerStyle = "status" | "priority";

function markerIcon(
  properties: IssueFeature["properties"],
  selected: boolean,
  styleBy: MarkerStyle,
) {
  const band = properties.priority_band;
  const html =
    styleBy === "priority" && band
      ? priorityShapeSvg(band)
      : `<span class="cp-dot" data-tone="${STATUS_STYLE[properties.status].variant}"></span>`;
  return L.divIcon({
    className: `cp-dot-icon${selected ? " is-selected" : ""}`,
    html,
    iconSize: selected ? [26, 26] : [18, 18],
    iconAnchor: selected ? [13, 13] : [9, 9],
  });
}

function boundsOf(map: L.Map): Bbox {
  const bounds = map.getBounds();
  return [
    bounds.getWest(),
    bounds.getSouth(),
    bounds.getEast(),
    bounds.getNorth(),
  ];
}

function Markers({
  features,
  selectedId,
  focusId,
  onSelect,
  onClusterSelect,
  onBoundsChange,
  markerLabel,
  label,
  styleBy = "status",
}: Omit<IssuesMapProps, "wards" | "initialView">) {
  const map = useMap();
  const group = useRef<L.MarkerClusterGroup | null>(null);
  const markers = useRef(new Map<string, L.Marker>());
  const callbacks = useRef({ onSelect, onClusterSelect, onBoundsChange });
  callbacks.current = { onSelect, onClusterSelect, onBoundsChange };

  useEffect(() => {
    const container = map.getContainer();
    container.setAttribute("aria-label", label);
    container.setAttribute("role", "region");
  }, [map, label]);

  useEffect(() => {
    const clusters = L.markerClusterGroup({
      showCoverageOnHover: false,
      maxClusterRadius: 50,
      chunkedLoading: true,
    });
    clusters.on("clusterclick", (event) => {
      const cluster = (event as unknown as { layer: L.MarkerCluster }).layer;
      const ids = cluster
        .getAllChildMarkers()
        .map((marker) => (marker.options as { issueId?: string }).issueId)
        .filter((id): id is string => Boolean(id));
      callbacks.current.onClusterSelect(ids);
    });
    map.addLayer(clusters);
    group.current = clusters;
    callbacks.current.onBoundsChange(boundsOf(map));
    return () => {
      map.removeLayer(clusters);
      group.current = null;
    };
  }, [map]);

  useMapEvents({
    moveend() {
      callbacks.current.onBoundsChange(boundsOf(map));
    },
  });

  // Rebuild markers when the data changes. Selection is applied below,
  // without touching the rest.
  // biome-ignore lint/correctness/useExhaustiveDependencies: selection is synced separately
  useEffect(() => {
    const clusters = group.current;
    if (!clusters) return;
    clusters.clearLayers();
    markers.current.clear();
    const layers = features.map((feature) => {
      const { id } = feature.properties;
      const [lng, lat] = feature.geometry.coordinates;
      const marker = L.marker([lat, lng], {
        icon: markerIcon(feature.properties, id === selectedId, styleBy),
        title: markerLabel(feature.properties),
        alt: markerLabel(feature.properties),
        keyboard: true,
        riseOnHover: true,
        issueId: id,
      } as L.MarkerOptions & { issueId: string });
      marker.on("click", () => callbacks.current.onSelect(id));
      markers.current.set(id, marker);
      return marker;
    });
    clusters.addLayers(layers);
  }, [features, markerLabel, styleBy]);

  const previous = useRef<string | null>(null);
  // biome-ignore lint/correctness/useExhaustiveDependencies: styleBy changes rebuild every marker above
  useEffect(() => {
    const byId = (id: string | null) => (id ? markers.current.get(id) : null);
    const properties = (id: string) =>
      features.find((feature) => feature.properties.id === id)?.properties;
    const old = byId(previous.current);
    const oldProps = previous.current
      ? properties(previous.current)
      : undefined;
    if (old && oldProps) old.setIcon(markerIcon(oldProps, false, styleBy));
    const current = byId(selectedId);
    const currentProps = selectedId ? properties(selectedId) : undefined;
    if (current && currentProps) {
      current.setIcon(markerIcon(currentProps, true, styleBy));
      current.setZIndexOffset(1000);
    }
    previous.current = selectedId;
  }, [selectedId, features]);

  useEffect(() => {
    if (!focusId) return;
    const marker = markers.current.get(focusId);
    const clusters = group.current;
    if (!marker || !clusters) return;
    // Opens the marker's cluster if needed, then pans to it.
    clusters.zoomToShowLayer(marker, () => {
      map.panTo(marker.getLatLng(), { animate: true });
    });
  }, [focusId, map]);

  return null;
}

export function IssuesMap({ wards, initialView, ...props }: IssuesMapProps) {
  const wardData = useMemo(
    () => ({
      type: "FeatureCollection" as const,
      features: wards
        .filter((ward) => ward.geometry)
        .map((ward) => ({
          type: "Feature" as const,
          properties: { name: ward.name, code: ward.code },
          geometry: ward.geometry as GeoJSON.MultiPolygon,
        })),
    }),
    [wards],
  );

  // Routes stay mounted inside <Activity>: hiding a page runs this
  // component's effect cleanups (Leaflet removes the map) and showing it
  // again re-runs the effects on the same DOM. A new key per showing gives
  // Leaflet a fresh container instead of "Map container is being reused".
  const [showing, setShowing] = useState(0);
  useEffect(() => {
    setShowing((n) => n + 1);
  }, []);
  if (showing === 0) return null;

  return (
    <MapContainer
      key={showing}
      center={toLeaflet(initialView.center)}
      zoom={initialView.zoom}
      className="size-full rounded-xl"
    >
      <TileLayer url={TILE_URL} attribution={TILE_ATTRIBUTION} />
      {wardData.features.length > 0 ? (
        <GeoJSON
          key={wards.map((ward) => ward.id).join()}
          data={wardData}
          style={{
            className: "cp-ward",
            weight: 2,
            dashArray: "6 4",
            fillOpacity: 0.04,
          }}
          onEachFeature={(feature, layer) => {
            layer.bindTooltip(String(feature.properties?.name ?? ""), {
              permanent: false,
              sticky: true,
            });
          }}
        />
      ) : null}
      <Markers {...props} />
    </MapContainer>
  );
}
