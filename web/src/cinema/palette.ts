// Cinema colour ramps (display choices, not model assumptions).
export type RGB = [number, number, number];
type Stop = [number, RGB];

/** Edge speed / limit: congested red -> amber -> pale gold -> free-flow teal. */
export const HEAT_STOPS: Stop[] = [
  [0, [235, 35, 50]],
  [0.35, [255, 120, 30]],
  [0.65, [255, 214, 90]],
  [1, [40, 210, 170]],
];
/** Difference mode: red = worse, neutral, blue = relief. */
export const DIFF_STOPS: Stop[] = [
  [0, [215, 40, 50]],
  [0.5, [70, 76, 90]],
  [1, [40, 140, 255]],
];
/** Vehicle speed (m/s): brake-light red when stopped -> amber -> warm white -> cool white. */
export const SPEED_STOPS: Stop[] = [
  [0, [255, 45, 45]],
  [0.2, [255, 150, 40]],
  [0.5, [255, 236, 190]],
  [1, [150, 215, 255]],
];
export const SPEED_MAX_MS = 18;

/** Vehicle class colours, in manifest.vehicle_classes order. */
export const CLASS_COLORS: RGB[] = [
  [230, 236, 245], // car
  [255, 176, 60], // truck
  [90, 230, 140], // bus
  [255, 50, 60], // emergency (pulses red/blue)
  [200, 120, 255], // convoy
  [255, 220, 40], // evacuee
];
export const EMERGENCY_BLUE: RGB = [50, 120, 255];
export const BAND_COLORS: RGB[] = [
  [255, 220, 60],
  [255, 150, 40],
  [255, 90, 70],
  [220, 80, 160],
  [160, 90, 230],
];

export function lut(stops: Stop[]): Uint8Array {
  const out = new Uint8Array(256 * 3);
  for (let i = 0; i < 256; i++) {
    const t = i / 255;
    let k = 0;
    while (k < stops.length - 2 && t > stops[k + 1]![0]) k++;
    const [t0, c0] = stops[k]!;
    const [t1, c1] = stops[k + 1]!;
    const f = t1 === t0 ? 0 : Math.min(1, Math.max(0, (t - t0) / (t1 - t0)));
    for (let j = 0; j < 3; j++) out[i * 3 + j] = Math.round(c0[j]! + (c1[j]! - c0[j]!) * f);
  }
  return out;
}

export const HEAT_LUT = lut(HEAT_STOPS);
export const DIFF_LUT = lut(DIFF_STOPS);
export const SPEED_LUT = lut(SPEED_STOPS);

export function gradientCss(stops: Stop[]): string {
  return `linear-gradient(to right, ${stops.map(([t, c]) => `rgb(${c.join(",")}) ${Math.round(t * 100)}%`).join(", ")})`;
}

export function mix(a: RGB, b: RGB, f: number): RGB {
  return [Math.round(a[0] + (b[0] - a[0]) * f), Math.round(a[1] + (b[1] - a[1]) * f), Math.round(a[2] + (b[2] - a[2]) * f)];
}
