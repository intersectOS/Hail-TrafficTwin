// Builds the deck.gl layers and lights for one frame of a film. Pure function of (bundle, frame):
// no wall clock, no randomness, so the same bundle gives the same frames.
import { AmbientLight, DirectionalLight, LightingEffect, type Layer } from "@deck.gl/core";
import { PathLayer, ScatterplotLayer, SolidPolygonLayer } from "@deck.gl/layers";
import { TripsLayer } from "@deck.gl/geo-layers";

import type { Bundle } from "./data";
import type { Heat, OverlaySet, ShotSpec, Trips } from "./types";
import {
  BAND_COLORS,
  CLASS_COLORS,
  DIFF_LUT,
  EMERGENCY_BLUE,
  HEAT_LUT,
  SPEED_LUT,
  SPEED_MAX_MS,
  mix,
  type RGB,
} from "./palette";

// Road width (m) and base brightness per class: motorway, primary, secondary, minor, link.
const ROAD_WIDTH_M = [16, 11, 8, 4.5, 7];
const ROAD_BASE_DAY: RGB[] = [
  [92, 104, 124],
  [74, 84, 102],
  [60, 68, 84],
  [42, 48, 60],
  [66, 76, 94],
];
const ROAD_BASE_NIGHT: RGB[] = [
  [255, 196, 120],
  [214, 160, 104],
  [150, 116, 86],
  [70, 60, 56],
  [200, 150, 100],
];
const LAND_DAY: RGB = [24, 28, 36];
const LAND_NIGHT: RGB = [7, 9, 13];
const WATER_DAY: RGB = [14, 38, 60];
const WATER_NIGHT: RGB = [4, 12, 24];
const BUILDING_DAY: RGB = [70, 76, 90];
const BUILDING_NIGHT: RGB = [28, 31, 42];
const PULSE_FRAMES = 8;
const EVENT_COLORS: Record<string, RGB> = {
  accident: [255, 70, 50],
  flood: [60, 150, 255],
  motorcade: [200, 120, 255],
  closure: [255, 40, 40],
}; // emergency light alternation period (frames)

const ADDITIVE = {
  blend: true,
  blendColorOperation: "add",
  blendColorSrcFactor: "src-alpha",
  blendColorDstFactor: "one",
  blendAlphaOperation: "add",
  blendAlphaSrcFactor: "one",
  blendAlphaDstFactor: "one-minus-src-alpha",
  depthWriteEnabled: false,
} as const;
const FLAT = { depthWriteEnabled: false } as const;

export interface FrameLight {
  night: number;
  land: RGB;
}

interface TripsPrepared {
  speedColors: Uint8Array;
  classColors: Uint8Array;
}

export class Scene {
  private b: Bundle;
  private roadWidths: Float32Array;
  private roadBase = new Uint8Array(0);
  private roadBaseNight = -1;
  private tripsPrep = new Map<string, TripsPrepared>();
  private buildingData: { polygon: number[][]; h: number }[];
  private waterData: number[][][][];
  readonly ambient = new AmbientLight({ color: [255, 255, 255], intensity: 1 });
  readonly sun = new DirectionalLight({ color: [255, 255, 255], intensity: 1, direction: [0, 0, -1] });
  readonly effect: LightingEffect;

  constructor(bundle: Bundle) {
    this.b = bundle;
    const r = bundle.roads;
    this.roadWidths = new Float32Array(r.vertexClass.length);
    for (let i = 0; i < r.vertexClass.length; i++) this.roadWidths[i] = ROAD_WIDTH_M[r.vertexClass[i]!]!;
    this.buildingData = (bundle.buildings?.rings ?? []).map((ring, i) => ({ polygon: ring, h: bundle.buildings!.heights[i]! }));
    this.waterData = bundle.water?.polygons ?? [];
    this.effect = new LightingEffect({ ambient: this.ambient, sun: this.sun });
  }

  /** Sets the lights for frame i and returns the night factor and land colour. */
  light(i: number): FrameLight {
    const L = this.b.frames.light[i]!;
    const [night, sunI, ambI, dx, dy, dz, sr, sg, sb, ar, ag, ab] = L as number[];
    this.sun.intensity = sunI!;
    this.sun.color = [sr!, sg!, sb!];
    this.sun.direction = [dx!, dy!, dz!];
    this.ambient.intensity = ambI!;
    this.ambient.color = [ar!, ag!, ab!];
    return { night: night!, land: mix(LAND_DAY, LAND_NIGHT, night!) };
  }

