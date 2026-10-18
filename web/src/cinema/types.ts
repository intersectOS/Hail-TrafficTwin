// Bundle contract written by scripts/movies/bundle.py (runs/movies/<film>/bundle/).

export interface KpiSpec {
  label: string;
  unit: string;
  decimals: number;
  sign: boolean;
}

export interface ShotSpec {
  id: string;
  duration_s: number;
  layers: {
    heat: string | null;
    compare: string | null;
    split: [string, string] | null;
    mode: "single" | "diff" | "split";
    metric: string;
    trips: string | null;
    color_by: "speed" | "class";
    overlays: string[];
    route_source: string | null;
    buildings: boolean;
    outline: [number, number][] | null;
    outline_label: string;
    line?: [number, number][] | null;
    stations?: [number, number][] | null;
  };
  hud: {
    caption: string;
    detail: string;
    kpis: KpiSpec[];
    legend: "speed" | "diff" | "class" | "none";
    split_labels: [string, string] | null;
    /** Which map annotations this shot draws (default: all true when the bundle has them). */
    labels?: ShotLabels;
  };
}

export interface ShotLabels {
  streets: boolean;
  districts: boolean;
  landmarks: boolean;
  callouts: boolean;
}

export interface Annotations {
  /** File name of the labels JSON in the bundle, or null for none. */
  labels: string | null;
  compass: boolean;
  scale_bar: boolean;
  subtitles: boolean;
}

/** One subtitle line, in film seconds (frame i is at i / fps). */
export interface NarrationLine {
  text: string;
  start_s: number;
  end_s: number;
}

/** labels.json. Street cls: 0 motorway/trunk, 1 primary, 2 secondary, 3 tertiary, 4 other. */
export interface Labels {
  streets: { en: string; ar: string | null; cls: number; anchors: [number, number, number][] }[];
  districts: { en: string; ar: string | null; lon: number; lat: number }[];
  landmarks: { id: string; en: string; ar: string | null; lon: number; lat: number; min_zoom: number; max_zoom: number }[];
}

export interface HeatFile {
  url: string;
  metric: string;
  range: [number, number];
  levels: number;
  bin_s: number;
  begin_s: number;
  n_bins: number;
  n_edges: number;
}

export interface TripsFile {
  url: string;
  n_vehicles: number;
  n_points: number;
  speed_scale: number;
  classes: Record<string, number>;
}

export interface Manifest {
  version: number;
  label: string;
  film: string;
  title: string;
  subtitle: string;
  tier: "A" | "B";
  width: number;
  height: number;
  fps: number;
  n_frames: number;
  letterbox: number | null;
  origin: [number, number];
  roads: { url: string; n_edges: number; n_points: number; classes: string[] };
  vehicle_classes: string[];
  trail_s: number;
  diff_half_range: Record<string, number>;
  files: {
    heat: Record<string, HeatFile>;
    trips: Record<string, TripsFile>;
    overlays: string;
    buildings?: string;
    water?: string;
  };
  frames: string;
  shots: ShotSpec[];
  /** Footer adds "fictional demo parameters" when true. */
  fictional?: boolean;
  annotations?: Annotations;
  narration?: NarrationLine[];
}

export interface Frames {
  n: number;
  fps: number;
  shot: number[];
  shot_t: number[];
  sim_t: number[];
  camera: [number, number, number, number, number][];
  /** night, sun_i, amb_i, dx, dy, dz, sun rgb, amb rgb, elevation, azimuth */
  light: number[][];
  clock: string[];
  kpi: (number | null)[][];
  caption_alpha: number[];
  title_alpha: number[];
  fade: number[];
}

export interface Roads {
  n: number;
  starts: Uint32Array;
  positions: Float64Array; // lon/lat interleaved, absolute
  classes: Uint8Array;
  vertexClass: Uint8Array;
}

export interface Heat {
  info: HeatFile;
  values: Uint8Array; // [n_bins * n_edges]
}

export interface Trips {
  n: number;
  starts: Uint32Array; // [n + 1]
  positions: Float64Array;
  times: Float32Array;
  speeds: Uint8Array;
  classes: Uint8Array;
  speedScale: number;
}

/** `callout`: optional English text drawn next to the item on the map while it is active. */
export interface OverlaySet {
  events: { id: string; type: string; begin_s: number; end_s: number; paths: number[][][]; point?: number[]; callout?: string }[];
  closures: { id: string; begin_s: number; end_s: number; paths: number[][][]; point?: number[]; callout?: string }[];
  zone: { ring: number[][]; begin_s: number } | null;
  exits: { id: string; begin_s: number; point?: number[]; paths: number[][][]; callout?: string }[];
  routes: { name: string; paths: number[][][] }[];
  phases: { band: number; begin_s: number; end_s: number; vehicles: number; ring: number[][]; points: number[][] }[];
  contraflow: { id: string; name: string; begin_s: number; paths: number[][][]; point?: number[]; callout?: string }[];
}

export interface Buildings {
  n: number;
  heights: number[];
  rings: number[][][];
}

export interface Water {
  polygons: number[][][][];
}
