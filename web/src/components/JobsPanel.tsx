import { useEffect, useRef, useState } from "react";
import { api } from "../api";

/** Start a Tier B smoke run and follow its progress over SSE. */
export function JobsPanel({ onDone }: { onDone: (runId: string | null) => void }) {
  const [tier, setTier] = useState<"A" | "B">("B");
  const [seed, setSeed] = useState(1);
  const [job, setJob] = useState<string | null>(null);
  const [status, setStatus] = useState<string>("");
  const [lines, setLines] = useState<string[]>([]);
  const es = useRef<EventSource | null>(null);

  useEffect(() => () => es.current?.close(), []);

  const start = async () => {
    setLines([]);
    setStatus("starting");
    try {
      const { job_id } = await api.startJob({ kind: "smoke", tier, seed });
      setJob(job_id);
      setStatus("running");
      const src = new EventSource(api.jobEventsUrl(job_id));
      es.current = src;
      src.addEventListener("log", (e) => setLines((l) => [...l.slice(-199), (e as MessageEvent<string>).data]));
      src.addEventListener("status", (e) => setStatus((e as MessageEvent<string>).data));
      src.addEventListener("done", (e) => {
        src.close();
        let runId: string | null = null;
        try {
          const d = JSON.parse((e as MessageEvent<string>).data) as { status: string; run_id?: string };
          setStatus(d.status);
          runId = d.run_id ?? null;
        } catch {
          setStatus("done");
        }
        onDone(runId);
      });
      src.onerror = () => {
        // EventSource retries on its own; give up once the job is finished.
        void api.job(job_id).then((j) => {
          if (j.status !== "running") {
            src.close();
            setStatus(j.status);
            onDone(j.run_id ?? null);
          }
        });
      };
    } catch (e) {
      setStatus(String(e));
    }
  };

  return (
    <div className="jobs">
      <div className="row">
        <label>
          Tier
          <select value={tier} onChange={(e) => setTier(e.target.value as "A" | "B")}>
            <option value="B">B (demo window, micro)</option>
            <option value="A">A (city, meso)</option>
          </select>
        </label>
        <label>
          Seed <input type="number" min={0} value={seed} onChange={(e) => setSeed(Number(e.target.value))} style={{ width: 60 }} />
        </label>
        <button onClick={() => void start()} disabled={status === "running" || status === "starting"}>
          Start smoke run
        </button>
      </div>
      {job ? (
        <div className="muted">
          job {job}: <b>{status}</b>
        </div>
      ) : status ? (
        <div className="error">{status}</div>
      ) : null}
      {lines.length ? <pre className="joblog">{lines.join("\n")}</pre> : null}
    </div>
  );
}