  // ------------------------------------------------------------------ roads + heat

  private baseColors(night: number): Uint8Array {
    const q = Math.round(night * 50);
    if (q === this.roadBaseNight) return this.roadBase;
    const r = this.b.roads;
    const out = new Uint8Array(r.vertexClass.length * 4);
    const cols = ROAD_BASE_DAY.map((c, k) => mix(c, ROAD_BASE_NIGHT[k]!, q / 50));
    for (let i = 0; i < r.vertexClass.length; i++) {
      const c = cols[r.vertexClass[i]!]!;
      out[4 * i] = c[0];
      out[4 * i + 1] = c[1];
      out[4 * i + 2] = c[2];
      out[4 * i + 3] = 255;
    }
    this.roadBase = out;
    this.roadBaseNight = q;
    return out;
  }

  /** Edge values at sim time t, linearly interpolated between bin centres (NaN = no data). */
  edgeValues(h: Heat, t: number): Float32Array {
    const { bin_s, begin_s, n_bins, n_edges, levels, range } = h.info;
    const f = Math.min(Math.max((t - begin_s) / bin_s - 0.5, 0), n_bins - 1);
    const i0 = Math.floor(f);
    const i1 = Math.min(i0 + 1, n_bins - 1);
    const w = f - i0;
    const out = new Float32Array(n_edges);
    const a = h.values.subarray(i0 * n_edges, (i0 + 1) * n_edges);
    const c = h.values.subarray(i1 * n_edges, (i1 + 1) * n_edges);
    const span = (range[1] - range[0]) / levels;
    for (let e = 0; e < n_edges; e++) {
      const qa = a[e]!;
      const qc = c[e]!;
      if (qa === 255 && qc === 255) out[e] = NaN;
      else if (qa === 255) out[e] = range[0] + qc * span;
      else if (qc === 255) out[e] = range[0] + qa * span;
      else out[e] = range[0] + (qa + (qc - qa) * w) * span;
    }
    return out;
  }

  private heatColors(shot: ShotSpec, heatId: string, t: number, compareId: string | null): Uint8Array {
    const r = this.b.roads;
    const h = this.b.heat.get(heatId);
    const out = new Uint8Array(r.vertexClass.length * 4);
    if (!h) return out;
    const v = this.edgeValues(h, t);
    const base = compareId ? this.b.heat.get(compareId) : undefined;
    const bv = base ? this.edgeValues(base, t) : null;
    const half = this.b.manifest.diff_half_range[shot.layers.metric] ?? 0.25;
    const higherBetter = shot.layers.metric === "speed_rel";
    const [lo, hi] = h.info.range;
    for (let e = 0; e < r.n; e++) {
      let x = v[e]!;
      let col: Uint8Array = HEAT_LUT;
      let tt: number;
      let alpha = 235;
      if (bv) {
        x = x - bv[e]!;
        if (!(x === x)) continue;
        const signed = higherBetter ? x : -x; // > 0 = relief
        const mag = Math.min(1, Math.abs(signed) / half);
        if (mag < 0.04) continue; // unchanged edges stay base-coloured
        tt = 0.5 + signed / (2 * half);
        col = DIFF_LUT;
        alpha = Math.round(255 * Math.pow(mag, 0.6));
      } else {
        if (!(x === x)) continue;
        tt = (x - lo) / (hi - lo || 1);
        if (!higherBetter) tt = 1 - tt;
      }
      const k = Math.round(Math.min(1, Math.max(0, tt)) * 255) * 3;
      const p1 = r.starts[e + 1]!;
      for (let p = r.starts[e]!; p < p1; p++) {
        out[4 * p] = col[k]!;
        out[4 * p + 1] = col[k + 1]!;
        out[4 * p + 2] = col[k + 2]!;
        out[4 * p + 3] = alpha;
      }
    }
    return out;
  }

  private pathData(colors: Uint8Array) {
    const r = this.b.roads;
    return {
      length: r.n,
      startIndices: r.starts,
      attributes: {
        getPath: { value: r.positions, size: 2 },
        getColor: { value: colors, size: 4 },
        getWidth: { value: this.roadWidths, size: 1 },
      },
    };
  }

  // ------------------------------------------------------------------ trips

