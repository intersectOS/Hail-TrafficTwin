// Map annotations for films: street, district and landmark labels plus overlay callouts, drawn as
// HTML over the deck canvas (the browser shapes Arabic; deck.gl's TextLayer does not).
// Pure function of (bundle, frame index): placement for frame j depends only on frame j's camera,
// shot, sim time and HUD layout, and a label's opacity at frame i is the share of frames
// i-K..i in which it passes the greedy placement, so frames can be rendered in any order.
// No letter-spacing anywhere (house style).
import { WebMercatorViewport } from "@deck.gl/core";

import type { Bundle } from "./data";
import type { Labels, OverlaySet, ShotLabels, ShotSpec } from "./types";
import type { RGB } from "./palette";
import { midpoint } from "./scene";

export interface Rect {
  x0: number;
  y0: number;
  x1: number;
  y1: number;
}

// Display choices (not model assumptions).
const STREET_MIN_ZOOM = [11.5, 12.5, 14.0, 15.0, 16.0]; // deck zoom at which each road class labels
const STREET_SIZE = [18, 17, 16, 15, 14]; // px at 1080p (the Arabic line is drawn at the same size)
const DISTRICT_FULL_ZOOM = 13.3;
const DISTRICT_OUT_ZOOM = 13.8;
const SMOOTH_K = 8; // opacity = share of frames i-K..i placing the label
const MAX_ANCHORS = 600; // street anchors evaluated per frame and half
const REPEAT_PX = 350; // a street name at most once per this distance (px at 1080p)
const PAD = 6; // collision padding (px at 1080p)
const EDGE = 6; // keep labels this far inside the viewport
const ALONG_M = 30; // metres along the road bearing used to orient a label
const HORIZON_PITCH = 40;
const HORIZON_TOP = 0.12; // skip anchors in the top 12 % of a pitched view
const LEADER = 36; // callout leader, px at 1080p on each axis (~51 px diagonal)
const CACHE = 64;
const JUMP_ZOOM = 0.25; // camera change between two frames that counts as a cut
const JUMP_DEG = 8;
const JUMP_PX = 120;

const FONT = `-apple-system, "SF Pro Text", "Helvetica Neue", "Geeza Pro", Arial, sans-serif`;
const AR_FONT = `"Geeza Pro", "SF Arabic", -apple-system, "Helvetica Neue", Arial, sans-serif`;
const LINE = 1.18;
// Landmark marker: a bullet glyph (text rasterizes identically whatever was drawn before; a CSS
// circle's anti-aliasing was seen to vary with render order).
const DOT = "\u25CF";
const DOT_SIZE = 12; // px at 1080p
const DOT_GAP = 5;

const CALLOUT_COLORS: Record<string, RGB> = {
  accident: [255, 70, 50],
  flood: [60, 150, 255],
  motorcade: [200, 120, 255],
  closures: [255, 40, 40],
  exits: [90, 255, 150],
  contraflow: [255, 190, 40],
};
const CALLOUT_KINDS = ["events", "closures", "exits", "contraflow"] as const;
const CALLOUT_SIDES: [number, number][] = [
  [1, 1],
  [-1, 1],
  [1, -1],
  [-1, -1],
];
type CalloutKind = (typeof CALLOUT_KINDS)[number];

