// Imperative rendering engine: MapLibre basemap + deck.gl overlay + playback clock.
//
// React owns the panels; this class owns everything that changes per frame. The rAF loop advances
// the clock, swaps edge colours when the 5-minute bin changes and pushes new layer instances to
// deck only when something visible changed (every frame only while trips are animating). No React
// state is touched per frame; the timeline is updated through listeners at ~10 Hz.
import maplibregl, { type StyleSpecification } from "maplibre-gl";
import { MapboxOverlay } from "@deck.gl/mapbox";
import type { Layer, PickingInfo } from "@deck.gl/core";
import { GeoJsonLayer, PathLayer, ScatterplotLayer, TextLayer } from "@deck.gl/layers";
import { TripsLayer } from "@deck.gl/geo-layers";
import type { Feature, FeatureCollection, Geometry } from "geojson";

import { BinCache } from "./binCache";
import { colorOf, fillEdgeColors, type Scale } from "./colors";
import {
  BASEMAP_STYLE_URL,
  BASEMAP_TIMEOUT_MS,
  BUILDINGS_MIN_ZOOM,
  CHORO_MIN_HALF,
  CHORO_RANGE_QUANTILE,
  DAY_S,
  PREFETCH_AHEAD,
  TRAIL_S,
  VEH_SPEED_MAX_MS,
  metricDef,
} from "./config";
import type {
  BinsInfo,
  Closure,
  DistrictEffects,
  EdgeGeometry,
  EdgeInfo,
  ScenarioEvent,
  ScenarioReport,
  TripsResponse,
} from "./types";
import type { ViewMode } from "./url";

export const BLANK_STYLE: StyleSpecification = {
  version: 8,
  sources: {},
  layers: [{ id: "background", type: "background", paint: { "background-color": "#0b0e13" } }],
};

const KM_PER_DEG = 111.32;

export const VEHICLE_SCALE: Scale = { palette: "cool", min: 0, max: VEH_SPEED_MAX_MS, invert: false };

type RGBA = [number, number, number, number];

interface BinaryPaths {
  length: number;
  startIndices: Uint32Array;
  attributes: {
    getPath: { value: Float32Array | Float64Array; size: 2 };
    getColor: { value: Uint8Array; size: 4 };
    getWidth?: { value: Float32Array; size: 1 };
    getTimestamps?: { value: Float32Array; size: 1 };
  };
}

interface NetworkData {
  hash: string;
  geom: EdgeGeometry;
  info: EdgeInfo | null;
  data: BinaryPaths;
  colors: Uint8Array;
  idIndex: Map<string, number> | null;
}

export interface RunInput {
  runId: string;
  tier: "A" | "B";
  bins: BinsInfo | null;
}

interface OverlayPath {
  path: number[][];
  color: RGBA;
  width: number;
  kind: "event" | "closure";
  label: string;
}

interface OverlayPoint {
  position: [number, number];
  color: RGBA;
  text: string;
  label: string;
}

const EVENT_COLORS: Record<string, RGBA> = {
  accident: [255, 80, 60, 255],
  rain: [80, 160, 255, 255],
  flood: [40, 110, 255, 255],
  motorcade: [220, 120, 255, 255],
  closure: [255, 40, 40, 255],
  evacuation: [255, 200, 0, 255],
  other: [240, 240, 240, 255],
};

const VTYPE_PALETTE: RGBA[] = [
  [0, 200, 255, 255],
  [255, 170, 0, 255],
  [255, 80, 160, 255],
  [120, 255, 120, 255],
  [200, 140, 255, 255],
  [255, 255, 120, 255],
  [255, 110, 80, 255],
  [140, 220, 220, 255],
];

export interface EngineStatus {
  basemap: "loading" | "ok" | "fallback" | "hidden";
  edges: "none" | "loading" | "ok" | "error";
  bin: "none" | "loading" | "ok" | "nodata";
  trips: "none" | "loading" | "ok";
  message: string;
}

export type TickListener = (t: number, playing: boolean) => void;

export class Engine {
  readonly map: maplibregl.Map;
  private overlay: MapboxOverlay;
  private cache = new BinCache();
  private styleLoaded = false;
  private basemapVisible = true;
  private basemapOk = false;

  // --- clock ---
  t = 0;
  playing = false;
  speed = 60;
  private lastFrame = 0;
  private span: [number, number] = [0, DAY_S];
  private tickListeners = new Set<TickListener>();
  private lastTickEmit = 0;
  private raf = 0;

