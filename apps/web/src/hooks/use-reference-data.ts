"use client";

import { useQuery } from "@tanstack/react-query";
import { useLocale } from "next-intl";
import { useCallback, useMemo } from "react";
import {
  FALLBACK_VIEW,
  fromLngLat,
  type LatLng,
} from "@/components/map/map-config";
import {
  type Category,
  getCurrentTenant,
  listCategories,
  type TenantMap,
} from "@/lib/api";
import { localized } from "@/lib/i18n-text";

/*
 * Data that rarely changes and is shared across pages. Same query keys
 * everywhere, so the tenant and the category list are fetched once per
 * session.
 */

export function useTenant() {
  return useQuery({
    queryKey: ["tenant", "current"],
    queryFn: ({ signal }) => getCurrentTenant(signal),
    staleTime: Number.POSITIVE_INFINITY,
  });
}

export type MapView = {
  center: LatLng;
  zoom: number;
  bounds: TenantMap["bounds"] | null;
  /** False while the tenant has no boundary, so the view is a fallback. */
  configured: boolean;
  /**
   * False until the tenant has loaded. Leaflet only reads the initial
   * centre once, so maps wait for this instead of opening on the fallback.
   */
  ready: boolean;
};

/** The tenant's initial map view, converted from GeoJSON order. */
export function useTenantMapView(): MapView {
  const { data, isPending } = useTenant();
  return useMemo(() => {
    const map = data?.map;
    const ready = !isPending;
    if (!map) {
      return { ...FALLBACK_VIEW, bounds: null, configured: !data, ready };
    }
    return {
      center: fromLngLat(map.center),
      zoom: map.zoom,
      bounds: map.bounds,
      configured: true,
      ready,
    };
  }, [data, isPending]);
}

export function useCategories() {
  return useQuery({
    queryKey: ["categories", "active"],
    queryFn: ({ signal }) => listCategories(signal),
    staleTime: 10 * 60_000,
  });
}

/** `localized()` bound to the current locale. */
export function useLocalized(): (
  text: Category["name_i18n"] | null | undefined,
) => string {
  const locale = useLocale();
  return useCallback((text) => localized(text, locale), [locale]);
}
