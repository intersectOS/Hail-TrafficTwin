// HTML heads-up display over the deck canvas: title card, caption, clock, KPIs counting, legend,
// split labels and the "synthetic demand, uncalibrated" footer. Updated synchronously per frame.
// No letter-spacing anywhere (house style).
import { Annotator, type Rect } from "./annotate";
import type { Bundle } from "./data";
import type { Frames, KpiSpec, Manifest, ShotSpec } from "./types";
import { BAND_COLORS, CLASS_COLORS, DIFF_STOPS, HEAT_STOPS, SPEED_STOPS, gradientCss } from "./palette";

const CSS = `
.cin-root { position: absolute; inset: 0; overflow: hidden; font-family: -apple-system, "SF Pro Text", "Helvetica Neue", Arial, sans-serif; color: #f2f4f8; letter-spacing: normal; }
.cin-root * { letter-spacing: normal; box-sizing: border-box; }
.cin-hud { position: absolute; left: 0; right: 0; pointer-events: none; }
.cin-grad-top { position: absolute; left: 0; right: 0; top: 0; height: calc(var(--u) * 230px); background: linear-gradient(to bottom, rgba(0,0,0,0.62), rgba(0,0,0,0)); }
.cin-grad-bot { position: absolute; left: 0; right: 0; bottom: 0; height: calc(var(--u) * 250px); background: linear-gradient(to top, rgba(0,0,0,0.7), rgba(0,0,0,0)); }
.cin-cap { position: absolute; left: calc(var(--u) * 56px); top: calc(var(--u) * 44px); max-width: 62%; }
.cin-film { font-size: calc(var(--u) * 17px); font-weight: 600; color: #e7b75f; }
.cin-caption { font-size: calc(var(--u) * 34px); font-weight: 650; line-height: 1.15; margin-top: calc(var(--u) * 6px); text-shadow: 0 2px 12px rgba(0,0,0,0.6); }
.cin-detail { font-size: calc(var(--u) * 19px); line-height: 1.35; margin-top: calc(var(--u) * 10px); color: #cfd6e2; max-width: calc(var(--u) * 1050px); text-shadow: 0 1px 8px rgba(0,0,0,0.7); }
.cin-clock { position: absolute; right: calc(var(--u) * 56px); top: calc(var(--u) * 38px); text-align: right; }
.cin-time { font-size: calc(var(--u) * 58px); font-weight: 300; font-variant-numeric: tabular-nums; line-height: 1; }
.cin-tier { font-size: calc(var(--u) * 16px); color: #aeb7c6; margin-top: calc(var(--u) * 8px); }
.cin-kpis { position: absolute; left: calc(var(--u) * 56px); bottom: calc(var(--u) * 70px); display: flex; gap: calc(var(--u) * 44px); }
.cin-kpi-v { font-size: calc(var(--u) * 44px); font-weight: 600; font-variant-numeric: tabular-nums; line-height: 1.05; }
.cin-kpi-u { font-size: calc(var(--u) * 20px); font-weight: 500; color: #cfd6e2; margin-left: calc(var(--u) * 6px); }
.cin-kpi-l { font-size: calc(var(--u) * 16px); color: #aeb7c6; margin-top: calc(var(--u) * 6px); }
.cin-legend { position: absolute; right: calc(var(--u) * 56px); bottom: calc(var(--u) * 72px); width: calc(var(--u) * 300px); font-size: calc(var(--u) * 15px); color: #cfd6e2; }
.cin-legend-t { margin-bottom: calc(var(--u) * 7px); color: #e8ecf2; font-weight: 600; }
.cin-bar { height: calc(var(--u) * 9px); border-radius: calc(var(--u) * 5px); }
.cin-ends { display: flex; justify-content: space-between; margin-top: calc(var(--u) * 5px); }
.cin-chips { display: flex; flex-wrap: wrap; gap: calc(var(--u) * 6px) calc(var(--u) * 14px); }
.cin-chip { display: flex; align-items: center; gap: calc(var(--u) * 6px); }
.cin-dot { width: calc(var(--u) * 10px); height: calc(var(--u) * 10px); border-radius: 50%; }
.cin-footer { position: absolute; left: 0; right: 0; bottom: calc(var(--u) * 22px); text-align: center; font-size: calc(var(--u) * 15px); color: #c3cad6; }
.cin-footer b { color: #f0c46a; font-weight: 600; }
.cin-title { position: absolute; inset: 0; display: flex; flex-direction: column; align-items: center; justify-content: center; background: radial-gradient(ellipse at center, rgba(5,8,14,0.55), rgba(5,8,14,0.85)); }
.cin-title-k { font-size: calc(var(--u) * 20px); color: #e7b75f; font-weight: 600; }
.cin-title-h { font-size: calc(var(--u) * 76px); font-weight: 700; margin-top: calc(var(--u) * 12px); text-align: center; line-height: 1.05; }
.cin-title-s { font-size: calc(var(--u) * 26px); color: #cfd6e2; margin-top: calc(var(--u) * 18px); text-align: center; }
.cin-title-f { font-size: calc(var(--u) * 17px); color: #f0c46a; margin-top: calc(var(--u) * 40px); }
.cin-split { position: absolute; top: calc(var(--u) * 232px); width: 50%; text-align: center; font-size: calc(var(--u) * 24px); font-weight: 600; text-shadow: 0 2px 10px rgba(0,0,0,0.8); }
.cin-divider { position: absolute; top: 0; bottom: 0; left: 50%; width: 2px; margin-left: -1px; background: rgba(240,244,250,0.7); }
.cin-fade { position: absolute; inset: 0; background: #000; }
.cin-bars { position: absolute; left: 0; right: 0; background: #000; }
.cin-compass { width: calc(var(--u) * 54px); height: calc(var(--u) * 54px); margin: calc(var(--u) * 14px) 0 0 auto; border-radius: 50%; background: rgba(8,12,20,0.5); border: 1.5px solid rgba(240,244,250,0.55); }
.cin-compass svg { display: block; width: 100%; height: 100%; }
.cin-scale { position: absolute; right: calc(var(--u) * 56px); text-align: right; font-size: calc(var(--u) * 14px); color: #e8ecf2; text-shadow: 0 1px 6px rgba(0,0,0,0.8); }
.cin-scale-bar { height: calc(var(--u) * 7px); margin-top: calc(var(--u) * 4px); margin-left: auto; border: 2px solid #e8ecf2; border-top: none; box-shadow: 0 1px 4px rgba(0,0,0,0.5); }
.cin-keys { display: flex; flex-wrap: wrap; gap: calc(var(--u) * 6px) calc(var(--u) * 14px); margin-top: calc(var(--u) * 10px); }
.cin-sw-zone { width: calc(var(--u) * 15px); height: calc(var(--u) * 10px); border: 2px solid rgb(255,225,70); border-radius: calc(var(--u) * 2px); }
.cin-sw-line { width: calc(var(--u) * 18px); height: calc(var(--u) * 4px); border-radius: calc(var(--u) * 2px); }
.cin-sw-band { width: calc(var(--u) * 8px); height: calc(var(--u) * 10px); border-radius: calc(var(--u) * 1.5px); }
.cin-sw-bands { display: flex; gap: calc(var(--u) * 2px); }
.cin-sub { position: absolute; text-align: center; pointer-events: none; }
.cin-sub span { display: inline-block; max-width: 100%; padding: calc(var(--u) * 8px) calc(var(--u) * 18px); border-radius: calc(var(--u) * 10px); background: rgba(8,12,20,0.66); color: #f2f4f8; line-height: 1.3; text-shadow: 0 1px 4px rgba(0,0,0,0.5); }
`;