const CSS = `
.cin-anno { position: absolute; top: 0; height: 100%; overflow: hidden; z-index: 0; }
.cin-lb { position: absolute; left: 0; top: 0; transform-origin: 0 0; white-space: nowrap; text-align: center; letter-spacing: normal; }
.cin-lb div { white-space: nowrap; }
.cin-lb-st { color: #eef2f7; text-shadow: 0 0 2px rgba(0,0,0,0.95), 0 0 4px rgba(0,0,0,0.85), 0 0 8px rgba(0,0,0,0.6); }
.cin-lb-st .ar { color: #d4dbe6; }
.cin-lb-di { color: #f3e6cf; text-shadow: 0 0 3px rgba(0,0,0,0.9), 0 0 9px rgba(0,0,0,0.7); }
.cin-lb-lm { display: flex; align-items: center; text-align: left; color: #f0c46a; text-shadow: 0 0 2px rgba(0,0,0,0.95), 0 0 6px rgba(0,0,0,0.75); }
.cin-lb-lm .dot { flex: none; color: #e7b75f; }
.cin-co svg { position: absolute; left: 0; top: 0; width: 1px; height: 1px; overflow: visible; }
.cin-co .box { position: absolute; background: rgba(10,13,20,0.82); color: #f2f4f8; white-space: nowrap; box-sizing: border-box; }
`;

interface Desc {
  key: string;
  kind: "co" | "lm" | "di" | "st";
  half: number;
  lon: number;
  lat: number;
  bearing: number;
  cls: number;
  en: string;
  ar: string | null;
  color: RGB;
  prio: number;
  w: number; // unrotated content box (px)
  h: number;
  lines: { text: string; font: string; lh: number; ar: boolean }[];
}

interface Geom {
  x: number; // local to the half (px)
  y: number;
  a: number; // rotation (deg)
  side: number; // callouts: +1 right, -1 left of the anchor
  up: number; // callouts: +1 above, -1 below the anchor
  r: Rect; // collision box (local px, padded)
}

interface Ctx {
  vp: WebMercatorViewport;
  w: number;
  h: number;
  off: number;
  pitched: boolean;
  zoom: number;
}

const DEFAULT_FLAGS: ShotLabels = { streets: true, districts: true, landmarks: true, callouts: true };

export class Annotator {
  private b: Bundle;
  private labels: Labels | null;
  private W: number;
  private H: number;
  private u: number;
  private reserved: (frame: number) => Rect[];
  private layers: HTMLElement[];
  private els = new Map<string, HTMLElement>();
  private descs = new Map<string, Desc>();
  private cache = new Map<number, Map<string, Geom>>();
  private measure: CanvasRenderingContext2D;
  private widths = new Map<string, number>();
  // flat street anchors
  private aLon: Float64Array;
  private aLat: Float64Array;
  private aBear: Float64Array;
  private aStreet: Int32Array;
  private aIdx: Int32Array;
  private streetRank: Int32Array;

  constructor(parent: HTMLElement, b: Bundle, size: { width: number; height: number }, reserved: (frame: number) => Rect[]) {
    this.b = b;
    this.labels = b.labels;
    this.W = size.width;
    this.H = size.height;
    this.u = b.manifest.height / 1080;
    this.reserved = reserved;
    const style = document.createElement("style");
    style.textContent = CSS;
    document.head.appendChild(style);
    this.layers = [0, 1].map(() => {
      const d = document.createElement("div");
      d.className = "cin-anno";
      parent.appendChild(d);
      return d;
    });
    this.measure = document.createElement("canvas").getContext("2d")!;
    const st = this.labels?.streets ?? [];
    const n = st.reduce((s, x) => s + x.anchors.length, 0);
    this.aLon = new Float64Array(n);
    this.aLat = new Float64Array(n);
    this.aBear = new Float64Array(n);
    this.aStreet = new Int32Array(n);
    this.aIdx = new Int32Array(n);
    let k = 0;
    st.forEach((s, si) =>
      s.anchors.forEach((a, ai) => {
        this.aLon[k] = a[0];
        this.aLat[k] = a[1];
        this.aBear[k] = a[2];
        this.aStreet[k] = si;
        this.aIdx[k] = ai;
        k++;
      }),
    );
    // priority: road class, then the file's order (stable)
    const order = st.map((_, i) => i).sort((p, q) => clsOf(st[p]!.cls) - clsOf(st[q]!.cls) || p - q);
    this.streetRank = new Int32Array(st.length);
    order.forEach((si, r) => (this.streetRank[si] = r));
  }

