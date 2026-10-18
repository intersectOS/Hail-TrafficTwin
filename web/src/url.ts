// Deep-link state in the URL query string (?run=&compare=&mode=diff&metric=&t=&play=1&panel=...).
import { SPEEDS } from "./config";

export type ViewMode = "scenario" | "baseline" | "diff";
export type Panel = "run" | "strategist" | "reports" | "jobs" | "none";

export interface UrlState {
  run: string | null;
  compare: string | null;
  mode: ViewMode;
  metric: string;
  t: number | null;
  play: boolean;
  speed: number;
  panel: Panel;
  basemap: boolean;
  colorBy: "speed" | "vtype";
  choropleth: boolean;
  buildings: boolean;
  districts: boolean;
  hideNoData: boolean;
  /** lon,lat,zoom[,pitch[,bearing]] */
  view: number[] | null;
}

/** "HH:MM", "HH:MM:SS" or plain seconds. */
export function parseTime(s: string | null): number | null {
  if (!s) return null;
  if (/^\d+(\.\d+)?$/.test(s)) return Number(s);
  const m = /^(\d{1,2}):(\d{2})(?::(\d{2}))?$/.exec(s);
  if (!m) return null;
  return Number(m[1]) * 3600 + Number(m[2]) * 60 + Number(m[3] ?? 0);
}

export function fmtTime(sec: number, withSeconds = false): string {
  const s = Math.max(0, Math.floor(sec));
  const h = Math.floor(s / 3600) % 100;
  const m = Math.floor((s % 3600) / 60);
  const ss = s % 60;
  const p = (n: number) => String(n).padStart(2, "0");
  return withSeconds ? `${p(h)}:${p(m)}:${p(ss)}` : `${p(h)}:${p(m)}`;
}

export function readUrl(): UrlState {
  const q = new URLSearchParams(window.location.search);
  const flag = (k: string, dflt: boolean) => (q.has(k) ? q.get(k) === "1" || q.get(k) === "true" : dflt);
  const mode = q.get("mode");
  const panel = q.get("panel");
  const speed = Number(q.get("speed"));
  const view = q.get("view")?.split(",").map(Number).filter((n) => Number.isFinite(n)) ?? null;
  return {
    run: q.get("run"),
    compare: q.get("compare"),
    mode: mode === "diff" || mode === "baseline" ? mode : "scenario",
    metric: q.get("metric") ?? "speed_rel",
    t: parseTime(q.get("t")),
    play: flag("play", false),
    speed: SPEEDS.includes(speed) ? speed : 60,
    panel: (["run", "strategist", "reports", "jobs", "none"] as const).find((p) => p === panel) ?? "run",
    basemap: flag("basemap", true),
    colorBy: q.get("color") === "vtype" ? "vtype" : "speed",
    choropleth: flag("choropleth", false),
    buildings: flag("buildings", true),
    districts: flag("districts", true),
    hideNoData: flag("hidenodata", false),
    view: view && view.length >= 3 ? view : null,
  };
}

/** Write the non-default parts of the state back to the URL (replaceState; never per frame). */
export function writeUrl(s: UrlState): void {
  const q = new URLSearchParams();
  if (s.run) q.set("run", s.run);
  if (s.compare) q.set("compare", s.compare);
  if (s.mode !== "scenario") q.set("mode", s.mode);
  if (s.metric !== "speed_rel") q.set("metric", s.metric);
  if (s.t !== null) q.set("t", fmtTime(s.t, s.t % 60 !== 0));
  if (s.play) q.set("play", "1");
  if (s.speed !== 60) q.set("speed", String(s.speed));
  if (s.panel !== "run") q.set("panel", s.panel);
  if (!s.basemap) q.set("basemap", "0");
  if (s.colorBy !== "speed") q.set("color", s.colorBy);
  if (s.choropleth) q.set("choropleth", "1");
  if (!s.buildings) q.set("buildings", "0");
  if (!s.districts) q.set("districts", "0");
  if (s.hideNoData) q.set("hidenodata", "1");
  if (s.view) q.set("view", s.view.map((v) => +v.toFixed(5)).join(","));
  const str = q.toString();
  window.history.replaceState(null, "", str ? `?${str}` : window.location.pathname);
}