const COMPASS_SVG = `<svg viewBox="0 0 100 100"><g>
<polygon points="50,9 64,52 36,52" fill="#e7b75f"/><polygon points="50,91 64,52 36,52" fill="rgba(230,236,245,0.55)"/>
<text x="50" y="45" text-anchor="middle" font-size="19" font-weight="700" fill="#0e1520" font-family="-apple-system, Helvetica Neue, Arial, sans-serif">N</text></g></svg>`;

/** Overlay kinds that get a key chip in the legend (when annotations are on). */
const KEY_KINDS = ["zone", "exits", "contraflow", "phases"] as const;

interface ShotLayout {
  rects: Rect[];
  kpi: Rect | null;
  legend: Rect | null;
  scaleBottom: number;
}

interface SubLayout {
  line: number;
  alpha: number;
  left: number;
  width: number;
  bottom: number;
  font: number;
}

function formatKpi(k: KpiSpec, v: number): string {
  const sign = k.sign && v > 0 ? "+" : "";
  return `${sign}${v.toLocaleString("en-US", { minimumFractionDigits: k.decimals, maximumFractionDigits: k.decimals })}`;
}

/** Nice scale-bar length (1/2/5 x 10^n m) whose bar is at most maxPx, and its width in px. */
export function scaleBar(lat: number, zoom: number, maxPx: number): { m: number; px: number } {
  const mpp = (40075016.686 * Math.cos((lat * Math.PI) / 180)) / (512 * 2 ** zoom);
  let best = { m: 1, px: 1 / mpp };
  for (let e = 0; e < 7; e++)
    for (const f of [1, 2, 5]) {
      const m = f * 10 ** e;
      if (m / mpp <= maxPx) best = { m, px: m / mpp };
    }
  return best;
}