  // ------------------------------------------------------------------ text metrics

  private textW(text: string, font: string): number {
    const k = `${font}|${text}`;
    let w = this.widths.get(k);
    if (w === undefined) {
      this.measure.font = font;
      w = this.measure.measureText(text).width;
      this.widths.set(k, w);
    }
    return w;
  }

  private lines(en: string, ar: string | null, size: number, weight: number, arSize: number, arWeight: number) {
    const u = this.u;
    const out = [{ text: en, font: `${weight} ${size * u}px ${FONT}`, lh: Math.round(size * u * LINE), ar: false }];
    if (ar && ar.trim() && ar.trim() !== en.trim())
      out.push({ text: ar, font: `${arWeight} ${arSize * u}px ${AR_FONT}`, lh: Math.round(arSize * u * LINE), ar: true });
    return out;
  }

  private desc(key: string, make: () => Omit<Desc, "w" | "h" | "key">, extraW = 0, extraH = 0): Desc {
    let d = this.descs.get(key);
    if (d) return d;
    const p = make();
    const w = Math.max(...p.lines.map((l) => this.textW(l.text, l.font))) + extraW;
    const h = p.lines.reduce((s, l) => s + l.lh, 0) + extraH;
    d = { ...p, key, w: Math.ceil(w), h };
    this.descs.set(key, d);
    return d;
  }

  private streetDesc(half: number, tag: string, k: number): Desc {
    const si = this.aStreet[k]!;
    const ai = this.aIdx[k]!;
    const s = this.labels!.streets[si]!;
    const c = clsOf(s.cls);
    return this.desc(`${tag}|st|${si}|${ai}`, () => ({
      kind: "st",
      half,
      lon: this.aLon[k]!,
      lat: this.aLat[k]!,
      bearing: this.aBear[k]!,
      cls: c,
      en: s.en,
      ar: s.ar,
      color: [0, 0, 0],
      prio: 3_000_000 + this.streetRank[si]! * 1000 + Math.min(ai, 999),
      lines: this.lines(s.en, s.ar, STREET_SIZE[c]!, c <= 1 ? 600 : 500, STREET_SIZE[c]!, 500),
    }));
  }

  private districtDesc(half: number, tag: string, k: number): Desc {
    const d = this.labels!.districts[k]!;
    return this.desc(`${tag}|di|${k}`, () => ({
      kind: "di",
      half,
      lon: d.lon,
      lat: d.lat,
      bearing: 0,
      cls: 0,
      en: d.en,
      ar: d.ar,
      color: [0, 0, 0],
      prio: 2_000_000 + k,
      lines: this.lines(d.en, d.ar, 22, 300, 20, 400),
    }));
  }

  private dotW(): number {
    return Math.ceil(this.textW(DOT, `${Math.round(DOT_SIZE * this.u)}px ${FONT}`));
  }

  private landmarkDesc(half: number, tag: string, k: number): Desc {
    const d = this.labels!.landmarks[k]!;
    const dot = this.dotW() + Math.round(DOT_GAP * this.u);
    return this.desc(
      `${tag}|lm|${k}`,
      () => ({
        kind: "lm",
        half,
        lon: d.lon,
        lat: d.lat,
        bearing: 0,
        cls: 0,
        en: d.en,
        ar: d.ar,
        color: [231, 183, 95],
        prio: 1_000_000 + k,
        lines: this.lines(d.en, d.ar, 15, 600, 15, 500),
      }),
      dot,
    );
  }

  private calloutDesc(half: number, tag: string, src: string, kind: CalloutKind, idx: number, text: string, at: number[], color: RGB, prio: number): Desc {
    const u = this.u;
    return this.desc(
      `${tag}|co|${src}|${kind}|${idx}`,
      () => ({
        kind: "co",
        half,
        lon: at[0]!,
        lat: at[1]!,
        bearing: 0,
        cls: 0,
        en: text,
        ar: null,
        color,
        prio,
        lines: [{ text, font: `600 ${15 * u}px ${FONT}`, lh: Math.round(15 * u * 1.25), ar: false }],
      }),
      Math.round(21 * u), // 9 + 9 padding + 3 border
      Math.round(10 * u),
    );
  }

