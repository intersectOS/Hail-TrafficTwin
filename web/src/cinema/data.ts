// Loads a film bundle (manifest, per-frame plan, binary roads/heat/trips, overlays, basemap).
import type { Buildings, Frames, Heat, Labels, Manifest, OverlaySet, Roads, Trips, Water } from "./types";

export interface Bundle {
  manifest: Manifest;
  frames: Frames;
  roads: Roads;
  heat: Map<string, Heat>;
  trips: Map<string, Trips>;
  overlays: Record<string, OverlaySet>;
  buildings: Buildings | null;
  water: Water | null;
  labels: Labels | null;
}

async function bytes(url: string): Promise<ArrayBuffer> {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${url}: HTTP ${r.status}`);
  return r.arrayBuffer();
}

async function json<T>(url: string): Promise<T> {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${url}: HTTP ${r.status}`);
  return (await r.json()) as T;
}

/** Offsets (f32, relative to origin) -> absolute lon/lat as f64. */
function absolute(off: Float32Array, origin: [number, number]): Float64Array {
  const out = new Float64Array(off.length);
  for (let i = 0; i < off.length; i += 2) {
    out[i] = origin[0] + off[i]!;
    out[i + 1] = origin[1] + off[i + 1]!;
  }
  return out;
}

function parseRoads(buf: ArrayBuffer, m: Manifest): Roads {
  const n = m.roads.n_edges;
  const p = m.roads.n_points;
  let o = 0;
  const starts = new Uint32Array(buf, o, n + 1);
  o += 4 * (n + 1);
  const off = new Float32Array(buf.slice(o, o + 8 * p));
  o += 8 * p;
  const classes = new Uint8Array(buf, o, n);
  const vertexClass = new Uint8Array(p);
  for (let e = 0; e < n; e++) vertexClass.fill(classes[e]!, starts[e]!, starts[e + 1]!);
  return { n, starts, positions: absolute(off, m.origin), classes, vertexClass };
}

function parseTrips(buf: ArrayBuffer, n: number, p: number, origin: [number, number], speedScale: number): Trips {
  let o = 0;
  const starts = new Uint32Array(buf.slice(o, o + 4 * (n + 1)));
  o += 4 * (n + 1);
  const off = new Float32Array(buf.slice(o, o + 8 * p));
  o += 8 * p;
  const times = new Float32Array(buf.slice(o, o + 4 * p));
  o += 4 * p;
  const speeds = new Uint8Array(buf.slice(o, o + p));
  o += p;
  const classes = new Uint8Array(buf.slice(o, o + n));
  return { n, starts, positions: absolute(off, origin), times, speeds, classes, speedScale };
}

export async function loadBundle(base: string): Promise<Bundle> {
  const manifest = await json<Manifest>(`${base}/manifest.json`);
  const [frames, roadsBuf, overlays] = await Promise.all([
    json<Frames>(`${base}/${manifest.frames}`),
    bytes(`${base}/${manifest.roads.url}`),
    json<Record<string, OverlaySet>>(`${base}/${manifest.files.overlays}`),
  ]);
  const heat = new Map<string, Heat>();
  for (const [sid, info] of Object.entries(manifest.files.heat)) {
    heat.set(sid, { info, values: new Uint8Array(await bytes(`${base}/${info.url}`)) });
  }
  const trips = new Map<string, Trips>();
  for (const [sid, info] of Object.entries(manifest.files.trips)) {
    const buf = await bytes(`${base}/${info.url}`);
    trips.set(sid, parseTrips(buf, info.n_vehicles, info.n_points, manifest.origin, info.speed_scale));
  }
  const buildings = manifest.files.buildings ? await json<Buildings>(`${base}/${manifest.files.buildings}`) : null;
  const water = manifest.files.water ? await json<Water>(`${base}/${manifest.files.water}`) : null;
  const lf = manifest.annotations?.labels;
  const labels = lf ? await json<Labels>(`${base}/${lf}`) : null;
  return { manifest, frames, roads: parseRoads(roadsBuf, manifest), heat, trips, overlays, buildings, water, labels };
}