function el(tag: string, cls: string, parent: HTMLElement, text = ""): HTMLElement {
  const e = document.createElement(tag);
  e.className = cls;
  if (text) e.textContent = text;
  parent.appendChild(e);
  return e;
}

const TIER_TEXT: Record<string, string> = {
  A: "Tier A city, mesoscopic, 10 % population sample",
  B: "Tier B window, microscopic",
};

export class Hud {
  private m: Manifest;
  private fr: Frames;
  private root: HTMLElement;
  private cap: HTMLElement;
  private caption: HTMLElement;
  private detail: HTMLElement;
  private time: HTMLElement;
  private kpis: HTMLElement;
  private legend: HTMLElement;
  private title: HTMLElement;
  private fade: HTMLElement;
  private splitL: HTMLElement;
  private splitR: HTMLElement;
  private divider: HTMLElement;
  private shown = -1;
  private kpiEls: HTMLElement[] = [];
  private b: Bundle;
  private hud: HTMLElement;
  private area: { top: number; height: number };
  private anno: Annotator | null = null;
  private compass: SVGGElement | null = null;
  private scale: HTMLElement | null = null;
  private scaleLabel: HTMLElement | null = null;
  private scaleBarEl: HTMLElement | null = null;
  private sub: HTMLElement | null = null;
  private subSpan: HTMLElement | null = null;
  private layouts: ShotLayout[] | null = null;
  private subH = new Map<string, number>();
  private footerRect: Rect | null = null;
  private u: number;
  /** Time spent on annotations in the last update (ms; diagnostics only, never drawn). */
  annoMs = 0;

