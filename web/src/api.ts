// Thin typed client for the TrafficTwin API (docs/contracts/run-outputs.md section 9).
import type {
  BinsInfo,
  DecisionEntry,
  DistrictEffects,
  EdgeGeometry,
  EdgeInfo,
  JobStatus,
  PolicyReport,
  Recommendations,
  RunSummary,
  ScenarioReport,
  TripsResponse,
} from "./types";
import type { FeatureCollection } from "geojson";

export class HttpError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

async function get(url: string, signal?: AbortSignal): Promise<Response> {
  const res = await fetch(url, { signal });
  if (!res.ok) throw new HttpError(res.status, `${url}: HTTP ${res.status}`);
  return res;
}

async function getJson<T>(url: string, signal?: AbortSignal): Promise<T> {
  return (await (await get(url, signal)).json()) as T;
}

/** Like getJson but resolves to null on 404 (optional artefacts). */
async function getOptional<T>(url: string, signal?: AbortSignal): Promise<T | null> {
  try {
    return await getJson<T>(url, signal);
  } catch (e) {
    if (e instanceof HttpError && e.status === 404) return null;
    throw e;
  }
}

const enc = encodeURIComponent;

export const api = {
  runs: () => getJson<RunSummary[]>("/api/runs"),
  bins: (run: string) => getOptional<BinsInfo>(`/api/runs/${enc(run)}/bins`),
  async bin(run: string, i: number, metric: string, signal?: AbortSignal): Promise<Float32Array> {
    const res = await get(`/api/runs/${enc(run)}/bins/${i}?metric=${enc(metric)}`, signal);
    return new Float32Array(await res.arrayBuffer());
  },
  edgesJson: (hash: string) => getJson<EdgeInfo>(`/api/networks/${enc(hash)}/edges.json`),
  async edgesBin(hash: string): Promise<EdgeGeometry> {
    const res = await get(`/api/networks/${enc(hash)}/edges.bin`);
    return parseEdgesBin(await res.arrayBuffer());
  },
  districts: () => getJson<FeatureCollection>("/api/geo/districts"),
  buildings: (bbox: [number, number, number, number]) =>
    getJson<FeatureCollection>(`/api/geo/buildings?bbox=${bbox.map((v) => v.toFixed(5)).join(",")}`),
  districtEffects: (run: string, baseline: string | null, metric = "mean_speed_delta_pct") =>
    getOptional<DistrictEffects>(
      `/api/runs/${enc(run)}/district-effects?metric=${enc(metric)}${baseline ? `&baseline=${enc(baseline)}` : ""}`,
    ),
  trajectories: (run: string, begin: number, end: number, step = 1) =>
    getOptional<TripsResponse>(`/api/runs/${enc(run)}/trajectories?begin=${begin}&end=${end}&step=${step}`),
  policyReport: (run: string) => getOptional<PolicyReport>(`/api/runs/${enc(run)}/policy-report`),
  scenarioReport: (run: string) => getOptional<ScenarioReport>(`/api/runs/${enc(run)}/scenario-report`),
  recommendations: (run: string) => getOptional<Recommendations>(`/api/runs/${enc(run)}/recommendations`),
  decisions: async (run: string) => (await getOptional<DecisionEntry[]>(`/api/runs/${enc(run)}/decisions`)) ?? [],
  async decide(
    run: string,
    option: string,
    body: { decision: "approved" | "rejected"; operator: string; note: string },
  ): Promise<DecisionEntry> {
    const res = await fetch(`/api/runs/${enc(run)}/recommendations/${enc(option)}/decision`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) throw new HttpError(res.status, `decision: HTTP ${res.status} ${await res.text()}`);
    return (await res.json()) as DecisionEntry;
  },
  async startJob(body: { kind: "smoke"; tier: "A" | "B"; seed: number; end?: number; fcd?: boolean }) {
    const res = await fetch("/api/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) throw new HttpError(res.status, `start job: HTTP ${res.status} ${await res.text()}`);
    return (await res.json()) as { job_id: string };
  },
  job: (id: string) => getJson<JobStatus>(`/api/jobs/${enc(id)}`),
  jobEventsUrl: (id: string) => `/api/jobs/${enc(id)}/events`,
};

/** Parse the TTE1 edge geometry buffer (little endian). */
export function parseEdgesBin(buf: ArrayBuffer): EdgeGeometry {
  const dv = new DataView(buf);
  const magic = String.fromCharCode(dv.getUint8(0), dv.getUint8(1), dv.getUint8(2), dv.getUint8(3));
  if (magic !== "TTE1") throw new Error(`edges.bin: bad magic ${magic}`);
  const nEdges = dv.getUint32(4, true);
  const nPoints = dv.getUint32(8, true);
  const startOff = 12;
  const posOff = startOff + 4 * (nEdges + 1);
  if (buf.byteLength < posOff + 8 * nPoints) throw new Error("edges.bin: truncated");
  // Offsets are 4-byte aligned, so typed views can share the buffer (no copy).
  const startIndices = new Uint32Array(buf, startOff, nEdges + 1);
  const positions = new Float32Array(buf, posOff, 2 * nPoints);
  let w = Infinity,
    s = Infinity,
    e = -Infinity,
    n = -Infinity;
  for (let i = 0; i < positions.length; i += 2) {
    const x = positions[i]!,
      y = positions[i + 1]!;
    if (x < w) w = x;
    if (x > e) e = x;
    if (y < s) s = y;
    if (y > n) n = y;
  }
  return { nEdges, nPoints, startIndices, positions, bbox: [w, s, e, n] };
}
