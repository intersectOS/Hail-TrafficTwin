import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import type { DecisionEntry, Recommendations } from "../types";

interface Props {
  runId: string;
  recs: Recommendations;
}

/** Ranked options with Approve / Reject. Approving only logs the decision (hash-chained); the
 * viewer never actuates anything. */
export function StrategistPanel({ runId, recs }: Props) {
  const [operator, setOperator] = useState(() => localStorage.getItem("tt.operator") ?? "");
  const [note, setNote] = useState("");
  const [log, setLog] = useState<DecisionEntry[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(() => {
    api.decisions(runId).then(setLog, (e: unknown) => setError(String(e)));
  }, [runId]);
  useEffect(refresh, [refresh]);

  const decide = async (optionId: string, decision: "approved" | "rejected") => {
    if (!operator.trim()) {
      setError("Enter an operator name first.");
      return;
    }
    setBusy(optionId + decision);
    setError(null);
    try {
      localStorage.setItem("tt.operator", operator.trim());
      await api.decide(runId, optionId, { decision, operator: operator.trim(), note });
      setNote("");
      refresh();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(null);
    }
  };

  const options = [...recs.options].sort((a, b) => a.rank - b.rank);
  const decidedBy = new Map(log.map((d) => [d.option_id, d]));

  return (
    <div className="strategist">
      <div className="muted">
        Incident {recs.incident_id ?? "n/a"}
        {recs.generated_at ? ` · generated ${recs.generated_at}` : ""}
      </div>
      <div className="row">
        <label>
          Operator <input value={operator} onChange={(e) => setOperator(e.target.value)} placeholder="duty-officer" />
        </label>
      </div>
      <div className="row">
        <label>
          Note <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="optional" />
        </label>
      </div>
      {error ? <div className="error">{error}</div> : null}
      <ol className="options">
        {options.map((o) => {
          const last = decidedBy.get(o.option_id);
          return (
            <li key={o.option_id} className={o.action_class === "high_impact" ? "high" : ""}>
              <div className="opt-head">
                <span className="rank">#{o.rank}</span>
                <span className="opt-title">{o.title}</span>
                <span className="score">{o.score.toFixed(2)}</span>
              </div>
              <div className="badges">
                <span className={`badge ${o.action_class}`}>{o.action_class.replace("_", " ")}</span>
                {o.requires_approval || o.action_class === "high_impact" ? <span className="badge">requires approval</span> : null}
                {last ? <span className={`badge ${last.decision}`}>{last.decision} by {last.operator}</span> : null}
              </div>
              <p className="explain">{o.explanation}</p>
              {o.effects ? (
                <div className="effects">
                  {Object.entries(o.effects).map(([k, v]) => (
                    <span key={k}>
                      {k}: <b>{typeof v === "number" ? `${v > 0 ? "+" : ""}${v.toFixed(1)}` : String(v)}</b>
                    </span>
                  ))}
                </div>
              ) : null}
              <div className="buttons">
                <button className="approve" disabled={busy !== null} onClick={() => void decide(o.option_id, "approved")}>
                  Approve
                </button>
                <button className="reject" disabled={busy !== null} onClick={() => void decide(o.option_id, "rejected")}>
                  Reject
                </button>
              </div>
            </li>
          );
        })}
      </ol>
      <h3>Decision log</h3>
      <div className="muted">Append-only, SHA-256 chained. Decision support only; nothing is actuated.</div>
      {log.length === 0 ? (
        <div className="muted">No decisions yet.</div>
      ) : (
        <table className="summary log">
          <thead>
            <tr>
              <th>time</th>
              <th>option</th>
              <th>decision</th>
              <th>operator</th>
              <th>hash</th>
            </tr>
          </thead>
          <tbody>
            {log
              .slice()
              .reverse()
              .map((d) => (
                <tr key={d.hash}>
                  <td>{d.ts.replace("T", " ").slice(0, 19)}</td>
                  <td>{d.option_id}</td>
                  <td className={d.decision === "approved" ? "pos" : "neg"}>{d.decision}</td>
                  <td>{d.operator}</td>
                  <td className="mono" title={`prev ${d.prev_hash}`}>
                    {d.hash.slice(0, 10)}
                  </td>
                </tr>
              ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