  // ------------------------------------------------------------------ placement

  private flags(shot: ShotSpec): ShotLabels {
    return shot.hud.labels ?? DEFAULT_FLAGS;
  }

  private ctx(j: number, half: number, split: boolean): Ctx {
    const cam = this.b.frames.camera[j]!;
    const w = split ? this.W / 2 : this.W;
    const vp = new WebMercatorViewport({ width: w, height: this.H, longitude: cam[0]!, latitude: cam[1]!, zoom: cam[2]!, pitch: cam[3]!, bearing: cam[4]! });
    return { vp, w, h: this.H, off: half * w, pitched: cam[3]! > HORIZON_PITCH, zoom: cam[2]! };
  }

  private project(c: Ctx, lon: number, lat: number): [number, number] | null {
    const p = c.vp.project([lon, lat]);
    const x = p[0]!;
    const y = p[1]!;
    if (!Number.isFinite(x) || !Number.isFinite(y)) return null;
    const e = EDGE * this.u;
    if (x < e || x > c.w - e || y < e || y > c.h - e) return null;
    if (c.pitched && y < HORIZON_TOP * c.h) return null;
    return [x, y];
  }

  /** Geometry of a label at the frame of `c` (no collision test); null when not drawable. */
  private geom(d: Desc, c: Ctx, side = 1, up = 1): Geom | null {
    const p = this.project(c, d.lon, d.lat);
    if (!p) return null;
    let a = 0;
    if (d.kind === "st") {
      const br = (d.bearing * Math.PI) / 180;
      const lat2 = d.lat + (ALONG_M * Math.cos(br)) / 111320;
      const lon2 = d.lon + (ALONG_M * Math.sin(br)) / (111320 * Math.cos((d.lat * Math.PI) / 180));
      const q = c.vp.project([lon2, lat2]);
      const dx = q[0]! - p[0];
      const dy = q[1]! - p[1];
      if (Number.isFinite(dx) && Number.isFinite(dy) && dx * dx + dy * dy > 1e-6) {
        a = (Math.atan2(dy, dx) * 180) / Math.PI;
        if (a > 90) a -= 180;
        else if (a < -90) a += 180;
      }
    }
    const g: Geom = { x: p[0], y: p[1], a, side, up, r: { x0: 0, y0: 0, x1: 0, y1: 0 } };
    g.r = this.box(d, g);
    return g;
  }

  /** Collision box (local px) of a placed label. */
  private box(d: Desc, g: Omit<Geom, "r">): Rect {
    const pad = PAD * this.u;
    if (d.kind === "st") {
      const r = (g.a * Math.PI) / 180;
      const cw = Math.abs(d.w * Math.cos(r)) + Math.abs(d.h * Math.sin(r));
      const ch = Math.abs(d.w * Math.sin(r)) + Math.abs(d.h * Math.cos(r));
      return { x0: g.x - cw / 2 - pad, y0: g.y - ch / 2 - pad, x1: g.x + cw / 2 + pad, y1: g.y + ch / 2 + pad };
    }
    if (d.kind === "lm") {
      const dot = this.dotW();
      return { x0: g.x - dot / 2 - pad, y0: g.y - d.h / 2 - pad, x1: g.x - dot / 2 + d.w + pad, y1: g.y + d.h / 2 + pad };
    }
    if (d.kind === "co") {
      const L = LEADER * this.u;
      const ex = g.x + g.side * L;
      const ey = g.y - g.up * L;
      const bx0 = g.side > 0 ? ex : ex - d.w;
      return {
        x0: Math.min(g.x, bx0) - pad,
        y0: Math.min(g.y, ey - d.h / 2) - pad,
        x1: Math.max(g.x, bx0 + d.w) + pad,
        y1: Math.max(g.y, ey + d.h / 2) + pad,
      };
    }
    return { x0: g.x - d.w / 2 - pad, y0: g.y - d.h / 2 - pad, x1: g.x + d.w / 2 + pad, y1: g.y + d.h / 2 + pad };
  }

