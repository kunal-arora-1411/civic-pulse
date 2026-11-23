"use client";

import "leaflet/dist/leaflet.css";
import "leaflet.markercluster/dist/MarkerCluster.css";
import L from "./leaflet-global";
import "leaflet.markercluster";
import { useEffect, useMemo, useRef } from "react";
import {
  GeoJSON,
  MapContainer,
  TileLayer,
  useMap,
  useMapEvents,
} from "react-leaflet";
import { STATUS_STYLE } from "@/components/issues/status-badge";
import type {
  IssueFeature,
  IssueStatus,
  JurisdictionWithGeometry,
} from "@/lib/api";
import type { Bbox } from "@/lib/issues/map-selection";
import {
  type LatLng,
  TILE_ATTRIBUTION,
  TILE_URL,
  toLeaflet,
} from "./map-config";

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
  /** "CP-26-000123, Reported": each marker's accessible name. */
  markerLabel: (reference: string, status: IssueStatus) => string;
};

function markerIcon(status: IssueStatus, selected: boolean) {
  return L.divIcon({
    className: `cp-dot-icon${selected ? " is-selected" : ""}`,
    html: `<span class="cp-dot" data-tone="${STATUS_STYLE[status].variant}"></span>`,
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
      const { id, reference, status } = feature.properties;
      const [lng, lat] = feature.geometry.coordinates;
      const marker = L.marker([lat, lng], {
        icon: markerIcon(status, id === selectedId),
        title: markerLabel(reference, status),
        alt: markerLabel(reference, status),
        keyboard: true,
        riseOnHover: true,
        issueId: id,
      } as L.MarkerOptions & { issueId: string });
      marker.on("click", () => callbacks.current.onSelect(id));
      markers.current.set(id, marker);
      return marker;
    });
    clusters.addLayers(layers);
  }, [features, markerLabel]);

  const previous = useRef<string | null>(null);
  useEffect(() => {
    const byId = (id: string | null) => (id ? markers.current.get(id) : null);
    const status = (id: string) =>
      features.find((feature) => feature.properties.id === id)?.properties
        .status;
    const old = byId(previous.current);
    const oldStatus = previous.current ? status(previous.current) : undefined;
    if (old && oldStatus) old.setIcon(markerIcon(oldStatus, false));
    const current = byId(selectedId);
    const currentStatus = selectedId ? status(selectedId) : undefined;
    if (current && currentStatus) {
      current.setIcon(markerIcon(currentStatus, true));
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

  return (
    <MapContainer
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