  // --- inputs ---
  private net: NetworkData | null = null;
  private run: RunInput | null = null;
  private compare: RunInput | null = null;
  private mode: ViewMode = "scenario";
  private metric = "speed_rel";
  private hideNoData = false;
  private trips: TripsResponse | null = null;
  private tripsData: BinaryPaths | null = null;
  private colorBy: "speed" | "vtype" = "speed";
  vtypes: string[] = [];
  private buildings: FeatureCollection | null = null;
  private showBuildings = true;
  private districts: FeatureCollection | null = null;
  private showDistricts = true;
  private effects: DistrictEffects | null = null;
  private effectByDistrict = new Map<string, number>();
  private showChoropleth = false;
  choroScale: Scale = { palette: "rdbu", min: -5, max: 5, invert: false };
  choroClipped = false;
  private scenario: ScenarioReport | null = null;

  // --- derived per bin ---
  private binKey = "";
  private shownBin = -1;
  private values: Float32Array | null = null;
  private baseValues: Float32Array | null = null;
  private colorVersion = 0;
  scale: Scale = { palette: "rdylgn", min: 0, max: 1, invert: false };
  private overlayKey = "";
  private activePaths: OverlayPath[] = [];
  private activePoints: OverlayPoint[] = [];
  private buildingsVisibleNow = false;
  private dirty = true;
  private pending = 0;
  private tooltip: HTMLDivElement;
  /** Recolour timings (per bin change), read by scripts/perf.mjs. */
  perf = { recolours: 0, recolourMsTotal: 0, recolourMsMax: 0 };

  status: EngineStatus = { basemap: "loading", edges: "none", bin: "none", trips: "none", message: "" };
  onStatus: ((s: EngineStatus) => void) | null = null;
  onScaleChange: (() => void) | null = null;