  constructor(parent: HTMLElement, b: Bundle, area: { top: number; height: number }) {
    const m = b.manifest;
    const fr = b.frames;
    this.b = b;
    this.m = m;
    this.fr = fr;
    this.area = area;
    this.u = m.height / 1080;
    const style = document.createElement("style");
    style.textContent = CSS;
    document.head.appendChild(style);
    this.root = el("div", "cin-root", parent);
    this.root.style.setProperty("--u", String(m.height / 1080));
    const hud = el("div", "cin-hud", this.root);
    this.hud = hud;
    hud.style.top = `${area.top}px`;
    hud.style.height = `${area.height}px`;
    const an = m.annotations;
    // map labels and callouts sit under the gradients and the HUD text
    if (an) this.anno = new Annotator(hud, b, { width: m.width, height: area.height }, (j) => this.reserved(j));
    el("div", "cin-grad-top", hud);
    el("div", "cin-grad-bot", hud);
    this.divider = el("div", "cin-divider", hud);
    this.splitL = el("div", "cin-split", hud);
    this.splitL.style.left = "0";
    this.splitR = el("div", "cin-split", hud);
    this.splitR.style.left = "50%";
    this.cap = el("div", "cin-cap", hud);
    el("div", "cin-film", this.cap, m.title);
    this.caption = el("div", "cin-caption", this.cap);
    this.detail = el("div", "cin-detail", this.cap);
    const clock = el("div", "cin-clock", hud);
    this.time = el("div", "cin-time", clock);
    el("div", "cin-tier", clock, TIER_TEXT[m.tier] ?? "");
    if (an?.compass) {
      const c = el("div", "cin-compass", clock);
      c.innerHTML = COMPASS_SVG;
      this.compass = c.querySelector("g");
    }
    this.kpis = el("div", "cin-kpis", hud);
    this.legend = el("div", "cin-legend", hud);
    if (an?.scale_bar) {
      this.scale = el("div", "cin-scale", hud);
      this.scaleLabel = el("div", "", this.scale);
      this.scaleBarEl = el("div", "cin-scale-bar", this.scale);
    }
    if (an?.subtitles && m.narration?.length) {
      this.sub = el("div", "cin-sub", hud);
      this.subSpan = el("span", "", this.sub);
      this.subSpan.dir = "auto"; // Arabic narration (pass 8): right-to-left base direction from the text
    }
    const footer = el("div", "cin-footer", hud);
    const fictional = m.fictional ? ` &middot; <b>fictional demo parameters</b>` : "";
    footer.innerHTML = `TrafficTwin Jeddah &middot; <b>${m.label}</b>${fictional} &middot; map data &copy; OpenStreetMap contributors (ODbL) &middot; simulated with Eclipse SUMO`;
    this.title = el("div", "cin-title", this.root);
    this.title.style.top = `${area.top}px`;
    this.title.style.height = `${area.height}px`;
    this.title.style.bottom = "auto";
    el("div", "cin-title-k", this.title, "TrafficTwin Jeddah");
    el("div", "cin-title-h", this.title, m.title);
    el("div", "cin-title-s", this.title, m.subtitle);
    el("div", "cin-title-f", this.title, m.label);
    if (m.letterbox) {
      const bar = (top: boolean) => {
        const b = el("div", "cin-bars", this.root);
        b.style.height = `${area.top}px`;
        if (top) b.style.top = "0";
        else b.style.bottom = "0";
      };
      bar(true);
      bar(false);
    }
    this.fade = el("div", "cin-fade", this.root);
  }

  private setShot(shot: ShotSpec): void {
    this.caption.textContent = shot.hud.caption;
    this.detail.textContent = shot.hud.detail;
    this.kpis.replaceChildren();
    this.kpiEls = shot.hud.kpis.map((k) => {
      const box = el("div", "cin-kpi", this.kpis);
      const v = el("div", "cin-kpi-v", box);
      el("div", "cin-kpi-l", box, k.label);
      return v;
    });
    const split = shot.layers.mode === "split" && shot.hud.split_labels;
    this.divider.style.display = shot.layers.mode === "split" ? "block" : "none";
    this.splitL.textContent = split ? shot.hud.split_labels![0] : "";
    this.splitR.textContent = split ? shot.hud.split_labels![1] : "";
    this.legend.replaceChildren();
    this.legendBody(shot);
    if (this.m.annotations) this.legendKeys(shot);
  }