  private inside(r: Rect, c: Ctx): boolean {
    const e = EDGE * this.u - PAD * this.u;
    return r.x0 >= e && r.y0 >= e && r.x1 <= c.w - e && r.y1 <= c.h - e;
  }

  private callouts(shot: ShotSpec, t: number, split: boolean): { half: number; d: Desc }[] {
    const want = new Set(shot.layers.overlays);
    const L = shot.layers;
    const sides: [number, string[]][] = split && L.split
      ? [
          [0, [L.split[0]]],
          [1, [L.split[1]]],
        ]
      : [[0, [...new Set([L.heat, L.trips, L.route_source].filter((x): x is string => !!x))]]];
    const out: { half: number; d: Desc }[] = [];
    let prio = 0;
    for (const [half, sids] of sides) {
      for (const sid of sids) {
        const o: OverlaySet | undefined = this.b.overlays[sid];
        if (!o) continue;
        for (const kind of CALLOUT_KINDS) {
          if (!want.has(kind)) continue;
          const items = (o[kind] ?? []) as { callout?: string; point?: number[]; paths: number[][][]; begin_s: number; end_s?: number; type?: string }[];
          items.forEach((it, idx) => {
            prio++;
            if (!it.callout) return;
            const active =
              kind === "exits" ? true : kind === "contraflow" ? t >= it.begin_s : t >= it.begin_s && t <= (it.end_s ?? Infinity);
            if (!active) return;
            const at = it.point ?? midpoint(it.paths);
            if (!at) return;
            const color = kind === "events" ? (CALLOUT_COLORS[it.type ?? ""] ?? CALLOUT_COLORS.accident!) : CALLOUT_COLORS[kind]!;
            out.push({ half, d: this.calloutDesc(half, viewTag(half, split), sid, kind, idx, it.callout, at, color, prio) });
          });
        }
      }
    }
    return out;
  }

