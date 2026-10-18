// Types for the viewer API (docs/contracts/run-outputs.md, version 1.1).

export const SYNTHETIC_LABEL = "synthetic demand, uncalibrated";

export interface RunSummary {
  run_id: string;
  kind: string;
  tier: "A" | "B";
  mode: string;
  seed: number;
  network_hash: string;
  sim_seconds: number;
  label: string;
  baseline_run_id?: string | null;
  /** v1.1: comparison sub-runs (`<id>~baseline`, `<id>~reference`) name their parent run. */
  parent_run_id?: string | null;
  scenario_id?: string | null;
  policy_id?: string | null;
  window?: string | null;
  has?: Partial<
    Record<"edgedata" | "fcd" | "policy_report" | "scenario_report" | "recommendations" | "decisions", boolean>
  >;
}

export interface MetricStats {
  p5: number;
  p50: number;
  p95: number;
}

export interface BinsInfo {
  bin_s: number;
  begin_s: number;
  n_bins: number;
  n_edges: number;
  network_hash: string;
  metrics: string[];
  stats: Record<string, MetricStats>;
}

export interface EdgeInfo {
  edge_ids: string[];
  names: string[];
  types: string[];
  lanes: number[];
  speed_kmh: number[];
}

/** Parsed `edges.bin` (TTE1). */
export interface EdgeGeometry {
  nEdges: number;
  nPoints: number;
  /** Start index (in points) of each edge's path; length nEdges + 1. */
  startIndices: Uint32Array;
  /** lon, lat pairs; length 2 * nPoints. */
  positions: Float32Array;
  bbox: [number, number, number, number];
}

export interface DistrictEffect {
  district_id: string;
  name_en?: string;
  value: number | null;
}

export interface DistrictEffects {
  source: "policy_report" | "computed";
  metric: string;
  unit: string;
  districts: DistrictEffect[];
}

export interface SummaryRow {
  baseline?: number;
  policy?: number;
  scenario?: number;
  delta_pct?: number;
  unit?: string;
  [k: string]: unknown;
}

export interface PolicyReport {
  label: string;
  run_id: string;
  baseline_run_id?: string;
  policy?: { id?: string; name?: string; file?: string };
  summary?: Record<string, SummaryRow>;
  districts?: unknown[];
  assumptions?: string[];
}

export interface ScenarioEvent {
  id: string;
  type: string;
  begin_s: number;
  end_s: number;
  edges?: string[];
  /** GeoJSON in lon/lat: Point (anchor) or Polygon (outlined; v1.1). */
  geometry?: { type: string; coordinates: unknown } | null;
  description?: string;
  /** v1.1: the producer's own event type when `type` is "other" (e.g. emergency_trip). */
  producer_type?: string;
}

export interface Closure {
  id: string;
  edges: string[];
  begin_s: number;
  end_s: number;
  reason?: string;
}

export interface ScenarioReport {
  label: string;
  run_id: string;
  baseline_run_id?: string;
  scenario?: { id?: string; name?: string; fictional?: boolean };
  events?: ScenarioEvent[];
  closures?: Closure[];
  summary?: Record<string, SummaryRow>;
}

export interface RecommendationOption {
  option_id: string;
  rank: number;
  title: string;
  action_class: "advisory" | "high_impact" | string;
  requires_approval?: boolean;
  score: number;
  explanation: string;
  effects?: Record<string, number>;
  actions?: unknown[];
  /** v1.1 strategist-backed options: the strategist's candidate id and classification. */
  candidate_id?: string;
  classification?: string;
}

export interface Recommendations {
  label: string;
  run_id: string;
  incident_id?: string;
  generated_at?: string;
  /** v1.1: "strategist" when mapped from runs/strategist (decisions go to its SQLite log). */
  source?: string;
  recommendation_id?: string;
  options: RecommendationOption[];
}

export interface DecisionEntry {
  ts: string;
  run_id: string;
  incident_id?: string;
  option_id: string;
  decision: "approved" | "rejected" | string;
  operator: string;
  note?: string;
  label?: string;
  prev_hash: string;
  hash: string;
  /** v1.1: "strategist-sqlite" for entries read from the strategist's decision log. */
  log?: string;
  record_id?: string;
}

export interface TripsVehicle {
  id: string;
  vtype: string;
  path: [number, number][];
  timestamps: number[];
  speeds: number[];
}

export interface TripsResponse {
  label: string;
  run_id: string;
  begin_s: number;
  end_s: number;
  step: number;
  vehicles: TripsVehicle[];
}

export interface JobStatus {
  job_id: string;
  status: "running" | "done" | "failed" | string;
  run_id?: string | null;
  returncode?: number | null;
}