  private prepTrips(sid: string, tr: Trips): TripsPrepared {
    let p = this.tripsPrep.get(sid);
    if (p) return p;
    const n = tr.times.length;
    const speedColors = new Uint8Array(n * 4);
    const classColors = new Uint8Array(n * 4);
    for (let v = 0; v < tr.n; v++) {
      const cls = tr.classes[v]!;
      const cc = CLASS_COLORS[cls] ?? CLASS_COLORS[0]!;
      for (let q = tr.starts[v]!; q < tr.starts[v + 1]!; q++) {
        let rgb: RGB;
        if (cls === 3 || cls === 4 || cls === 5) rgb = cc;
        else {
          const s = Math.min(1, tr.speeds[q]! / tr.speedScale / SPEED_MAX_MS);
          const k = Math.round(s * 255) * 3;
          rgb = [SPEED_LUT[k]!, SPEED_LUT[k + 1]!, SPEED_LUT[k + 2]!];
        }
        speedColors.set([rgb[0], rgb[1], rgb[2], 255], 4 * q);
        classColors.set([cc[0], cc[1], cc[2], 255], 4 * q);
      }
    }
    p = { speedColors, classColors };
    this.tripsPrep.set(sid, p);
    return p;
  }

  /** Current position, colour and class of every vehicle on the road at sim time t. */
  heads(sid: string, tr: Trips, t: number, colorBy: "speed" | "class", frame: number) {
    const pos: number[] = [];
    const col: number[] = [];
    const rad: number[] = [];
    const emerg: number[] = [];
    const prep = this.prepTrips(sid, tr);
    const colors = colorBy === "class" ? prep.classColors : prep.speedColors;
    const blink = Math.floor(frame / PULSE_FRAMES) % 2 === 0;
    for (let v = 0; v < tr.n; v++) {
      const a = tr.starts[v]!;
      const b = tr.starts[v + 1]! - 1;
      if (t < tr.times[a]! || t > tr.times[b]!) continue;
      let lo = a;
      let hi = b;
      while (hi - lo > 1) {
        const mid = (lo + hi) >> 1;
        if (tr.times[mid]! <= t) lo = mid;
        else hi = mid;
      }
      const t0 = tr.times[lo]!;
      const t1 = tr.times[hi]!;
      const f = t1 > t0 ? (t - t0) / (t1 - t0) : 0;
      const x = tr.positions[2 * lo]! + (tr.positions[2 * hi]! - tr.positions[2 * lo]!) * f;
      const y = tr.positions[2 * lo + 1]! + (tr.positions[2 * hi + 1]! - tr.positions[2 * lo + 1]!) * f;
      const cls = tr.classes[v]!;
      pos.push(x, y);
      if (cls === 3) {
        const c = blink ? CLASS_COLORS[3]! : EMERGENCY_BLUE;
        col.push(c[0], c[1], c[2], 255);
        rad.push(5);
        emerg.push(x, y);
      } else {
        col.push(colors[4 * lo]!, colors[4 * lo + 1]!, colors[4 * lo + 2]!, 255);
        rad.push(cls === 1 || cls === 2 ? 3.8 : 3);
      }
    }
    return { pos: new Float64Array(pos), col: new Uint8Array(col), rad: new Float32Array(rad), emerg };
  }