  private legendBody(shot: ShotSpec): void {
    const kind = shot.hud.legend;
    if (kind === "none") return;
    if (kind === "class") {
      el("div", "cin-legend-t", this.legend, "Vehicles");
      const chips = el("div", "cin-chips", this.legend);
      const counts = shot.layers.trips ? this.m.files.trips[shot.layers.trips]?.classes : undefined;
      this.m.vehicle_classes.forEach((c, i) => {
        if (counts && !counts[c]) return;
        const chip = el("div", "cin-chip", chips);
        const dot = el("span", "cin-dot", chip);
        dot.style.background = `rgb(${CLASS_COLORS[i]!.join(",")})`;
        el("span", "", chip, c);
      });
      return;
    }
    const diff = kind === "diff";
    const tripsOnly = kind === "speed" && !shot.layers.heat && shot.layers.trips;
    el("div", "cin-legend-t", this.legend, diff ? "Change in speed vs comparison" : tripsOnly ? "Vehicle speed" : "Road speed / limit");
    const bar = el("div", "cin-bar", this.legend);
    bar.style.background = gradientCss(diff ? DIFF_STOPS : tripsOnly ? SPEED_STOPS : HEAT_STOPS);
    const ends = el("div", "cin-ends", this.legend);
    el("span", "", ends, diff ? "worse" : tripsOnly ? "stopped" : "congested");
    el("span", "", ends, diff ? "relief" : tripsOnly ? "fast" : "free flow");
  }

  /** Key chips for the zone / exits / contraflow / release-band overlays present in the shot. */
  private legendKeys(shot: ShotSpec): void {
    const want = new Set(shot.layers.overlays);
    const L = shot.layers;
    const sids = [L.heat, L.trips, L.route_source, ...(L.split ?? [])].filter((x): x is string => !!x);
    const sets = [...new Set(sids)].map((s) => this.b.overlays[s]).filter((o) => !!o);
    const has = (k: (typeof KEY_KINDS)[number]) =>
      want.has(k) && sets.some((o) => (k === "zone" ? !!o!.zone : (o![k]?.length ?? 0) > 0));
    const kinds = KEY_KINDS.filter(has);
    if (!kinds.length) return;
    const row = el("div", "cin-keys", this.legend);
    for (const k of kinds) {
      const chip = el("div", "cin-chip", row);
      if (k === "zone") {
        el("span", "cin-sw-zone", chip);
        el("span", "", chip, "Evacuation zone");
      } else if (k === "exits") {
        const d = el("span", "cin-dot", chip);
        d.style.background = "rgb(90,255,150)";
        el("span", "", chip, "Exits");
      } else if (k === "contraflow") {
        const d = el("span", "cin-sw-line", chip);
        d.style.background = "rgb(255,190,40)";
        el("span", "", chip, "Contraflow");
      } else {
        const bands = Math.min(
          BAND_COLORS.length,
          Math.max(1, ...sets.map((o) => (o!.phases.length ? Math.max(...o!.phases.map((p) => p.band)) + 1 : 0))),
        );
        const sw = el("span", "cin-sw-bands", chip);
        for (let i = 0; i < bands; i++) {
          const d = el("span", "cin-sw-band", sw);
          d.style.background = `rgb(${BAND_COLORS[i]!.join(",")})`;
        }
        el("span", "", chip, "Release bands");
      }
    }
  }

  // ------------------------------------------------------------------ layout for annotations

  private rel(e: Element): Rect | null {
    const r = e.getBoundingClientRect();
    if (r.width < 1 || r.height < 1) return null;
    const h = this.hud.getBoundingClientRect();
    return { x0: r.left - h.left, y0: r.top - h.top, x1: r.right - h.left, y1: r.bottom - h.top };
  }

