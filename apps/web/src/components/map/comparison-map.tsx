"use client";

import "leaflet/dist/leaflet.css";
import L from "leaflet";
import { useEffect, useMemo } from "react";
import {
  Circle,
  MapContainer,
  Marker,
  Polyline,
  TileLayer,
  useMap,
} from "react-leaflet";
import {
  type LatLng,
  TILE_ATTRIBUTION,
  TILE_URL,
  toLeaflet,
} from "./map-config";

/*
 * Two points on one small map: a new report and the issue it may
 * duplicate, joined by a dashed line, with the category's matching radius
 * drawn around the issue. Loaded only through next/dynamic (ssr: false).
 */

export type ComparisonMapProps = {
  report: LatLng;
  issue: LatLng;
  /** The category's matching radius, drawn around the issue. */
  radiusM: number;
  /** Text on the report's marker, e.g. "New report". */
  reportLabel: string;
  /** Text on the issue's marker: its reference. */
  issueLabel: string;
  /** Accessible name of the map region. */
  label: string;
};

function tagIcon(text: string, tone: "report" | "issue") {
  const span = document.createElement("span");
  span.className = "cp-tag";
  span.dataset.tone = tone;
  span.textContent = text;
  return L.divIcon({
    className: "cp-tag-icon",
    html: span.outerHTML,
    iconSize: undefined,
    iconAnchor: [0, 0],
  });
}

function Fit({ points, label }: { points: LatLng[]; label: string }) {
  const map = useMap();
  useEffect(() => {
    const container = map.getContainer();
    container.setAttribute("aria-label", label);
    container.setAttribute("role", "region");
  }, [map, label]);
  useEffect(() => {
    const bounds = L.latLngBounds(points.map(toLeaflet));
    map.fitBounds(bounds.pad(0.6), { maxZoom: 18, animate: false });
  }, [map, points]);
  return null;
}

export function ComparisonMap({
  report,
  issue,
  radiusM,
  reportLabel,
  issueLabel,
  label,
}: ComparisonMapProps) {
  const points = useMemo(() => [report, issue], [report, issue]);
  const icons = useMemo(
    () => ({
      report: tagIcon(reportLabel, "report"),
      issue: tagIcon(issueLabel, "issue"),
    }),
    [reportLabel, issueLabel],
  );

  return (
    <MapContainer
      center={toLeaflet(issue)}
      zoom={17}
      scrollWheelZoom={false}
      dragging={false}
      doubleClickZoom={false}
      touchZoom={false}
      keyboard={false}
      className="size-full rounded-xl"
    >
      <TileLayer url={TILE_URL} attribution={TILE_ATTRIBUTION} />
      <Fit points={points} label={label} />
      <Circle
        center={toLeaflet(issue)}
        radius={radiusM}
        pathOptions={{ className: "cp-radius", weight: 1.5, fillOpacity: 0.08 }}
      />
      <Polyline
        positions={[toLeaflet(report), toLeaflet(issue)]}
        pathOptions={{ className: "cp-link-line", weight: 2, dashArray: "5 5" }}
      />
      <Marker
        position={toLeaflet(issue)}
        icon={icons.issue}
        title={issueLabel}
        alt={issueLabel}
        keyboard={false}
      />
      <Marker
        position={toLeaflet(report)}
        icon={icons.report}
        title={reportLabel}
        alt={reportLabel}
        keyboard={false}
      />
    </MapContainer>
  );
}