  private tripLayers(sid: string, t: number, colorBy: "speed" | "class", night: number, frame: number, suffix: string): Layer[] {
    const tr = this.b.trips.get(sid);
    if (!tr) return [];
    const prep = this.prepTrips(sid, tr);
    const data = {
      length: tr.n,
      startIndices: tr.starts,
      attributes: {
        getPath: { value: tr.positions, size: 2 },
        getTimestamps: { value: tr.times, size: 1 },
        getColor: { value: colorBy === "class" ? prep.classColors : prep.speedColors, size: 4 },
      },
    };
    const h = this.heads(sid, tr, t, colorBy, frame);
    const n = h.rad.length;
    const headData = {
      length: n,
      attributes: {
        getPosition: { value: h.pos, size: 2 },
        getFillColor: { value: h.col, size: 4 },
        getRadius: { value: h.rad, size: 1 },
      },
    };
    const layers: Layer[] = [
      new TripsLayer({
        id: `trips-${sid}${suffix}`,
        data: data as never,
        _pathType: "open",
        currentTime: t,
        trailLength: this.b.manifest.trail_s,
        fadeTrail: true,
        widthUnits: "meters",
        getWidth: 2.6,
        widthMinPixels: 1.6,
        capRounded: true,
        jointRounded: true,
        opacity: 0.85,
        parameters: ADDITIVE,
      }) as unknown as Layer,
      new ScatterplotLayer({
        id: `heads-glow-${sid}${suffix}`,
        data: headData as never,
        radiusUnits: "meters",
        radiusScale: 2.4,
        radiusMinPixels: 3,
        opacity: 0.14 + 0.3 * night,
        parameters: ADDITIVE,
      }) as unknown as Layer,
      new ScatterplotLayer({
        id: `heads-${sid}${suffix}`,
        data: headData as never,
        radiusUnits: "meters",
        radiusMinPixels: 2,
        opacity: 1,
      }) as unknown as Layer,
    ];
    if (h.emerg.length) {
      const pulse = 0.5 + 0.5 * Math.sin((frame / PULSE_FRAMES) * Math.PI);
      const blink = Math.floor(frame / PULSE_FRAMES) % 2 === 0;
      layers.push(
        new ScatterplotLayer({
          id: `emergency-halo-${sid}${suffix}`,
          data: h.emerg.length / 2 > 0 ? Array.from({ length: h.emerg.length / 2 }, (_, k) => [h.emerg[2 * k], h.emerg[2 * k + 1]]) : [],
          getPosition: (d: number[]) => d as [number, number],
          getFillColor: [...(blink ? CLASS_COLORS[3]! : EMERGENCY_BLUE), 255],
          radiusUnits: "meters",
          getRadius: 18 + 26 * pulse,
          radiusMinPixels: 8,
          opacity: 0.55,
          parameters: ADDITIVE,
        }) as unknown as Layer,
      );
    }
    return layers;
  }

  // ------------------------------------------------------------------ overlays

