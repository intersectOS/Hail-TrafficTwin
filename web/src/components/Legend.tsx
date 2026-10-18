import { gradientCss, type Scale } from "../colors";

interface Props {
  title: string;
  unit: string;
  scale: Scale;
  note?: string;
  digits?: number;
}

export function Legend({ title, unit, scale, note, digits = 1 }: Props) {
  const mid = (scale.min + scale.max) / 2;
  const f = (v: number) => (Math.abs(v) >= 100 ? v.toFixed(0) : v.toFixed(digits));
  return (
    <div className="legend">
      <div className="legend-title">
        {title}
        {unit ? ` (${unit})` : ""}
      </div>
      <div className="legend-bar" style={{ background: gradientCss(scale) }} />
      <div className="legend-labels">
        <span>{f(scale.min)}</span>
        <span>{f(mid)}</span>
        <span>{f(scale.max)}</span>
      </div>
      {note ? <div className="legend-note">{note}</div> : null}
    </div>
  );
}
