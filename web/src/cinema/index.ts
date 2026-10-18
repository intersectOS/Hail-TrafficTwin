// Cinema mode (`?cinema=<film>`): renders film frames from a bundle written by
// scripts/movies/bundle.py. The page exposes `window.__cinema` for the frame-stepping renderer
// (web/scripts/cinema.mjs): load(spec), renderFrame(i) (resolves after deck.gl has drawn and the
// HUD is updated) and frameCount(). The render clock is the frame index: no wall-clock time.
// `&play=1` plays the film in real time for previewing in a normal browser.
import { Deck, MapView, type Layer, type MapViewState } from "@deck.gl/core";

import { loadBundle, type Bundle } from "./data";
import { Hud } from "./hud";
import { Scene } from "./scene";
import type { Frames } from "./types";

export interface CinemaApi {
  load: (film: string) => Promise<number>;
  renderFrame: (i: number) => Promise<void>;
  frameCount: () => number;
  ready: () => boolean;
  frames: Frames | null;
  error: string | null;
  debug: () => Record<string, unknown>;
}

declare global {
  interface Window {
    __cinema?: CinemaApi;
  }
}

const DATA_ROOT = "/cinema-data";

function viewStates(cam: number[], split: boolean): Record<string, MapViewState> {
  const vs: MapViewState = { longitude: cam[0]!, latitude: cam[1]!, zoom: cam[2]!, pitch: cam[3]!, bearing: cam[4]! };
  return split ? { left: vs, right: vs } : { main: vs };
}

class Player {
  private b: Bundle;
  private deck: Deck<any>;
  private scene: Scene;
  private hud: Hud;
  private stage: HTMLDivElement;
  private drawn: (() => void) | null = null;
  private split = false;

  constructor(root: HTMLElement, b: Bundle) {
    this.b = b;
    const m = b.manifest;
    document.body.style.margin = "0";
    document.body.style.background = "#000";
    document.body.style.overflow = "hidden";
    root.style.position = "relative";
    root.style.width = `${m.width}px`;
    root.style.height = `${m.height}px`;
    root.style.overflow = "hidden";
    const barH = m.letterbox ? Math.round((m.height - m.width / m.letterbox) / 2) : 0;
    this.stage = document.createElement("div") as HTMLDivElement;
    this.stage.style.cssText = `position:absolute;left:0;top:${barH}px;width:${m.width}px;height:${m.height - 2 * barH}px;`;
    root.appendChild(this.stage);
    this.scene = new Scene(b);
    this.deck = new Deck<any>({
      parent: this.stage,
      width: m.width,
      height: m.height - 2 * barH,
      useDevicePixels: 1,
      controller: false,
      _animate: false,
      views: [new MapView({ id: "main", repeat: false })],
      viewState: viewStates(b.frames.camera[0]!, false) as never,
      layers: [],
      effects: [this.scene.effect],
      layerFilter: ({ layer, viewport }) => this.visible(layer.id, viewport.id),
      onAfterRender: () => {
        const cb = this.drawn;
        this.drawn = null;
        cb?.();
      },
    });
    this.hud = new Hud(root, b, { top: barH, height: m.height - 2 * barH });
  }

  private visible(id: string, view: string): boolean {
    if (view === "main" || !this.split) return true;
    if (id.includes("@left")) return view === "left";
    if (id.includes("@right")) return view === "right";
    return true;
  }

  debug(): Record<string, unknown> {
    const layers = (this.deck.props.layers ?? []) as Layer[];
    return {
      layers: layers.map((l) => [l.id, (l.props.data as { length?: number } | undefined)?.length ?? null]),
      annoMs: this.hud.annoMs,
    };
  }

  async render(i: number): Promise<void> {
    const fr = this.b.frames;
    const n = fr.n;
    const k = Math.min(Math.max(0, Math.floor(i)), n - 1);
    const shot = this.b.manifest.shots[fr.shot[k]!]!;
    const split = shot.layers.mode === "split";
    const lt = this.scene.light(k);
    this.stage.style.background = `rgb(${lt.land.join(",")})`;
    const layers: Layer[] = this.scene.layers(k, lt.night);
    const w = this.b.manifest.width;
    const views = split
      ? [new MapView({ id: "left", x: 0, width: w / 2, repeat: false }), new MapView({ id: "right", x: w / 2, width: w / 2, repeat: false })]
      : [new MapView({ id: "main", repeat: false })];
    this.split = split;
    this.hud.update(k);
    await new Promise<void>((resolve) => {
      const timer = window.setTimeout(() => {
        this.drawn = null;
        this.deck.redraw("cinema-timeout");
        resolve();
      }, 20000);
      this.drawn = () => {
        window.clearTimeout(timer);
        resolve();
      };
      this.deck.setProps({ views, viewState: viewStates(fr.camera[k]!, split) as never, layers, effects: [this.scene.effect] });
      this.deck.redraw("cinema-frame");
    });
    // let the compositor present the drawn frame and the HUD before a screenshot
    await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
  }
}

export function mountCinema(root: HTMLElement, film: string): void {
  let player: Player | null = null;
  let frames: Frames | null = null;
  let loaded: Promise<number> | null = null;
  let loadedName = "";
  const api: CinemaApi = {
    frames: null,
    error: null,
    debug: () => player?.debug() ?? {},
    ready: () => player !== null,
    frameCount: () => frames?.n ?? 0,
    load: (name: string) => {
      if (loaded && name === loadedName) return loaded;
      if (loaded) return Promise.reject(new Error(`cinema: ${loadedName} is already loaded`));
      loadedName = name;
      loaded = loadBundle(`${DATA_ROOT}/${encodeURIComponent(name)}`).then(async (b) => {
        frames = b.frames;
        api.frames = b.frames;
        player = new Player(root, b);
        await player.render(0);
        return b.frames.n;
      });
      return loaded;
    },
    renderFrame: async (i: number) => {
      if (!player) throw new Error("cinema: load() first");
      await player.render(i);
    },
  };
  window.__cinema = api;
  const params = new URLSearchParams(window.location.search);
  api.load(film).then(
    (n) => {
      if (params.get("play") === "1") {
        const t0 = performance.now();
        const fps = frames?.fps ?? 30;
        const tick = async () => {
          const i = Math.floor(((performance.now() - t0) / 1000) * fps) % n;
          await api.renderFrame(i);
          requestAnimationFrame(tick);
        };
        requestAnimationFrame(tick);
      }
    },
    (e: unknown) => {
      api.error = String(e);
      root.textContent = `cinema: ${String(e)}`;
      root.style.color = "#fff";
    },
  );
}