  private overlayLayers(shot: ShotSpec, t: number, frame: number, suffix: string, side: string | null): Layer[] {
    const out: Layer[] = [];
    const want = new Set(shot.layers.overlays);
    // split screen: each half shows only its own source's overlays
    const sids = (side ? [side] : [shot.layers.heat, shot.layers.trips, shot.layers.route_source]).filter(
      (x): x is string => !!x,
    );
    const pulse = 0.5 + 0.5 * Math.sin((frame / 12) * Math.PI);
    const seen = new Set<string>();
    for (const sid of sids) {
      if (seen.has(sid)) continue;
      seen.add(sid);
      const o: OverlaySet | undefined = this.b.overlays[sid];
      if (!o) continue;
      const key = `${sid}${suffix}`;
      if (want.has("phases") && o.phases.length) {
        const visible = o.phases.filter((p) => t >= p.begin_s);
        out.push(
          new SolidPolygonLayer({
            id: `phases-${key}`,
            data: visible,
            getPolygon: (p: OverlaySet["phases"][number]) => p.ring as never,
            getFillColor: (p: OverlaySet["phases"][number]) => {
              const c = BAND_COLORS[p.band % BAND_COLORS.length]!;
              const on = t <= p.end_s ? Math.min(1, (t - p.begin_s) / 60) : Math.max(0.35, 1 - (t - p.end_s) / 600);
              return [c[0], c[1], c[2], Math.round(70 * on)];
            },
            updateTriggers: { getFillColor: t },
            parameters: FLAT,
          }) as unknown as Layer,
          new PathLayer({
            id: `phases-line-${key}`,
            data: visible,
            getPath: (p: OverlaySet["phases"][number]) => p.ring as never,
            getColor: (p: OverlaySet["phases"][number]) => [...BAND_COLORS[p.band % BAND_COLORS.length]!, 220] as [number, number, number, number],
            widthUnits: "pixels",
            getWidth: 2,
            parameters: FLAT,
          }) as unknown as Layer,
          new ScatterplotLayer({
            id: `phases-pts-${key}`,
            data: visible.flatMap((p) => p.points.filter((q) => q[2]! <= t).map((q) => ({ q, band: p.band }))),
            getPosition: (d: { q: number[] }) => [d.q[0]!, d.q[1]!],
            getFillColor: (d: { band: number }) => [...BAND_COLORS[d.band % BAND_COLORS.length]!, 200] as [number, number, number, number],
            radiusUnits: "meters",
            getRadius: 9,
            radiusMinPixels: 1.5,
            parameters: ADDITIVE,
          }) as unknown as Layer,
        );
      }
      if (want.has("zone") && o.zone) {
        const z = o.zone;
        out.push(
          new PathLayer({
            id: `zone-${key}`,
            data: [z.ring],
            getPath: (d: number[][]) => d as [number, number][],
            getColor: [255, 225, 70, t >= z.begin_s ? 230 : 110],
            widthUnits: "pixels",
            getWidth: 2.5,
            parameters: FLAT,
          }) as unknown as Layer,
        );
      }
      if (want.has("contraflow")) {
        const cf = o.contraflow.filter((c) => t >= c.begin_s).flatMap((c) => c.paths);
        if (cf.length) out.push(...this.glowPaths(`contraflow-${key}`, cf, [255, 190, 40], 14, 0.55 + 0.35 * pulse));
      }
      if (want.has("routes") && sid === shot.layers.route_source) {
        const paths = o.routes.flatMap((r) => r.paths);
        out.push(...this.glowPaths(`route-${key}`, paths, [120, 230, 255], 12, 0.8));
      }
      if (want.has("closures")) {
        const paths = o.closures.filter((c) => t >= c.begin_s && t <= c.end_s).flatMap((c) => c.paths);
        if (paths.length) out.push(...this.glowPaths(`closures-${key}`, paths, [255, 40, 40], 12, 0.9));
      }
      if (want.has("events")) {
        const active = o.events.filter((e) => t >= e.begin_s && t <= e.end_s);
        for (const type of [...new Set(active.map((e) => e.type))]) {
          const paths = active.filter((e) => e.type === type).flatMap((e) => e.paths);
          const c = EVENT_COLORS[type] ?? EVENT_COLORS.accident!;
          if (paths.length) out.push(...this.glowPaths(`events-${type}-${key}`, paths, c, 16, 0.6 + 0.4 * pulse));
        }
        const pts = active.map((e) => e.point ?? midpoint(e.paths)).filter((p): p is number[] => !!p);
        if (pts.length)
          out.push(
            new ScatterplotLayer({
              id: `events-pulse-${key}`,
              data: pts.filter((_, k) => active[k]!.type === "accident"),
              getPosition: (d: number[]) => [d[0]!, d[1]!],
              getFillColor: [255, 70, 50, 255],
              radiusUnits: "meters",
              getRadius: 30 + 60 * pulse,
              radiusMinPixels: 6,
              opacity: 0.35,
              parameters: ADDITIVE,
            }) as unknown as Layer,
          );
      }
      if (want.has("exits") && o.exits.length) {
        out.push(
          new ScatterplotLayer({
            id: `exits-${key}`,
            data: o.exits.filter((e) => e.point),
            getPosition: (e: OverlaySet["exits"][number]) => e.point as [number, number],
            getFillColor: [90, 255, 150, 255],
            getLineColor: [10, 40, 20, 255],
            stroked: true,
            lineWidthMinPixels: 1.5,
            radiusUnits: "meters",
            getRadius: 22,
            radiusMinPixels: 5,
          }) as unknown as Layer,
        );
      }
    }
    return out;
  }

  private glowPaths(id: string, paths: number[][][], c: RGB, widthM: number, alpha: number): Layer[] {
    return [
      new PathLayer({
        id: `${id}-glow`,
        data: paths,
        getPath: (d: number[][]) => d as [number, number][],
        getColor: [c[0], c[1], c[2], Math.round(90 * alpha)],
        widthUnits: "meters",
        getWidth: widthM * 3,
        widthMinPixels: 6,
        capRounded: true,
        jointRounded: true,
        parameters: ADDITIVE,
      }) as unknown as Layer,
      new PathLayer({
        id: `${id}-core`,
        data: paths,
        getPath: (d: number[][]) => d as [number, number][],
        getColor: [c[0], c[1], c[2], Math.round(255 * alpha)],
        widthUnits: "meters",
        getWidth: widthM * 0.6,
        widthMinPixels: 2,
        capRounded: true,
        jointRounded: true,
        parameters: ADDITIVE,
      }) as unknown as Layer,
    ];
  }

  // ------------------------------------------------------------------ frame