  /** Measures the HUD's reserved rectangles for every shot once (the layout is deterministic). */
  private measure(): ShotLayout[] {
    if (this.layouts) return this.layouts;
    const u = this.u;
    const W = this.m.width;
    const H = this.area.height;
    const pad = 8 * u;
    const grow = (r: Rect | null): Rect | null => (r ? { x0: r.x0 - pad, y0: r.y0 - pad, x1: r.x1 + pad, y1: r.y1 + pad } : null);
    const footer = this.hud.querySelector(".cin-footer");
    this.footerRect = footer ? grow(this.rel(footer)) : null;
    // the clock is measured with its longest text (it is empty before the first update)
    const clockText = this.time.textContent;
    this.time.textContent = this.fr.clock.reduce((x, y) => (y.length > x.length ? y : x), "");
    const out: ShotLayout[] = this.m.shots.map((shot, s) => {
      this.setShot(shot);
      // widest KPI value of the shot, so the reserved row covers every frame
      shot.hud.kpis.forEach((k, j) => {
        let best = "-";
        for (let i = 0; i < this.fr.n; i++) {
          if (this.fr.shot[i] !== s) continue;
          const v = this.fr.kpi[i]?.[j];
          if (v === null || v === undefined) continue;
          const t = formatKpi(k, v);
          if (t.length > best.length) best = t;
        }
        const e = this.kpiEls[j]!;
        e.replaceChildren(document.createTextNode(best));
        if (k.unit) el("span", "cin-kpi-u", e, k.unit);
      });
      const rects: Rect[] = [];
      const add = (r: Rect | null) => {
        if (r) rects.push(r);
        return r;
      };
      add(grow(this.rel(this.cap)));
      add(grow(this.rel(this.hud.querySelector(".cin-clock")!)));
      const kpi = add(grow(this.rel(this.kpis)));
      const legend = add(grow(this.rel(this.legend)));
      if (shot.layers.mode === "split" && shot.hud.split_labels) {
        add(grow(this.rel(this.splitL)));
        add(grow(this.rel(this.splitR)));
      }
      if (this.footerRect) rects.push(this.footerRect);
      const legendH = legend ? legend.y1 - legend.y0 - 2 * pad : 0;
      const scaleBottom = 72 * u + (legendH > 0 ? legendH + 14 * u : 0);
      if (this.scale) rects.push({ x0: W - 56 * u - 200 * u - pad, y0: H - scaleBottom - 36 * u - pad, x1: W - 56 * u + pad, y1: H - scaleBottom + pad });
      return { rects, kpi, legend, scaleBottom };
    });
    this.time.textContent = clockText;
    this.shown = -1;
    this.layouts = out;
    return out;
  }

  /** Active subtitle at frame i and where it goes (between the KPI row and the legend, else above both). */
  private subLayout(i: number): SubLayout | null {
    const lines = this.m.narration;
    if (!this.sub || !lines) return null;
    const t = i / this.m.fps;
    const line = lines.findIndex((l) => t >= l.start_s && t < l.end_s);
    if (line < 0) return null;
    const l = lines[line]!;
    const alpha = Math.min(1, Math.max(0, Math.min(t - l.start_s, l.end_s - t) / 0.2));
    const u = this.u;
    const W = this.m.width;
    const H = this.area.height;
    const lay = this.measure()[this.fr.shot[i]!]!;
    const gap = 16 * u;
    const lo = lay.kpi ? lay.kpi.x1 + gap : 56 * u;
    const hi = lay.legend ? lay.legend.x0 - gap : W - 56 * u;
    const max = 0.7 * W;
    const footerTop = this.footerRect ? H - this.footerRect.y0 : 46 * u;
    if (hi - lo >= 0.4 * W) {
      const width = Math.min(max, hi - lo);
      const centre = Math.min(Math.max(W / 2, lo + width / 2), hi - width / 2);
      return { line, alpha, left: centre - width / 2, width, bottom: footerTop + 4 * u, font: hi - lo >= 0.55 * W ? 26 * u : 22 * u };
    }
    const above = Math.max(lay.kpi ? H - lay.kpi.y0 : 0, lay.legend ? H - lay.legend.y0 : 0, footerTop);
    return { line, alpha, left: (W - max) / 2, width: max, bottom: above + 6 * u, font: 26 * u };
  }