  /** Greedy placement for frame j: key -> geometry of every label that passes. */
  private place(j: number): Map<string, Geom> {
    const hit = this.cache.get(j);
    if (hit) return hit;
    const fr = this.b.frames;
    const shot = this.b.manifest.shots[fr.shot[j]!]!;
    const split = shot.layers.mode === "split";
    const flags = this.flags(shot);
    const reserved = this.reserved(j);
    const t = fr.sim_t[j]!;
    const u = this.u;
    const out = new Map<string, Geom>();
    const callouts = flags.callouts ? this.callouts(shot, t, split) : [];
    for (let half = 0; half < (split ? 2 : 1); half++) {
      const c = this.ctx(j, half, split);
      const tag = viewTag(half, split);
      const taken: Rect[] = [];
      const free = (r: Rect) => {
        if (overlapsAny(r, taken, 0)) return false;
        return !overlapsAny(r, reserved, c.off);
      };
      // callouts first: up-right, else up-left (down-right / down-left when the HUD is in the way)
      const coTaken: Rect[] = [];
      for (const { half: h, d } of callouts) {
        if (h !== half) continue;
        let best: { g: Geom; r: Rect; score: number } | null = null;
        for (const [side, up] of CALLOUT_SIDES) {
          const g = this.geom(d, c, side, up);
          if (!g) break;
          const r = g.r;
          // off-screen or over the HUD: not placeable; over an earlier callout: allowed if no better side
          const score = !this.inside(r, c) || overlapsAny(r, reserved, c.off) ? 2 : overlapsAny(r, coTaken, 0) ? 1 : 0;
          if (!best || score < best.score) best = { g, r, score };
          if (score === 0) break;
        }
        if (!best || best.score === 2) continue;
        coTaken.push(best.r);
        taken.push(best.r);
        out.set(d.key, best.g);
      }
      if (!this.labels) continue;
      const tryPlace = (d: Desc) => {
        const g = this.geom(d, c);
        if (!g) return null;
        const r = g.r;
        if (!this.inside(r, c) || !free(r)) return null;
        taken.push(r);
        out.set(d.key, g);
        return g;
      };
      const radius = this.radius(c);
      const cam = fr.camera[j]!;
      const kx = 111320 * Math.cos((cam[1]! * Math.PI) / 180);
      const near = (lon: number, lat: number) => {
        const dx = (lon - cam[0]!) * kx;
        const dy = (lat - cam[1]!) * 110540;
        return dx * dx + dy * dy;
      };
      const r2 = radius * radius;
      if (flags.landmarks)
        this.labels.landmarks.forEach((lm, k) => {
          if (c.zoom < lm.min_zoom || c.zoom > lm.max_zoom || near(lm.lon, lm.lat) > r2) return;
          tryPlace(this.landmarkDesc(half, tag, k));
        });
      if (flags.districts && c.zoom < DISTRICT_OUT_ZOOM)
        this.labels.districts.forEach((di, k) => {
          if (near(di.lon, di.lat) > r2) return;
          tryPlace(this.districtDesc(half, tag, k));
        });
      if (flags.streets) {
        const st = this.labels.streets;
        const cand: number[] = [];
        const dist: number[] = [];
        for (let k = 0; k < this.aLon.length; k++) {
          const cls = clsOf(st[this.aStreet[k]!]!.cls);
          if (c.zoom < STREET_MIN_ZOOM[cls]!) continue;
          const d2 = near(this.aLon[k]!, this.aLat[k]!);
          if (d2 > r2) continue;
          cand.push(k);
          dist.push(d2);
        }
        let pick = cand.map((_, q) => q);
        if (pick.length > MAX_ANCHORS) pick = pick.sort((p, q) => dist[p]! - dist[q]! || p - q).slice(0, MAX_ANCHORS);
        const ks = pick.map((q) => cand[q]!);
        ks.sort((p, q) => this.streetRank[this.aStreet[p]!]! - this.streetRank[this.aStreet[q]!]! || p - q);
        const seen = new Map<string, [number, number][]>();
        const rep2 = (REPEAT_PX * u) ** 2;
        for (const k of ks) {
          const d = this.streetDesc(half, tag, k);
          const prev = seen.get(d.en);
          if (prev) {
            const g0 = this.geom(d, c);
            if (!g0 || prev.some(([x, y]) => (x - g0.x) ** 2 + (y - g0.y) ** 2 < rep2)) continue;
          }
          const g = tryPlace(d);
          if (!g) continue;
          if (prev) prev.push([g.x, g.y]);
          else seen.set(d.en, [[g.x, g.y]]);
        }
      }
    }
    this.cache.set(j, out);
    if (this.cache.size > CACHE) this.cache.delete(this.cache.keys().next().value!);
    return out;
  }

  /** True when the camera jumps between frames j-1 and j (a hard cut): label fades restart there. */
  private jump(j: number): boolean {
    const a = this.b.frames.camera[j - 1];
    const b = this.b.frames.camera[j];
    if (!a || !b) return false;
    const mpp = (40075016.686 * Math.cos((b[1]! * Math.PI) / 180)) / (512 * 2 ** b[2]!);
    const dx = (b[0]! - a[0]!) * 111320 * Math.cos((b[1]! * Math.PI) / 180);
    const dy = (b[1]! - a[1]!) * 110540;
    const db = Math.abs(((b[4]! - a[4]! + 540) % 360) - 180);
    return Math.abs(b[2]! - a[2]!) > JUMP_ZOOM || Math.abs(b[3]! - a[3]!) > JUMP_DEG || db > JUMP_DEG || Math.hypot(dx, dy) / mpp > JUMP_PX * this.u;
  }

