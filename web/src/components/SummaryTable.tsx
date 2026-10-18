import type { SummaryRow } from "../types";

const num = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? (Math.abs(v) >= 1000 ? v.toLocaleString(undefined, { maximumFractionDigits: 0 }) : v.toFixed(2)) : "");

/** Renders {metric: {baseline, policy|scenario, delta_pct, unit}} as a table. */
export function SummaryTable({ rows, otherKey }: { rows: Record<string, SummaryRow>; otherKey: "policy" | "scenario" }) {
  const entries = Object.entries(rows);
  if (!entries.length) return null;
  return (
    <table className="summary">
      <thead>
        <tr>
          <th>metric</th>
          <th>baseline</th>
          <th>{otherKey}</th>
          <th>Δ %</th>
        </tr>
      </thead>
      <tbody>
        {entries.map(([k, r]) => {
          const d = r.delta_pct;
          return (
            <tr key={k}>
              <td>
                {k}
                {r.unit ? <span className="unit"> {r.unit}</span> : null}
              </td>
              <td>{num(r.baseline)}</td>
              <td>{num(r[otherKey])}</td>
              <td className={typeof d === "number" ? (d > 0 ? "pos" : d < 0 ? "neg" : "") : ""}>
                {typeof d === "number" ? `${d > 0 ? "+" : ""}${d.toFixed(1)}` : ""}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
