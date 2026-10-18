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

/** Built with VITE_STATIC=1 (GitHub Pages): read the files of scripts/hail/export_static.py instead
 * of the live API. The static viewer is read-only (no decisions, no jobs). */
export const STATIC = import.meta.env.VITE_STATIC === "1";
const SB = `${import.meta.env.BASE_URL}api/`;
const sr = (run: string) => `${SB}runs/${enc(run)}`;

export class ReadOnlyError extends Error {}

/** TTP1 packs (one per run and metric), fetched once and decoded per bin on demand. */
const packs = new Map<string, Promise<ArrayBuffer>>();
async function staticBin(run: string, i: number, metric: string, signal?: AbortSignal): Promise<Float32Array> {
  const k = `${run}|${metric}`;
  let p = packs.get(k);
  if (!p) {
    p = get(`${sr(run)}/bins/${enc(metric)}.pack`).then((r) => r.arrayBuffer());
    packs.set(k, p);
    p.catch(() => packs.delete(k));
  }
  const buf = await p;
  if (signal?.aborted) throw new DOMException("aborted", "AbortError");
  const dv = new DataView(buf);
  const nBins = dv.getUint32(4, true);
  const nEdges = dv.getUint32(8, true);
  const idxBytes = dv.getUint32(12, true);
  const lo = dv.getFloat32(16, true);
  const scale = dv.getFloat32(20, true);
  const out = new Float32Array(nEdges).fill(Number.NaN);
  if (i < 0 || i >= nBins) return out;
  let pos = dv.getUint32(24 + 4 * i, true);
  const count = dv.getUint32(pos, true);
  pos += 4;
  const idx = idxBytes === 2 ? new Uint16Array(buf, pos, count) : new Uint32Array(buf, pos, count);
  pos += idxBytes * count;
  pos += (4 - (pos % 4)) % 4;
  const codes = new Uint16Array(buf, pos, count);
  for (let j = 0; j < count; j++) {
    const c = codes[j]!;
    if (c !== 0xffff) out[idx[j]!] = lo + c * scale;
  }
  return out;
}

const staticApi = {
  runs: () => getJson<RunSummary[]>(`${SB}runs.json`),
  bins: (run: string) => getOptional<BinsInfo>(`${sr(run)}/bins.json`),
  bin: staticBin,
  edgesJson: (hash: string) => getJson<EdgeInfo>(`${SB}networks/${enc(hash)}/edges.json`),
  async edgesBin(hash: string): Promise<EdgeGeometry> {
    const res = await get(`${SB}networks/${enc(hash)}/edges.bin`);
    return parseEdgesBin(await res.arrayBuffer());
  },
  districts: () => getJson<FeatureCollection>(`${SB}geo/districts.json`),
  buildings: (_bbox: [number, number, number, number]) => getJson<FeatureCollection>(`${SB}geo/buildings.json`),
  districtEffects: (run: string, baseline: string | null, _metric = "mean_speed_delta_pct") =>
    getOptional<DistrictEffects>(`${sr(run)}/district-effects/${enc(baseline ?? "none")}.json`),
  trajectories: (run: string, _begin: number, _end: number, _step = 1) =>
    getOptional<TripsResponse>(`${sr(run)}/trajectories.json`),
  policyReport: (run: string) => getOptional<PolicyReport>(`${sr(run)}/policy-report.json`),
  scenarioReport: (run: string) => getOptional<ScenarioReport>(`${sr(run)}/scenario-report.json`),
  recommendations: (run: string) => getOptional<Recommendations>(`${sr(run)}/recommendations.json`),
  decisions: async (run: string) => (await getOptional<DecisionEntry[]>(`${sr(run)}/decisions.json`)) ?? [],
  async decide(
    _run: string,
    _option: string,
    _body: { decision: "approved" | "rejected"; operator: string; note: string },
  ): Promise<DecisionEntry> {
    throw new ReadOnlyError("This public viewer is read-only: decisions are logged only on a local installation.");
  },
  async startJob(_body: { kind: "smoke"; tier: "A" | "B"; seed: number; end?: number; fcd?: boolean }): Promise<{ job_id: string }> {
    throw new ReadOnlyError("This public viewer is read-only: runs are started on a local installation.");
  },
  job: (_id: string): Promise<JobStatus> => Promise.reject(new ReadOnlyError("read-only")),
  jobEventsUrl: (_id: string) => "",
};

const liveApi = {
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

export const api: typeof liveApi = STATIC ? staticApi : liveApi;

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