  private subHeight(s: SubLayout): number {
    const k = `${s.line}|${Math.round(s.width)}|${s.font}`;
    let h = this.subH.get(k);
    if (h === undefined) {
      const probe = el("div", "cin-sub", this.hud);
      probe.style.visibility = "hidden";
      probe.style.left = `${s.left}px`;
      probe.style.width = `${s.width}px`;
      probe.style.bottom = "0";
      const sp = el("span", "", probe, this.m.narration![s.line]!.text);
      sp.dir = "auto";
      sp.style.fontSize = `${s.font}px`;
      h = sp.getBoundingClientRect().height;
      probe.remove();
      this.subH.set(k, h);
    }
    return h;
  }

  /** HUD rectangles labels must avoid at frame j (stage px). */
  reserved(j: number): Rect[] {
    const lay = this.measure()[this.fr.shot[j]!]!;
    const s = this.subLayout(j);
    if (!s) return lay.rects;
    const H = this.area.height;
    const h = this.subHeight(s);
    const pad = 8 * this.u;
    return [...lay.rects, { x0: s.left - pad, y0: H - s.bottom - h - pad, x1: s.left + s.width + pad, y1: H - s.bottom + pad }];
  }

  update(i: number): void {
    const f = this.m.shots;
    const fr = this.fr;
    if (this.m.annotations) this.measure();
    const s = fr.shot[i]!;
    if (s !== this.shown) {
      this.setShot(f[s]!);
      this.shown = s;
    }
    const shot = f[s]!;
    this.cap.style.opacity = String(fr.caption_alpha[i]);
    this.time.textContent = fr.clock[i]!;
    const vals = fr.kpi[i] ?? [];
    shot.hud.kpis.forEach((k, j) => {
      const v = vals[j];
      const e = this.kpiEls[j]!;
      if (v === null || v === undefined) {
        e.textContent = "-";
        return;
      }
      e.replaceChildren(document.createTextNode(formatKpi(k, v)));
      if (k.unit) el("span", "cin-kpi-u", e, k.unit);
    });
    this.title.style.opacity = String(fr.title_alpha[i]);
    this.title.style.display = fr.title_alpha[i]! > 0 ? "flex" : "none";
    this.fade.style.opacity = String(fr.fade[i]);
    if (this.m.annotations) {
      const t0 = performance.now();
      this.annotate(i);
      this.annoMs = performance.now() - t0;
    }
  }

  private annotate(i: number): void {
    const cam = this.fr.camera[i]!;
    const u = this.u;
    if (this.compass) this.compass.setAttribute("transform", `rotate(${(-cam[4]!).toFixed(2)} 50 50)`);
    if (this.scale && this.scaleLabel && this.scaleBarEl) {
      const lay = this.measure()[this.fr.shot[i]!]!;
      const sb = scaleBar(cam[1]!, cam[2]!, 170 * u);
      this.scale.style.bottom = `${lay.scaleBottom}px`;
      this.scaleLabel.textContent = sb.m >= 1000 ? `${sb.m / 1000} km` : `${sb.m} m`;
      this.scaleBarEl.style.width = `${sb.px.toFixed(1)}px`;
    }
    if (this.sub && this.subSpan) {
      const s = this.subLayout(i);
      if (!s) this.sub.style.display = "none";
      else {
        this.sub.style.display = "block";
        this.sub.style.left = `${s.left.toFixed(1)}px`;
        this.sub.style.width = `${s.width.toFixed(1)}px`;
        this.sub.style.bottom = `${s.bottom.toFixed(1)}px`;
        this.sub.style.opacity = s.alpha.toFixed(3);
        this.subSpan.style.fontSize = `${s.font}px`;
        this.subSpan.textContent = this.m.narration![s.line]!.text;
      }
    }
    this.anno?.update(i);
  }
}
