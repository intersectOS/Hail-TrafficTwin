// Presentation constants for the viewer. These are display choices (colour ranges, cache sizes,
// playback speeds), not behavioural model assumptions, so they live here and not in the
// assumptions register.

export type Metric = "speed_rel" | "speed_kmh" | "delay_s_per_veh" | "density_veh_km" | "flow_veh_h";

export interface MetricDef {
  id: Metric;
  label: string;
  unit: string;
  /** Fixed absolute range; when null the range is [0, p95] from /bins stats. */
  range: [number, number] | null;
  /** Half-width of the symmetric range in difference mode. */
  diffRange: number;
  /** true: high values are good (fast), coloured green; false: high values are bad (delay). */
  higherIsBetter: boolean;
}

export const METRICS: MetricDef[] = [
  { id: "speed_rel", label: "Speed / limit", unit: "", range: [0, 1], diffRange: 0.25, higherIsBetter: true },
  { id: "speed_kmh", label: "Speed", unit: "km/h", range: [0, 100], diffRange: 20, higherIsBetter: true },
  { id: "delay_s_per_veh", label: "Delay per vehicle", unit: "s", range: null, diffRange: 60, higherIsBetter: false },
  { id: "density_veh_km", label: "Density", unit: "veh/km", range: null, diffRange: 20, higherIsBetter: false },
  { id: "flow_veh_h", label: "Flow", unit: "veh/h", range: null, diffRange: 500, higherIsBetter: false },
];

export function metricDef(id: string): MetricDef {
  return METRICS.find((m) => m.id === id) ?? METRICS[0]!;
}

/** Playback speeds in simulated seconds per wall-clock second. */
export const SPEEDS = [1, 10, 60, 300, 900];
export const DAY_S = 24 * 3600;
/** Bins kept per (run, metric). */
export const BIN_CACHE_SIZE = 24;
/** Bins fetched ahead of the playhead. */
export const PREFETCH_AHEAD = 3;
/** TripsLayer trail, in simulated seconds. */
export const TRAIL_S = 30;
/** Vehicle speed colour range (m/s). */
export const VEH_SPEED_MAX_MS = 20;
/** Grey for edges without data in the current bin. */
export const NO_DATA_RGBA: [number, number, number, number] = [110, 116, 128, 60];
/** Choropleth half-range (percent) used when the data range is degenerate. */
export const CHORO_MIN_HALF = 1;
/** Choropleth half-range = this quantile of |value| (robust to outlier districts; beyond it clips). */
export const CHORO_RANGE_QUANTILE = 0.9;
/** Zoom from which buildings are worth drawing in the city view. */
export const BUILDINGS_MIN_ZOOM = 13;

export const BASEMAP_STYLE_URL = "https://tiles.openfreemap.org/styles/dark";
export const BASEMAP_TIMEOUT_MS = 6000;
