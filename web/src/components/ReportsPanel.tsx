import type { PolicyReport, ScenarioReport } from "../types";
import { fmtTime } from "../url";
import { SummaryTable } from "./SummaryTable";

export function ReportsPanel({ policy, scenario }: { policy: PolicyReport | null; scenario: ScenarioReport | null }) {
  return (
    <div>
      {policy ? (
        <section>
          <h3>Policy report</h3>
          <div className="muted">
            {policy.policy?.name ?? policy.policy?.id ?? "policy"} vs {policy.baseline_run_id ?? "baseline"}
          </div>
          {policy.summary ? <SummaryTable rows={policy.summary} otherKey="policy" /> : null}
          {policy.assumptions?.length ? <div className="muted">Assumptions: {policy.assumptions.join(", ")}</div> : null}
        </section>
      ) : null}
      {scenario ? (
        <section>
          <h3>Scenario summary</h3>
          <div className="muted">
            {scenario.scenario?.name ?? scenario.scenario?.id ?? "scenario"}
            {scenario.scenario?.fictional ? " (fictional)" : ""} vs {scenario.baseline_run_id ?? "baseline"}
          </div>
          {scenario.summary ? <SummaryTable rows={scenario.summary} otherKey="scenario" /> : null}
          <table className="summary">
            <thead>
              <tr>
                <th>event</th>
                <th>type</th>
                <th>window</th>
                <th>edges</th>
              </tr>
            </thead>
            <tbody>
              {(scenario.events ?? []).map((e) => (
                <tr key={e.id}>
                  <td title={e.description}>{e.id}</td>
                  <td>{e.type}</td>
                  <td>
                    {fmtTime(e.begin_s)}-{fmtTime(e.end_s)}
                  </td>
                  <td>{e.edges?.length ?? 0}</td>
                </tr>
              ))}
              {(scenario.closures ?? []).map((c) => (
                <tr key={c.id}>
                  <td title={c.reason}>{c.id}</td>
                  <td>closure</td>
                  <td>
                    {fmtTime(c.begin_s)}-{fmtTime(c.end_s)}
                  </td>
                  <td>{c.edges.length}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      ) : null}
      {!policy && !scenario ? <div className="muted">No policy or scenario report for this run.</div> : null}
    </div>
  );
}
