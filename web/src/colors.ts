// Colour scales as 256-entry RGBA lookup tables, so per-bin recolouring of ~1M path vertices is
// a tight loop with no allocation.
import { NO_DATA_RGBA } from "./config";

type Stop = [number, [number, number, number]];

// ColorBrewer RdYlGn (low = red = slow, high = green = free flow).
const RDYLGN: Stop[] = [
  [0, [165, 0, 38]],
  [0.25, [244, 109, 67]],
  [0.5, [254, 224, 139]],
  [0.75, [102, 189, 99]],
  [1, [0, 104, 55]],
];
// ColorBrewer YlOrRd for "more is worse/busier" (delay, density, flow).
const YLORRD: Stop[] = [
  [0, [255, 255, 178]],
  [0.25, [254, 204, 92]],
  [0.5, [253, 141, 60]],
  [0.75, [240, 59, 32]],
  [1, [189, 0, 38]],
];
// Diverging RdBu: 0 = red (worse), 0.5 = neutral, 1 = blue (better).
const RDBU: Stop[] = [
  [0, [178, 24, 43]],
  [0.25, [239, 138, 98]],
  [0.5, [235, 235, 235]],
  [0.75, [103, 169, 207]],
  [1, [33, 102, 172]],
];

// Vehicles: magenta (stopped) -> violet -> cyan -> white (fast); distinct from the edge palettes.
const COOL: Stop[] = [
  [0, [255, 0, 170]],
  [0.35, [170, 70, 255]],
  [0.7, [0, 200, 255]],
  [1, [220, 255, 255]],
];

export type PaletteName = "rdylgn" | "ylorrd" | "rdbu" | "cool";
const STOPS: Record<PaletteName, Stop[]> = { rdylgn: RDYLGN, ylorrd: YLORRD, rdbu: RDBU, cool: COOL };

function buildLut(stops: Stop[]): Uint8Array {
  const lut = new Uint8Array(256 * 4);
  for (let i = 0; i < 256; i++) {
    const t = i / 255;
    let k = 0;
    while (k < stops.length - 2 && t > stops[k + 1]![0]) k++;
    const [t0, c0] = stops[k]!;
    const [t1, c1] = stops[k + 1]!;
    const f = t1 === t0 ? 0 : (t - t0) / (t1 - t0);
    for (let j = 0; j < 3; j++) lut[i * 4 + j] = Math.round(c0[j]! + (c1[j]! - c0[j]!) * f);
    lut[i * 4 + 3] = 255;
  }
  return lut;
}

const LUTS: Record<PaletteName, Uint8Array> = {
  rdylgn: buildLut(RDYLGN),
  ylorrd: buildLut(YLORRD),
  rdbu: buildLut(RDBU),
  cool: buildLut(COOL),
};

export interface Scale {
  palette: PaletteName;
  min: number;
  max: number;
  /** Diverging scales: flip so that "better" is always blue. */
  invert: boolean;
}

/** Index 0..255 into the LUT for value v, or -1 when v is NaN. */
export function lutIndex(scale: Scale, v: number): number {
  if (!(v === v)) return -1; // NaN
  let t = (v - scale.min) / (scale.max - scale.min || 1);
  if (scale.invert) t = 1 - t;
  t = t < 0 ? 0 : t > 1 ? 1 : t;
  return (t * 255 + 0.5) | 0;
}

export function colorOf(scale: Scale, v: number): [number, number, number, number] {
  const i = lutIndex(scale, v);
  if (i < 0) return [...NO_DATA_RGBA];
  const lut = LUTS[scale.palette];
  return [lut[i * 4]!, lut[i * 4 + 1]!, lut[i * 4 + 2]!, 255];
}

export function cssColor(scale: Scale, v: number): string {
  const [r, g, b] = colorOf(scale, v);
  return `rgb(${r},${g},${b})`;
}

/** CSS linear-gradient for a legend bar (left = min, right = max). */
export function gradientCss(scale: Scale): string {
  const parts: string[] = [];
  for (let i = 0; i <= 10; i++) {
    const v = scale.min + ((scale.max - scale.min) * i) / 10;
    parts.push(`${cssColor(scale, v)} ${i * 10}%`);
  }
  return `linear-gradient(to right, ${parts.join(", ")})`;
}

/**
 * Fill a per-vertex RGBA buffer from per-edge values. `values` may be null (no data at all).
 * `base` (optional) is subtracted for difference mode. Edges with NaN get the no-data colour, or
 * alpha 0 when `hideNoData` is set.
 */
export function fillEdgeColors(
  out: Uint8Array,
  startIndices: Uint32Array,
  nEdges: number,
  values: Float32Array | null,
  base: Float32Array | null,
  scale: Scale,
  hideNoData: boolean,
): void {
  const lut = LUTS[scale.palette];
  const nr = NO_DATA_RGBA[0],
    ng = NO_DATA_RGBA[1],
    nb = NO_DATA_RGBA[2],
    na = hideNoData ? 0 : NO_DATA_RGBA[3];
  const span = scale.max - scale.min || 1;
  const min = scale.min;
  const inv = scale.invert;
  for (let e = 0; e < nEdges; e++) {
    let v = values ? values[e]! : NaN;
    if (base) v -= base[e]!;
    let r = nr,
      g = ng,
      b = nb,
      a = na;
    if (v === v) {
      let t = (v - min) / span;
      if (inv) t = 1 - t;
      t = t < 0 ? 0 : t > 1 ? 1 : t;
      const i = ((t * 255 + 0.5) | 0) * 4;
      r = lut[i]!;
      g = lut[i + 1]!;
      b = lut[i + 2]!;
      a = 255;
    }
    const p1 = startIndices[e + 1]!;
    for (let p = startIndices[e]!; p < p1; p++) {
      const o = p * 4;
      out[o] = r;
      out[o + 1] = g;
      out[o + 2] = b;
      out[o + 3] = a;
    }
  }
}

export function paletteStops(name: PaletteName): Stop[] {
  return STOPS[name];
}