  constructor(container: HTMLElement, tooltip: HTMLDivElement) {
    this.tooltip = tooltip;
    this.map = new maplibregl.Map({
      container,
      style: BLANK_STYLE,
      center: [39.18, 21.55],
      zoom: 10.5,
      maxPitch: 75,
      attributionControl: { compact: true },
      // Needed so screenshots can read the WebGL canvas.
      canvasContextAttributes: { preserveDrawingBuffer: true },
    });
    this.map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), "top-right");
    this.overlay = new MapboxOverlay({
      interleaved: false,
      layers: [],
      getTooltip: null as never,
      onHover: (info: PickingInfo) => this.handleHover(info),
      _typedArrayManagerProps: { overAlloc: 1, poolSize: 0 },
      deviceProps: { webgl: { preserveDrawingBuffer: true } },
    } as ConstructorParameters<typeof MapboxOverlay>[0]);
    this.map.addControl(this.overlay as unknown as maplibregl.IControl);
    this.map.on("zoomend", () => this.markDirtyIfBuildingsChange());
    void this.loadBasemap();
    this.raf = requestAnimationFrame(this.frame);
  }

  destroy(): void {
    cancelAnimationFrame(this.raf);
    this.map.remove();
  }

  // ------------------------------------------------------------------ basemap
  private async loadBasemap(): Promise<void> {
    try {
      const ctl = new AbortController();
      const timer = setTimeout(() => ctl.abort(), BASEMAP_TIMEOUT_MS);
      const res = await fetch(BASEMAP_STYLE_URL, { signal: ctl.signal });
      clearTimeout(timer);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const style = (await res.json()) as StyleSpecification;
      this.map.once("style.load", () => {
        this.styleLoaded = true;
        this.basemapOk = true;
        this.applyBasemapVisibility();
      });
      // diff: false forces a full load so "style.load" fires (a diff from the blank style does not).
      this.map.setStyle(style, { diff: false });
    } catch (err) {
      console.warn("basemap style failed, using plain background", err);
      this.styleLoaded = true;
      this.setStatus({ basemap: "fallback" });
    }
  }

  setBasemapVisible(v: boolean): void {
    this.basemapVisible = v;
    this.applyBasemapVisibility();
  }

  private applyBasemapVisibility(): void {
    if (!this.basemapOk) {
      this.setStatus({ basemap: this.styleLoaded ? "fallback" : "loading" });
      return;
    }
    const style = this.map.getStyle();
    for (const layer of style.layers ?? []) {
      if (layer.type === "background") continue;
      this.map.setLayoutProperty(layer.id, "visibility", this.basemapVisible ? "visible" : "none");
    }
    this.setStatus({ basemap: this.basemapVisible ? "ok" : "hidden" });
  }

  // ------------------------------------------------------------------ inputs
  private setStatus(p: Partial<EngineStatus>): void {
    this.status = { ...this.status, ...p };
    this.onStatus?.(this.status);
  }

  setNetwork(hash: string, geom: EdgeGeometry | null, info: EdgeInfo | null): void {
    if (!geom) {
      this.net = null;
      this.setStatus({ edges: "none" });
      this.dirty = true;
      return;
    }
    if (this.net?.hash === hash && this.net.geom === geom) {
      if (info && this.net.info !== info) {
        this.net.info = info;
        this.net.idIndex = null;
        this.applyWidths(info);
        this.overlayKey = "";
        this.dirty = true;
      }
      return;
    }
    const colors = new Uint8Array(geom.nPoints * 4);
    const data: BinaryPaths = {
      length: geom.nEdges,
      startIndices: geom.startIndices.subarray(0, geom.nEdges),
      attributes: {
        getPath: { value: geom.positions, size: 2 },
        getColor: { value: colors, size: 4 },
      },
    };
    this.net = { hash, geom, info, data, colors, idIndex: null };
    if (info) this.applyWidths(info);
    this.binKey = "";
    this.overlayKey = "";
    this.setStatus({ edges: "ok" });
    this.dirty = true;
  }

  /** Per-vertex widths in metres from lane counts (set once per network). */
  private applyWidths(info: EdgeInfo): void {
    const net = this.net;
    if (!net) return;
    const { startIndices, nEdges, nPoints } = net.geom;
    const w = new Float32Array(nPoints);
    for (let e = 0; e < nEdges; e++) {
      const lanes = info.lanes[e] ?? 1;
      const width = 1.5 + 3.2 * Math.max(1, lanes);
      w.fill(width, startIndices[e]!, startIndices[e + 1]!);
    }
    net.data = { ...net.data, attributes: { ...net.data.attributes, getWidth: { value: w, size: 1 } } };
  }

  setRuns(run: RunInput | null, compare: RunInput | null, mode: ViewMode): void {
    this.run = run;
    this.compare = compare;
    this.mode = compare ? mode : "scenario";
    this.updateSpan();
    this.binKey = "";
    this.dirty = true;
  }

  setMetric(metric: string, hideNoData: boolean): void {
    this.metric = metric;
    this.hideNoData = hideNoData;
    this.binKey = "";
  }

  setTrips(trips: TripsResponse | null, colorBy: "speed" | "vtype"): void {
    if (trips === this.trips && colorBy === this.colorBy) return;
    this.trips = trips;
    this.colorBy = colorBy;
    this.tripsData = trips ? this.buildTrips(trips, colorBy) : null;
    this.setStatus({ trips: trips ? "ok" : "none" });
    this.updateSpan();
    this.dirty = true;
  }

  setBuildings(fc: FeatureCollection | null, show: boolean): void {
    this.buildings = fc;
    this.showBuildings = show;
    this.dirty = true;
  }

  setDistricts(fc: FeatureCollection | null, show: boolean): void {
    this.districts = fc;
    this.showDistricts = show;
    this.dirty = true;
  }

  setChoropleth(effects: DistrictEffects | null, show: boolean): void {
    this.effects = effects;
    this.showChoropleth = show;
    this.effectByDistrict.clear();
    const abs: number[] = [];
    for (const d of effects?.districts ?? []) {
      if (d.value === null || !Number.isFinite(d.value)) continue;
      this.effectByDistrict.set(d.district_id, d.value);
      abs.push(Math.abs(d.value));
    }
    abs.sort((a, b) => a - b);
    const q = abs.length ? abs[Math.min(abs.length - 1, Math.floor(CHORO_RANGE_QUANTILE * abs.length))]! : 0;
    const half = Math.max(CHORO_MIN_HALF, q);
    this.choroClipped = abs.length > 0 && abs[abs.length - 1]! > half;
    const lowerBetter = (effects?.metric ?? "").includes("delay") || (effects?.metric ?? "").includes("vkt");
    this.choroScale = { palette: "rdbu", min: -half, max: half, invert: lowerBetter };
    this.onScaleChange?.();
    this.dirty = true;
  }

  setScenario(report: ScenarioReport | null): void {
    this.scenario = report;
    this.overlayKey = "";
    this.dirty = true;
  }

  // ------------------------------------------------------------------ clock
  addTickListener(fn: TickListener): () => void {
    this.tickListeners.add(fn);
    fn(this.t, this.playing);
    return () => this.tickListeners.delete(fn);
  }

  private emitTick(force = false): void {
    const now = performance.now();
    if (!force && now - this.lastTickEmit < 100) return;
    this.lastTickEmit = now;
    for (const fn of this.tickListeners) fn(this.t, this.playing);
  }

  seek(t: number): void {
    this.t = Math.max(0, Math.min(DAY_S, t));
    this.dirty = true;
    this.emitTick(true);
  }

  setPlaying(p: boolean): void {
    this.playing = p;
    this.lastFrame = performance.now();
    if (p && (this.t < this.span[0] || this.t >= this.span[1])) this.t = this.span[0];
    this.emitTick(true);
  }

  setSpeed(s: number): void {
    this.speed = s;
  }

  /** Data span [begin, end) of the current run(s); playback loops inside it. */
  getSpan(): [number, number] {
    return this.span;
  }

  private updateSpan(): void {
    const b = this.run?.bins;
    if (b && b.n_bins > 0) this.span = [b.begin_s, b.begin_s + b.n_bins * b.bin_s];
    else if (this.trips) this.span = [this.trips.begin_s, this.trips.end_s];
    else this.span = [0, DAY_S];
  }

  private frame = (now: number): void => {
    this.raf = requestAnimationFrame(this.frame);
    if (this.playing) {
      const dt = Math.min(0.25, (now - this.lastFrame) / 1000);
      this.t += dt * this.speed;
      if (this.t >= this.span[1]) this.t = this.span[0] + ((this.t - this.span[0]) % (this.span[1] - this.span[0] || 1));
      if (this.t > DAY_S) this.t = 0;
    }
    this.lastFrame = now;
    this.updateBin();
    this.updateOverlays();
    if (this.dirty || (this.playing && this.tripsData)) {
      this.dirty = false;
      this.overlay.setProps({ layers: this.buildLayers() });
    }
    if (this.playing) this.emitTick();
  };

  // ------------------------------------------------------------------ bins
  private binIndex(r: RunInput | null): number {
    const b = r?.bins;
    if (!b) return -1;
    const i = Math.floor((this.t - b.begin_s) / b.bin_s);
    return i >= 0 && i < b.n_bins ? i : -1;
  }

  private computeScale(): Scale {
    const def = metricDef(this.metric);
    if (this.mode === "diff") {
      return { palette: "rdbu", min: -def.diffRange, max: def.diffRange, invert: !def.higherIsBetter };
    }
    const src = this.mode === "baseline" ? this.compare : this.run;
    let range = def.range;
    if (!range) {
      const st = src?.bins?.stats?.[this.metric];
      range = [0, st && Number.isFinite(st.p95) && st.p95 > 0 ? st.p95 : 1];
    }
    return { palette: def.higherIsBetter ? "rdylgn" : "ylorrd", min: range[0], max: range[1], invert: false };
  }

  private updateBin(): void {
    const net = this.net;
    if (!net) return;
    const showRun = this.mode === "baseline" ? this.compare : this.run;
    const iMain = this.binIndex(showRun);
    const iBase = this.mode === "diff" ? this.binIndex(this.compare) : -1;
    const key = `${this.mode}|${this.metric}|${this.hideNoData}|${showRun?.runId}|${this.compare?.runId}|${iMain}|${iBase}`;
    if (key === this.binKey) return;

    const scale = this.computeScale();
    const metric = this.metric;
    const nBinsMain = showRun?.bins?.n_bins ?? 0;
    if (showRun && iMain >= 0) this.cache.prefetch(showRun.runId, metric, iMain + 1, PREFETCH_AHEAD, nBinsMain);
    if (this.mode === "diff" && this.compare && iBase >= 0)
      this.cache.prefetch(this.compare.runId, metric, iBase + 1, PREFETCH_AHEAD, this.compare.bins?.n_bins ?? 0);

    if (!showRun || iMain < 0 || (this.mode === "diff" && iBase < 0)) {
      this.binKey = key;
      this.apply(null, null, scale, -1);
      this.setStatus({ bin: showRun?.bins ? "nodata" : "none" });
      return;
    }
    const main = this.cache.peek(showRun.runId, metric, iMain);
    const base = this.mode === "diff" && this.compare ? this.cache.peek(this.compare.runId, metric, iBase) : null;
    if (main && (this.mode !== "diff" || base)) {
      this.binKey = key;
      this.apply(main, base ?? null, scale, iMain);
      this.setStatus({ bin: "ok" });
      return;
    }
    // Not cached: keep the previous colours until the fetch lands (no flicker), then retry.
    this.binKey = key;
    this.pending++;
    this.setStatus({ bin: "loading" });
    const want = [this.cache.get(showRun.runId, metric, iMain)];
    if (this.mode === "diff" && this.compare) want.push(this.cache.get(this.compare.runId, metric, iBase));
    void Promise.all(want).finally(() => {
      this.pending--;
      if (this.binKey === key) this.binKey = ""; // re-evaluate next frame from the cache
    });
  }

  private apply(values: Float32Array | null, base: Float32Array | null, scale: Scale, bin: number): void {
    const net = this.net;
    if (!net) return;
    const n = net.geom.nEdges;
    // Guard against a bins array that does not match the edge index.
    const ok = (a: Float32Array | null) => !a || a.length === n;
    if (!ok(values) || !ok(base)) {
      console.warn("bin length does not match edge count", values?.length, n);
      values = null;
      base = null;
    }
    const t0 = performance.now();
    fillEdgeColors(net.colors, net.geom.startIndices, n, values, base, scale, this.hideNoData);
    const dt = performance.now() - t0;
    this.perf.recolours++;
    this.perf.recolourMsTotal += dt;
    this.perf.recolourMsMax = Math.max(this.perf.recolourMsMax, dt);
    // New wrapper object -> deck re-uploads the colour attribute only; the path geometry is not
    // re-tessellated because `data` itself is unchanged.
    net.data.attributes.getColor = { value: net.colors, size: 4 };
    this.colorVersion++;
    this.values = values;
    this.baseValues = base;
    this.shownBin = bin;
    const changed = scale.min !== this.scale.min || scale.max !== this.scale.max || scale.palette !== this.scale.palette || scale.invert !== this.scale.invert;
    this.scale = scale;
    if (changed) this.onScaleChange?.();
    this.dirty = true;
  }

  /** Current value on edge `i` (difference applied in diff mode). */
  valueAt(i: number): number {
    if (!this.values) return NaN;
    const v = this.values[i] ?? NaN;
    return this.baseValues ? v - (this.baseValues[i] ?? NaN) : v;
  }

  getShownBin(): number {
    return this.shownBin;
  }

  // ------------------------------------------------------------------ trips
  private buildTrips(trips: TripsResponse, colorBy: "speed" | "vtype"): BinaryPaths {
    const vs = trips.vehicles.filter((v) => v.path.length >= 2);
    let nPts = 0;
    for (const v of vs) nPts += v.path.length;
    const pos = new Float64Array(nPts * 2);
    const ts = new Float32Array(nPts);
    const col = new Uint8Array(nPts * 4);
    const starts = new Uint32Array(vs.length);
    const vtypes = [...new Set(vs.map((v) => v.vtype))].sort();
    this.vtypes = vtypes;
    const speedScale: Scale = VEHICLE_SCALE;
    let p = 0;
    vs.forEach((v, k) => {
      starts[k] = p;
      const vc = VTYPE_PALETTE[vtypes.indexOf(v.vtype) % VTYPE_PALETTE.length]!;
      for (let j = 0; j < v.path.length; j++, p++) {
        const pt = v.path[j]!;
        pos[2 * p] = pt[0];
        pos[2 * p + 1] = pt[1];
        ts[p] = v.timestamps[j] ?? 0;
        const c = colorBy === "vtype" ? vc : colorOf(speedScale, v.speeds[j] ?? NaN);
        col[4 * p] = c[0];
        col[4 * p + 1] = c[1];
        col[4 * p + 2] = c[2];
        col[4 * p + 3] = 255;
      }
    });
    return {
      length: vs.length,
      startIndices: starts,
      attributes: {
        getPath: { value: pos, size: 2 },
        getTimestamps: { value: ts, size: 1 },
        getColor: { value: col, size: 4 },
      },
    };
  }

  vtypeColor(vtype: string): RGBA {
    return VTYPE_PALETTE[this.vtypes.indexOf(vtype) % VTYPE_PALETTE.length] ?? [255, 255, 255, 255];
  }

  // ------------------------------------------------------------------ overlays
  private edgeIndex(id: string): number | undefined {
    const net = this.net;
    if (!net?.info) return undefined;
    if (!net.idIndex) {
      net.idIndex = new Map();
      net.info.edge_ids.forEach((e, i) => net.idIndex!.set(e, i));
    }
    return net.idIndex.get(id);
  }

  private edgePath(id: string): number[][] | null {
    const i = this.edgeIndex(id);
    const net = this.net;
    if (i === undefined || !net) return null;
    const a = net.geom.startIndices[i]!,
      b = net.geom.startIndices[i + 1]!;
    const out: number[][] = [];
    for (let p = a; p < b; p++) out.push([net.geom.positions[2 * p]!, net.geom.positions[2 * p + 1]!]);
    return out;
  }

  private updateOverlays(): void {
    const rep = this.scenario;
    if (!rep) {
      if (this.overlayKey !== "none") {
        this.overlayKey = "none";
        this.activePaths = [];
        this.activePoints = [];
        this.dirty = true;
      }
      return;
    }
    const inWin = (b: number, e: number) => this.t >= b && this.t <= e;
    const evs = (rep.events ?? []).filter((e) => inWin(e.begin_s, e.end_s));
    const cls = (rep.closures ?? []).filter((c) => inWin(c.begin_s, c.end_s));
    const key = evs.map((e) => e.id).join(",") + "|" + cls.map((c) => c.id).join(",");
    if (key === this.overlayKey) return;
    this.overlayKey = key;
    const paths: OverlayPath[] = [];
    const points: OverlayPoint[] = [];
    for (const ev of evs) this.addEvent(ev, paths, points);
    for (const cl of cls) this.addClosure(cl, paths);
    this.activePaths = paths;
    this.activePoints = points;
    this.dirty = true;
  }

  private addEvent(ev: ScenarioEvent, paths: OverlayPath[], points: OverlayPoint[]): void {
    const color = EVENT_COLORS[ev.type] ?? EVENT_COLORS.other!;
    const label = `${ev.type}: ${ev.description ?? ev.id}`;
    let anchor: [number, number] | null = null;
    for (const id of ev.edges ?? []) {
      const p = this.edgePath(id);
      if (!p) continue;
      paths.push({ path: p, color: [255, 220, 0, 230], width: 14, kind: "event", label });
      if (!anchor) anchor = p[Math.floor(p.length / 2)] as [number, number];
    }
    const g = ev.geometry;
    if (g && g.type === "Point" && Array.isArray(g.coordinates)) anchor = g.coordinates as [number, number];
    // Polygon (e.g. an evacuation zone, contract v1.1): outline each ring, label at the centroid.
    if (g && g.type === "Polygon" && Array.isArray(g.coordinates)) {
      for (const ring of g.coordinates as number[][][]) {
        if (!Array.isArray(ring) || ring.length < 3) continue;
        paths.push({ path: ring, color, width: 6, kind: "event", label });
        if (!anchor) {
          let x = 0,
            y = 0;
          const n = ring.length - 1; // closed ring: last point repeats the first
          for (let k = 0; k < n; k++) {
            x += ring[k]![0]!;
            y += ring[k]![1]!;
          }
          anchor = [x / n, y / n];
        }
      }
    }
    if (anchor) points.push({ position: anchor, color, text: ev.type.toUpperCase(), label });
  }

  /** Closures are drawn as red dashes, cut on the CPU (a few edges; avoids an extension). */
  private addClosure(cl: Closure, paths: OverlayPath[]): void {
    const label = `closure: ${cl.reason ?? cl.id}`;
    const dashKm = 0.012;
    for (const id of cl.edges) {
      const p = this.edgePath(id);
      if (!p) continue;
      for (const seg of dashes(p, dashKm)) paths.push({ path: seg, color: [255, 30, 30, 255], width: 9, kind: "closure", label });
    }
  }

  // ------------------------------------------------------------------ layers
  private markDirtyIfBuildingsChange(): void {
    const vis = this.buildingsShouldShow();
    if (vis !== this.buildingsVisibleNow) this.dirty = true;
  }

  private buildingsShouldShow(): boolean {
    if (!this.buildings || !this.showBuildings) return false;
    return this.run?.tier === "B" || this.map.getZoom() >= BUILDINGS_MIN_ZOOM;
  }

  private buildLayers(): Layer[] {
    const layers: Layer[] = [];
    if (this.districts && (this.showDistricts || this.showChoropleth)) {
      const choro = this.showChoropleth && this.effects !== null;
      layers.push(
        new GeoJsonLayer({
          id: "districts",
          data: this.districts,
          stroked: this.showDistricts,
          filled: true,
          pickable: true,
          getLineColor: [150, 170, 200, 160],
          lineWidthUnits: "pixels",
          getLineWidth: 1,
          getFillColor: (f: Feature<Geometry, { osm_id?: string }>) => {
            if (!choro) return [0, 0, 0, 0];
            const v = this.effectByDistrict.get(String(f.properties?.osm_id));
            if (v === undefined) return [90, 90, 90, 40];
            const c = colorOf(this.choroScale, v);
            return [c[0], c[1], c[2], 170];
          },
          updateTriggers: { getFillColor: [choro, this.effects] },
        }),
      );
    }
    const net = this.net;
    if (net) {
      layers.push(
        new PathLayer({
          id: "edges",
          data: net.data as never,
          _pathType: "open",
          widthUnits: "meters",
          widthMinPixels: 1,
          widthMaxPixels: this.tripsData ? 5 : 10,
          ...(net.data.attributes.getWidth ? {} : { getWidth: 4 }),
          capRounded: false,
          jointRounded: false,
          pickable: true,
          autoHighlight: true,
          highlightColor: [255, 255, 255, 220],
          opacity: this.tripsData ? 0.4 : 1,
          // Flat 2D layer: no depth writes, so vehicles and overlays at z = 0 always draw over it.
          parameters: { depthWriteEnabled: false },
          updateTriggers: { getColor: this.colorVersion },
        }),
      );
    }
    this.buildingsVisibleNow = this.buildingsShouldShow();
    if (this.buildings && this.buildingsVisibleNow) {
      layers.push(
        new GeoJsonLayer({
          id: "buildings",
          data: this.buildings,
          extruded: true,
          filled: true,
          stroked: false,
          wireframe: false,
          getElevation: (f: Feature<Geometry, { height_m?: number }>) => f.properties?.height_m ?? 6,
          getFillColor: [120, 135, 160, 210],
          material: { ambient: 0.45, diffuse: 0.6, shininess: 16, specularColor: [60, 64, 70] },
          pickable: false,
        }),
      );
    }
    if (this.tripsData) {
      layers.push(
        new TripsLayer({
          id: "trips",
          data: this.tripsData as never,
          _pathType: "open",
          currentTime: this.t,
          trailLength: TRAIL_S,
          fadeTrail: true,
          widthUnits: "pixels",
          getWidth: 6,
          widthMinPixels: 4,
          parameters: { depthWriteEnabled: false },
          capRounded: true,
          jointRounded: true,
        }),
      );
    }
    if (this.activePaths.length) {
      layers.push(
        new PathLayer<OverlayPath>({
          id: "scenario-paths",
          data: this.activePaths,
          getPath: (d) => d.path as never,
          getColor: (d) => d.color,
          getWidth: (d) => d.width,
          widthUnits: "pixels",
          capRounded: false,
          pickable: true,
          parameters: { depthWriteEnabled: false, depthCompare: "always" },
        }),
      );
    }
    if (this.activePoints.length) {
      layers.push(
        new ScatterplotLayer<OverlayPoint>({
          id: "scenario-points",
          data: this.activePoints,
          getPosition: (d) => d.position,
          getFillColor: (d) => d.color,
          getLineColor: [255, 255, 255, 255],
          stroked: true,
          lineWidthMinPixels: 2,
          radiusUnits: "pixels",
          getRadius: 11,
          pickable: true,
          parameters: { depthCompare: "always" },
        }),
        new TextLayer<OverlayPoint>({
          id: "scenario-labels",
          data: this.activePoints,
          getPosition: (d) => d.position,
          getText: (d) => d.text,
          getColor: [255, 255, 255, 255],
          getSize: 13,
          getPixelOffset: [0, -24],
          fontWeight: 700,
          outlineWidth: 3,
          outlineColor: [0, 0, 0, 255],
          fontSettings: { sdf: true },
          parameters: { depthCompare: "always" },
        }),
      );
    }
    return layers;
  }

  // ------------------------------------------------------------------ hover
  private handleHover(info: PickingInfo): void {
    const tip = this.tooltip;
    if (!info.picked || info.index < 0 || !info.layer) {
      tip.style.display = "none";
      return;
    }
    let html = "";
    const id = info.layer.id;
    if (id === "edges" && this.net) {
      const i = info.index;
      const inf = this.net.info;
      const def = metricDef(this.metric);
      const v = this.valueAt(i);
      const name = inf?.names[i] || "(unnamed)";
      const val = Number.isFinite(v) ? `${v.toFixed(def.id === "speed_rel" ? 2 : 1)} ${def.unit}` : "no data";
      html = `<b>${esc(name)}</b><br>${esc(inf?.edge_ids[i] ?? `#${i}`)} · ${esc(inf?.types[i] ?? "")}<br>${inf ? `${inf.lanes[i]} lanes · ${inf.speed_kmh[i]} km/h limit<br>` : ""}${esc(def.label)}${this.mode === "diff" ? " Δ" : ""}: <b>${val}</b>`;
    } else if (id === "districts") {
      const p = (info.object as Feature<Geometry, Record<string, unknown>>).properties ?? {};
      const v = this.effectByDistrict.get(String(p.osm_id));
      html = `<b>${esc(String(p.name_en ?? ""))}</b> ${esc(String(p.name_ar ?? ""))}`;
      if (this.showChoropleth && this.effects)
        html += `<br>${esc(this.effects.metric)}: <b>${v === undefined ? "n/a" : `${v.toFixed(2)} ${esc(this.effects.unit)}`}</b>`;
    } else if (id.startsWith("scenario")) {
      html = esc((info.object as { label: string }).label);
    } else {
      tip.style.display = "none";
      return;
    }
    tip.innerHTML = html;
    tip.style.display = "block";
    tip.style.left = `${info.x + 14}px`;
    tip.style.top = `${info.y + 14}px`;
  }

  // ------------------------------------------------------------------ camera / readiness
  fitTo(bbox: [number, number, number, number], pitched: boolean, view: number[] | null): void {
    if (view && view.length >= 3) {
      this.map.jumpTo({ center: [view[0]!, view[1]!], zoom: view[2]!, pitch: view[3] ?? 0, bearing: view[4] ?? 0 });
      return;
    }
    this.map.fitBounds(
      [
        [bbox[0], bbox[1]],
        [bbox[2], bbox[3]],
      ],
      { padding: 40, pitch: pitched ? 55 : 0, bearing: pitched ? -20 : 0, duration: 0 },
    );
  }

  /** Readiness breakdown (used by the screenshot and perf scripts). */
  readiness(): Record<string, boolean | number | string> {
    const deck = (this.overlay as unknown as { _deck?: { layerManager?: { getLayers(): Layer[] } } })._deck;
    const layers = deck?.layerManager?.getLayers() ?? [];
    const notLoaded = layers.filter((l) => !l.isLoaded).map((l) => l.id);
    return {
      pending: this.pending,
      dirty: this.dirty,
      deck: Boolean(deck),
      layersNotLoaded: notLoaded.join(","),
      styleLoaded: this.styleLoaded,
      mapLoaded: this.map.loaded(),
      tilesLoaded: this.map.areTilesLoaded(),
      bin: this.status.bin,
    };
  }

  /** True when nothing is loading and deck + map have drawn the current state. */
  isReady(): boolean {
    const r = this.readiness();
    return r.pending === 0 && !r.dirty && r.deck === true && r.layersNotLoaded === "" && r.styleLoaded === true && r.tilesLoaded === true && r.bin !== "loading";
  }

  cacheStats(): { entries: number; mb: number } {
    return { entries: this.cache.size, mb: this.cache.bytes / 1e6 };
  }
}

function esc(s: string): string {
  return s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]!);
}

/** Split a lon/lat polyline into dash segments of `dashKm` with equal gaps. */
function dashes(path: number[][], dashKm: number): number[][][] {
  const out: number[][][] = [];
  let on = true;
  let left = dashKm;
  let cur: number[][] = [path[0]!];
  for (let i = 1; i < path.length; i++) {
    let [x0, y0] = path[i - 1] as [number, number];
    const [x1, y1] = path[i] as [number, number];
    const kx = KM_PER_DEG * Math.cos((y0 * Math.PI) / 180);
    let segKm = Math.hypot((x1 - x0) * kx, (y1 - y0) * KM_PER_DEG);
    while (segKm > left) {
      const f = left / segKm;
      const xm = x0 + (x1 - x0) * f,
        ym = y0 + (y1 - y0) * f;
      if (on) {
        cur.push([xm, ym]);
        out.push(cur);
      }
      cur = [[xm, ym]];
      on = !on;
      segKm -= left;
      left = dashKm;
      x0 = xm;
      y0 = ym;
    }
    left -= segKm;
    if (on) cur.push([x1, y1]);
  }
  if (on && cur.length > 1) out.push(cur);
  return out;
}
