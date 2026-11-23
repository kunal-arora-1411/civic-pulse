import {
  Bus,
  CircleHelp,
  Construction,
  Dog,
  Droplets,
  Footprints,
  Lamp,
  Lightbulb,
  type LucideIcon,
  ShieldAlert,
  Signpost,
  TrafficCone,
  Trash2,
  TreeDeciduous,
  Waves,
  Wind,
} from "lucide-react";
import type { ComponentProps } from "react";

/*
 * Categories name a lucide icon (contract §2). Importing every lucide
 * icon by name would ship hundreds of kB to citizens on slow phones, so
 * we keep a curated set. The category editor offers exactly these, and
 * any other name falls back to a neutral icon.
 */
export const CATEGORY_ICONS = {
  construction: Construction,
  "traffic-cone": TrafficCone,
  "trash-2": Trash2,
  waves: Waves,
  droplets: Droplets,
  lightbulb: Lightbulb,
  lamp: Lamp,
  "tree-deciduous": TreeDeciduous,
  footprints: Footprints,
  signpost: Signpost,
  bus: Bus,
  dog: Dog,
  wind: Wind,
  "shield-alert": ShieldAlert,
} as const satisfies Record<string, LucideIcon>;

export type CategoryIconName = keyof typeof CATEGORY_ICONS;

export function categoryIcon(name: string | null | undefined): LucideIcon {
  return (name && CATEGORY_ICONS[name as CategoryIconName]) || CircleHelp;
}

export function CategoryIcon({
  icon,
  ...props
}: { icon: string | null | undefined } & ComponentProps<LucideIcon>) {
  const Icon = categoryIcon(icon);
  return <Icon aria-hidden="true" {...props} />;
}