  layers(i: number, night: number): Layer[] {
    const fr = this.b.frames;
    const shot = this.b.manifest.shots[fr.shot[i]!]!;
    const t = fr.sim_t[i]!;
    const L = shot.layers;
    const out: Layer[] = [];
    if (this.waterData.length)
      out.push(
        new SolidPolygonLayer({
          id: "water",
          data: this.waterData,
          getPolygon: (d: number[][][]) => d as never,
          getFillColor: [...mix(WATER_DAY, WATER_NIGHT, night), 255] as [number, number, number, number],
          updateTriggers: { getFillColor: Math.round(night * 50) },
          parameters: FLAT,
        }) as unknown as Layer,
      );
    const sides: [string | null, string | null, string, string | null][] =
      L.mode === "split" && L.split
        ? [
            [L.split[0], L.split[0], "@left", null],
            [L.split[1], L.split[1], "@right", null],
          ]
        : [[L.heat, L.trips, "@both", L.mode === "diff" ? L.compare : null]];
    out.push(
      new PathLayer({
        id: "roads-base@both",
        data: this.pathData(this.baseColors(night)) as never,
        _pathType: "open",
        widthUnits: "meters",
        widthMinPixels: 0.5,
        opacity: 0.55 + 0.25 * night,
        parameters: FLAT,
      }) as unknown as Layer,
    );
    for (const [heat, , suffix, compare] of sides) {
      if (!heat || !this.b.heat.has(heat)) continue;
      const colors = this.heatColors(shot, heat, t, compare);
      const data = this.pathData(colors);
      const tripsOn = !!L.trips || L.mode === "split";
      out.push(
        new PathLayer({
          id: `heat-glow${suffix}`,
          data: data as never,
          _pathType: "open",
          widthUnits: "meters",
          widthScale: tripsOn && !compare ? 1.8 : 3.2,
          widthMinPixels: compare ? 3 : 2,
          opacity: (tripsOn && !compare ? 0.08 : 0.2) + 0.15 * night,
          parameters: ADDITIVE,
        }) as unknown as Layer,
        new PathLayer({
          id: `heat${suffix}`,
          data: data as never,
          _pathType: "open",
          widthUnits: "meters",
          widthScale: tripsOn && !compare ? 0.7 : 1,
          widthMinPixels: compare ? 1.6 : 0.9,
          opacity: tripsOn && !compare ? 0.5 : 0.95,
          parameters: FLAT,
        }) as unknown as Layer,
      );
    }
    if (L.buildings && this.buildingData.length)
      out.push(
        new SolidPolygonLayer({
          id: "buildings@both",
          data: this.buildingData,
          extruded: true,
          getPolygon: (d: { polygon: number[][] }) => d.polygon as never,
          getElevation: (d: { h: number }) => d.h,
          getFillColor: [...mix(BUILDING_DAY, BUILDING_NIGHT, night), 255] as [number, number, number, number],
          updateTriggers: { getFillColor: Math.round(night * 50) },
          material: { ambient: 0.45, diffuse: 0.65, shininess: 24, specularColor: [70, 74, 82] },
        }) as unknown as Layer,
      );
    if (L.outline) {
      const ring = [...L.outline, L.outline[0]!].map((p) => [p[0], p[1]]);
      out.push(...this.glowPaths("outline@both", [ring], [255, 236, 170], 30, 0.75));
    }
    if (L.line && L.line.length > 1) {
      const path = L.line.map((p) => [p[0], p[1]]);
      out.push(...this.glowPaths("line@both", [path], [120, 230, 255], 40, 0.9));
    }
    if (L.stations && L.stations.length)
      out.push(
        new ScatterplotLayer({
          id: "stations@both",
          data: L.stations,
          getPosition: (p: [number, number]) => p,
          getFillColor: [235, 252, 255, 255],
          getLineColor: [20, 120, 160, 255],
          stroked: true,
          lineWidthMinPixels: 2,
          radiusUnits: "meters",
          getRadius: 90,
          radiusMinPixels: 4,
        }) as unknown as Layer,
      );
    for (const [, trips, suffix] of sides) {
      out.push(...this.overlayLayers(shot, t, i, suffix, L.mode === "split" ? trips : null));
      if (trips) out.push(...this.tripLayers(trips, t, L.color_by, night, i, suffix));
    }
    return out;
  }
}

export function midpoint(paths: number[][][]): number[] | null {
  const p = paths[Math.floor(paths.length / 2)];
  if (!p || !p.length) return null;
  return p[Math.floor(p.length / 2)] ?? null;
}