  /** Ground distance (m) from the camera centre beyond which anchors cannot be on screen. */
  private radius(c: Ctx): number {
    const cam = c.vp;
    const mpp = (40075016.686 * Math.cos((cam.latitude * Math.PI) / 180)) / (512 * 2 ** cam.zoom);
    const pitch = (cam.pitch * Math.PI) / 180;
    return (Math.hypot(c.w, c.h) / 2) * mpp * (1 + 4 * Math.sin(pitch) ** 2);
  }

  // ------------------------------------------------------------------ drawing

  private element(d: Desc): HTMLElement {
    let e = this.els.get(d.key);
    if (e) return e;
    const u = this.u;
    e = document.createElement("div");
    e.style.zIndex = String(5_000_000 - d.prio);
    const lineEl = (l: Desc["lines"][number], parent: HTMLElement) => {
      const x = document.createElement("div");
      x.textContent = l.text;
      x.style.font = l.font;
      x.style.lineHeight = `${l.lh}px`;
      if (l.ar) {
        x.dir = "rtl";
        x.className = "ar";
      }
      parent.appendChild(x);
    };
    if (d.kind === "co") {
      e.className = "cin-lb cin-co";
      const ns = "http://www.w3.org/2000/svg";
      const svg = document.createElementNS(ns, "svg");
      const col = `rgb(${d.color.join(",")})`;
      const line = document.createElementNS(ns, "line");
      line.setAttribute("stroke", col);
      line.setAttribute("stroke-width", String(Math.max(1.5, 2 * u)));
      const dot = document.createElementNS(ns, "circle");
      dot.setAttribute("r", String(Math.max(2, 3.5 * u)));
      dot.setAttribute("fill", col);
      dot.setAttribute("stroke", "rgba(10,13,20,0.9)");
      dot.setAttribute("stroke-width", "1");
      svg.append(line, dot);
      const box = document.createElement("div");
      box.className = "box";
      box.style.width = `${d.w}px`;
      box.style.height = `${d.h}px`;
      box.style.padding = `${Math.round(5 * u)}px ${Math.round(9 * u)}px`;
      box.style.borderLeft = `${Math.round(3 * u)}px solid ${col}`;
      box.style.borderRadius = `${Math.round(3 * u)}px`;
      lineEl(d.lines[0]!, box);
      e.append(svg, box);
    } else if (d.kind === "lm") {
      e.className = "cin-lb cin-lb-lm";
      const dot = document.createElement("span");
      dot.className = "dot";
      dot.textContent = DOT;
      dot.style.font = `${Math.round(DOT_SIZE * u)}px ${FONT}`;
      dot.style.width = `${this.dotW()}px`;
      dot.style.marginRight = `${Math.round(DOT_GAP * u)}px`;
      const txt = document.createElement("div");
      e.append(dot, txt);
      d.lines.forEach((l) => lineEl(l, txt));
    } else {
      e.className = `cin-lb ${d.kind === "st" ? "cin-lb-st" : "cin-lb-di"}`;
      d.lines.forEach((l) => lineEl(l, e!));
    }
    this.layers[d.half]!.appendChild(e);
    this.els.set(d.key, e);
    return e;
  }

