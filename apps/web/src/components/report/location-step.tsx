"use client";

import {
  Crosshair,
  LocateFixed,
  MapPin,
  MapPinned,
  Navigation,
} from "lucide-react";
import { useTranslations } from "next-intl";
import { useCallback, useId, useRef, useState } from "react";
import { PinMap } from "@/components/map/lazy-maps";
import type { LatLng } from "@/components/map/map-config";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Skeleton } from "@/components/ui/skeleton";
import type { MapView } from "@/hooks/use-reference-data";
import type { ReverseGeocode } from "@/lib/api";
import type { DraftLocation } from "@/lib/report/draft";
import {
  type GeoCheck,
  LOW_ACCURACY_M,
  type LocationIssue,
} from "@/lib/report/validation";

type GpsState =
  | { status: "idle" }
  | { status: "locating" }
  | { status: "found"; accuracy: number }
  | { status: "denied" | "unavailable" | "unsupported" };

export function LocationStep({
  location,
  onChange,
  geo,
  geoData,
  mapView,
  cityName,
  issue,
}: {
  location: DraftLocation | null;
  onChange: (location: DraftLocation) => void;
  geo: GeoCheck;
  geoData: ReverseGeocode | undefined;
  mapView: MapView;
  cityName: string | null;
  /** Shown once the citizen has tried to continue (blocking ones always). */
  issue: LocationIssue | null;
}) {
  const t = useTranslations("report.location");
  const [gps, setGps] = useState<GpsState>({ status: "idle" });
  const [manual, setManual] = useState(location !== null);
  const [recenterKey, setRecenterKey] = useState(0);
  const mapCenter = useRef<LatLng>(location ?? mapView.center);
  const confirmId = useId();

  const locate = useCallback(() => {
    if (!("geolocation" in navigator)) {
      setGps({ status: "unsupported" });
      setManual(true);
      return;
    }
    setGps({ status: "locating" });
    navigator.geolocation.getCurrentPosition(
      (position) => {
        const accuracy = Math.round(position.coords.accuracy);
        setGps({ status: "found", accuracy });
        onChange({
          lat: position.coords.latitude,
          lng: position.coords.longitude,
          accuracyM: accuracy,
          source: "gps",
        });
        setRecenterKey((key) => key + 1);
      },
      (error) => {
        setGps({
          status:
            error.code === error.PERMISSION_DENIED ? "denied" : "unavailable",
        });
        setManual(true);
      },
      // maximumAge 0: "find my location again" must not return the cached
      // fix the citizen is trying to replace.
      { enableHighAccuracy: true, timeout: 15_000, maximumAge: 0 },
    );
  }, [onChange]);

  // A pin the citizen moved is no longer a raw GPS fix: record it as
  // placed by hand, without the GPS accuracy (provenance, PRD §10.2).
  const movePin = useCallback(
    (point: LatLng) => onChange({ ...point, accuracyM: null, source: "pin" }),
    [onChange],
  );

  const showMap = manual || location !== null || gps.status === "locating";
  const lowAccuracy =
    location?.source === "gps" &&
    location.accuracyM !== null &&
    location.accuracyM > LOW_ACCURACY_M;

  return (
    <div className="grid gap-5">
      {location === null && gps.status !== "locating" && !manual ? (
        <div className="grid gap-4 rounded-xl border border-border bg-card p-5 shadow-card">
          <div className="flex gap-3">
            <span className="grid size-11 shrink-0 place-items-center rounded-xl bg-primary-soft text-primary-soft-foreground">
              <MapPinned aria-hidden="true" className="size-5" />
            </span>
            <div className="grid gap-1">
              <h3 className="font-semibold">{t("consentTitle")}</h3>
              <p className="text-sm text-muted-foreground">
                {t("consentBody")}
              </p>
            </div>
          </div>
          <div className="grid gap-2 sm:grid-cols-2">
            <Button size="lg" onClick={locate}>
              <LocateFixed aria-hidden="true" />
              {t("useGps")}
            </Button>
            <Button size="lg" variant="outline" onClick={() => setManual(true)}>
              <MapPin aria-hidden="true" />
              {t("placeManually")}
            </Button>
          </div>
        </div>
      ) : null}

      <div aria-live="polite" className="empty:hidden">
        {gps.status === "locating" ? (
          <p className="flex items-center gap-2 text-sm font-medium">
            <Navigation
              aria-hidden="true"
              className="size-4 text-primary motion-safe:animate-pulse"
            />
            {t("locating")}
          </p>
        ) : gps.status === "found" && location?.source === "gps" ? (
          <p className="flex items-center gap-2 text-sm font-semibold text-primary">
            <LocateFixed aria-hidden="true" className="size-4" />
            {t("found", { meters: gps.accuracy })}
          </p>
        ) : gps.status === "denied" ||
          gps.status === "unavailable" ||
          gps.status === "unsupported" ? (
          <Alert variant="info">{t(gps.status)}</Alert>
        ) : null}
      </div>

      {showMap && !mapView.configured ? (
        <Alert variant="info">{t("noCityMap")}</Alert>
      ) : null}

      {showMap ? (
        <div className="grid gap-3">
          <p className="text-sm text-muted-foreground">
            {location ? t("mapHelp") : t("tapToPlace")}
          </p>
          <div className="h-72 overflow-hidden rounded-xl border border-border sm:h-96">
            <PinMap
              center={mapView.center}
              zoom={location ? 17 : mapView.zoom}
              pin={location}
              accuracyM={location?.source === "gps" ? location.accuracyM : null}
              onPinChange={movePin}
              onCenterChange={(center) => {
                mapCenter.current = center;
              }}
              recenterKey={recenterKey}
              label={t("mapLabel")}
              pinLabel={t("pinLabel")}
            />
          </div>
          <div className="flex flex-wrap gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => movePin(mapCenter.current)}
            >
              <Crosshair aria-hidden="true" />
              {t("pinToCenter")}
            </Button>
            {gps.status !== "locating" ? (
              <Button variant="ghost" size="sm" onClick={locate}>
                <LocateFixed aria-hidden="true" />
                {location?.source === "gps" ? t("locateAgain") : t("useGps")}
              </Button>
            ) : null}
          </div>
        </div>
      ) : null}

      {location ? (
        <dl
          aria-live="polite"
          className="grid gap-3 rounded-xl border border-border bg-card p-4 text-sm sm:grid-cols-2"
        >
          <div className="grid gap-0.5">
            <dt className="font-semibold text-muted-foreground">
              {t("address")}
            </dt>
            <dd>
              {geo.status === "pending" ? (
                <>
                  <span className="sr-only">{t("lookingUp")}</span>
                  <Skeleton className="mt-1 h-4 w-48" />
                </>
              ) : geo.status === "unavailable" ? (
                t("lookupFailed")
              ) : (
                geoData?.address_text || t("noAddress")
              )}
            </dd>
          </div>
          <div className="grid gap-0.5">
            <dt className="font-semibold text-muted-foreground">{t("ward")}</dt>
            <dd>
              {geo.status === "pending" ? (
                <Skeleton className="mt-1 h-4 w-24" />
              ) : (
                geoData?.ward?.name || "—"
              )}
            </dd>
          </div>
        </dl>
      ) : null}

      {issue === "out_of_jurisdiction" ? (
        <Alert variant="destructive" live="assertive" title={t("outsideTitle")}>
          {cityName ? t("outside", { city: cityName }) : t("outsideGeneric")}
        </Alert>
      ) : null}

      {lowAccuracy && location ? (
        <Alert variant="warning" live="polite">
          <p>{t("lowAccuracy", { meters: location.accuracyM ?? 0 })}</p>
          <div className="mt-3 flex items-center gap-2">
            <Checkbox
              id={confirmId}
              checked={Boolean(location.accuracyConfirmed)}
              onChange={(event) =>
                onChange({
                  ...location,
                  accuracyConfirmed: event.target.checked,
                })
              }
              aria-invalid={issue === "confirm_accuracy" || undefined}
              aria-describedby={
                issue === "confirm_accuracy" ? `${confirmId}-error` : undefined
              }
            />
            <label htmlFor={confirmId} className="font-semibold">
              {t("confirmAccuracy")}
            </label>
          </div>
          {issue === "confirm_accuracy" ? (
            <p id={`${confirmId}-error`} className="mt-2 font-semibold">
              {t("confirm_accuracy")}
            </p>
          ) : null}
        </Alert>
      ) : null}

      {issue === "missing" || issue === "checking" ? (
        <Alert variant="destructive" live="assertive">
          {t(issue)}
        </Alert>
      ) : null}
    </div>
  );
}