  private draw(d: Desc, g: Geom, e: HTMLElement): void {
    if (d.kind === "st" || d.kind === "di") {
      e.style.transform = `translate(${Math.round(g.x)}px,${Math.round(g.y)}px) rotate(${g.a.toFixed(2)}deg) translate(-50%,-50%)`;
    } else if (d.kind === "lm") {
      const dot = this.dotW();
      e.style.transform = `translate(${Math.round(g.x - dot / 2)}px,${Math.round(g.y - d.h / 2)}px)`;
    } else {
      const L = LEADER * this.u;
      e.style.transform = `translate(${Math.round(g.x)}px,${Math.round(g.y)}px)`;
      const line = e.querySelector("line")!;
      line.setAttribute("x1", "0");
      line.setAttribute("y1", "0");
      line.setAttribute("x2", String(g.side * L));
      line.setAttribute("y2", String(-g.up * L));
      const box = e.querySelector<HTMLElement>(".box")!;
      box.style.left = `${g.side > 0 ? L : -L - d.w}px`;
      box.style.top = `${-g.up * L - d.h / 2}px`;
    }
  }

  update(i: number): void {
    const fr = this.b.frames;
    const shot = this.b.manifest.shots[fr.shot[i]!]!;
    const split = shot.layers.mode === "split";
    const w = split ? this.W / 2 : this.W;
    this.layers.forEach((l, h) => {
      l.style.left = `${h * w}px`;
      l.style.width = `${w}px`;
      l.style.display = h === 0 || split ? "block" : "none";
    });
    const counts = new Map<string, number>();
    let j0 = Math.max(0, i - SMOOTH_K);
    for (let j = i; j > j0; j--)
      if (this.jump(j)) {
        j0 = j;
        break;
      }
    for (let j = j0; j <= i; j++) for (const k of this.place(j).keys()) counts.set(k, (counts.get(k) ?? 0) + 1);
    const cur = this.place(i);
    const ctxs: Ctx[] = [];
    const zoom = fr.camera[i]![2]!;
    const districtFade = Math.min(1, Math.max(0, (DISTRICT_OUT_ZOOM - zoom) / (DISTRICT_OUT_ZOOM - DISTRICT_FULL_ZOOM)));
    const used = new Set<string>();
    // labels placed in this frame first; labels fading out (placed only in earlier frames) are
    // drawn at this frame's position unless they would overlap something already drawn
    const keys = [...counts.keys()].map((k) => this.descs.get(k)!);
    keys.sort((p, q) => Number(cur.has(q.key)) - Number(cur.has(p.key)) || p.prio - q.prio || (p.key < q.key ? -1 : 1));
    const drawn: Rect[][] = [[], []];
    let reserved: Rect[] | undefined;
    for (const d of keys) {
      const key = d.key;
      const n = counts.get(key)!;
      if (d.half > 0 && !split) continue;
      let g = cur.get(key) ?? null;
      if (!g) {
        const c = (ctxs[d.half] ??= this.ctx(i, d.half, split));
        g = this.geom(d, c, 1, 1);
        if (g && d.kind === "co" && !this.inside(g.r, c)) g = this.geom(d, c, -1, 1);
        if (!g || !this.inside(g.r, c) || overlapsAny(g.r, drawn[d.half]!, 0) || overlapsAny(g.r, (reserved ??= this.reserved(i)), c.off)) continue;
      }
      const op = (n / (SMOOTH_K + 1)) * (d.kind === "di" ? districtFade : 1);
      if (op <= 0.001) continue;
      drawn[d.half]!.push(g.r);
      const e = this.element(d);
      this.draw(d, g, e);
      e.style.opacity = op.toFixed(3);
      e.style.display = "";
      used.add(key);
    }
    for (const [k, e] of this.els) {
      if (used.has(k)) continue;
      if (e.style.display !== "none") e.style.display = "none";
    }
  }
}

function viewTag(half: number, split: boolean): string {
  return split ? (half ? "R" : "L") : "M";
}

function clsOf(c: number): number {
  return Math.min(4, Math.max(0, Math.round(c)));
}

function overlapsAny(r: Rect, list: Rect[], off: number): boolean {
  for (const q of list) {
    if (r.x0 + off < q.x1 && r.x1 + off > q.x0 && r.y0 < q.y1 && r.y1 > q.y0) return true;
  }
  return false;
}
