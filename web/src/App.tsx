import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { FeatureCollection } from "geojson";

import { api } from "./api";
import { METRICS, metricDef } from "./config";
import { Engine, VEHICLE_SCALE, type EngineStatus, type RunInput } from "./engine";
import type {
  BinsInfo,
  DistrictEffects,
  EdgeGeometry,
  EdgeInfo,
  PolicyReport,
  Recommendations,
  RunSummary,
  ScenarioReport,
  TripsResponse,
} from "./types";
import { SYNTHETIC_LABEL } from "./types";
import { readUrl, writeUrl, type Panel, type UrlState, type ViewMode } from "./url";
import { Timeline } from "./components/Timeline";
import { Hud } from "./components/Hud";
import { Legend } from "./components/Legend";
import { StrategistPanel } from "./components/StrategistPanel";
import { ReportsPanel } from "./components/ReportsPanel";
import { JobsPanel } from "./components/JobsPanel";

interface NetworkEntry {
  geom: Promise<EdgeGeometry>;
  info: Promise<EdgeInfo | null>;
}
const networks = new Map<string, NetworkEntry>();
function loadNetwork(hash: string): NetworkEntry {
  let n = networks.get(hash);
  if (!n) {
    n = {
      geom: api.edgesBin(hash),
      info: api.edgesJson(hash).catch((e: unknown) => {
        console.warn("edges.json failed", e);
        return null;
      }),
    };
    networks.set(hash, n);
  }
  return n;
}

const INITIAL: UrlState = readUrl();

/** Global hook for the screenshot/perf scripts. */
declare global {
  interface Window {
    __tt?: { engine: Engine; ready: () => boolean; loading: () => number; debug: () => Record<string, unknown> };
  }
}

export function App() {
  const mapEl = useRef<HTMLDivElement>(null);
  const tipEl = useRef<HTMLDivElement>(null);
  const [engine, setEngine] = useState<Engine | null>(null);
  const loading = useRef(0);
  const track = useCallback(<T,>(p: Promise<T>): Promise<T> => {
    loading.current++;
    return p.finally(() => loading.current--);
  }, []);

  const [runs, setRuns] = useState<RunSummary[] | null>(null);
  const [runsError, setRunsError] = useState<string | null>(null);
  const [runId, setRunId] = useState<string | null>(INITIAL.run);
  const [compareId, setCompareId] = useState<string | null>(INITIAL.compare);
  const [mode, setMode] = useState<ViewMode>(INITIAL.mode);
  const [metric, setMetric] = useState(INITIAL.metric);
  const [playing, setPlaying] = useState(INITIAL.play);
  const [speed, setSpeed] = useState(INITIAL.speed);
  const [panel, setPanel] = useState<Panel>(INITIAL.panel);
  const [basemap, setBasemap] = useState(INITIAL.basemap);
  const [colorBy, setColorBy] = useState(INITIAL.colorBy);
  const [choropleth, setChoropleth] = useState(INITIAL.choropleth);
  const [showBuildings, setShowBuildings] = useState(INITIAL.buildings);
  const [showDistricts, setShowDistricts] = useState(INITIAL.districts);
  const [hideNoData, setHideNoData] = useState(INITIAL.hideNoData);

  const [bins, setBins] = useState<BinsInfo | null>(null);
  const [cmpBins, setCmpBins] = useState<BinsInfo | null>(null);
  const [trips, setTrips] = useState<TripsResponse | null>(null);
  const [policy, setPolicy] = useState<PolicyReport | null>(null);
  const [scenario, setScenario] = useState<ScenarioReport | null>(null);
  const [recs, setRecs] = useState<Recommendations | null>(null);
  const [districts, setDistricts] = useState<FeatureCollection | null>(null);
  const [buildings, setBuildings] = useState<FeatureCollection | null>(null);
  const [effects, setEffects] = useState<DistrictEffects | null>(null);
  const [status, setStatus] = useState<EngineStatus | null>(null);
  const [scaleVer, setScaleVer] = useState(0);
  const [span, setSpan] = useState<[number, number]>([0, 86400]);
  const [errors, setErrors] = useState<string[]>([]);
  const firstFit = useRef(true);
  const syncUrlRef = useRef<() => void>(() => undefined);
  const viewRef = useRef<number[] | null>(INITIAL.view);

  const pushError = useCallback((e: unknown) => setErrors((x) => [...x.slice(-3), String(e)]), []);

  // ---------------------------------------------------------------- engine lifecycle
  useEffect(() => {
    if (!mapEl.current || !tipEl.current) return;
    const eng = new Engine(mapEl.current, tipEl.current);
    eng.onStatus = (s) => setStatus(s);
    eng.onScaleChange = () => setScaleVer((v) => v + 1);
    setEngine(eng);
    window.__tt = {
      engine: eng,
      ready: () => loading.current === 0 && eng.isReady(),
      loading: () => loading.current,
      debug: () => ({ loading: loading.current, ...eng.readiness() }),
    };
    const onMove = () => {
      if (firstFit.current) return;
      const c = eng.map.getCenter();
      viewRef.current = [c.lng, c.lat, eng.map.getZoom(), eng.map.getPitch(), eng.map.getBearing()];
      syncUrlRef.current();
    };
    eng.map.on("moveend", onMove);
    return () => eng.destroy();
  }, []);

  const refreshRuns = useCallback(
    (select?: string | null) => {
      track(api.runs()).then(
        (r) => {
          setRuns(r);
          setRunsError(null);
          if (select) setRunId(select);
          else setRunId((cur) => (cur && r.some((x) => x.run_id === cur) ? cur : (r.find((x) => x.tier === "A")?.run_id ?? r[0]?.run_id ?? null)));
        },
        (e: unknown) => setRunsError(String(e)),
      );
    },
    [track],
  );

  useEffect(() => {
    refreshRuns();
    track(api.districts()).then(setDistricts, pushError);
  }, [refreshRuns, track, pushError]);

  const run = useMemo(() => runs?.find((r) => r.run_id === runId) ?? null, [runs, runId]);
  const candidates = useMemo(
    () => (run && runs ? runs.filter((r) => r.network_hash === run.network_hash && r.run_id !== run.run_id) : []),
    [runs, run],
  );
  const compare = useMemo(() => candidates.find((r) => r.run_id === compareId) ?? null, [candidates, compareId]);

  // Default comparison: meta.baseline_run_id when it is on the same network.
  useEffect(() => {
    if (!run || !runs) return;
    if (compareId && candidates.some((c) => c.run_id === compareId)) return;
    const dflt = run.baseline_run_id && candidates.some((c) => c.run_id === run.baseline_run_id) ? run.baseline_run_id : null;
    setCompareId(dflt);
  }, [run, runs, candidates, compareId]);

  // ---------------------------------------------------------------- per-run data
  useEffect(() => {
    if (!run || !engine) return;
    let alive = true;
    setBins(null);
    setTrips(null);
    setPolicy(null);
    setScenario(null);
    setRecs(null);
    setBuildings(null);
    const id = run.run_id;
    const net = loadNetwork(run.network_hash);
    track(net.geom).then(
      (geom) => {
        if (!alive) return;
        engine.setNetwork(run.network_hash, geom, null);
        const view = firstFit.current ? INITIAL.view : null;
        engine.fitTo(geom.bbox, run.tier === "B", view);
        firstFit.current = false;
        const pad = 0.003;
        const bb: [number, number, number, number] = [geom.bbox[0] - pad, geom.bbox[1] - pad, geom.bbox[2] + pad, geom.bbox[3] + pad];
        track(api.buildings(bb)).then((fc) => alive && setBuildings(fc), pushError);
        track(net.info).then((info) => alive && info && engine.setNetwork(run.network_hash, geom, info));
      },
      (e: unknown) => {
        pushError(e);
        engine.setNetwork(run.network_hash, null, null);
      },
    );
    track(api.bins(id)).then((b) => alive && setBins(b), pushError);
    if (run.tier === "B") {
      const begin = 0;
      track(api.trajectories(id, begin, begin + run.sim_seconds, 1)).then((t) => alive && setTrips(t), pushError);
    }
    track(api.policyReport(id)).then((p) => alive && setPolicy(p), () => undefined);
    track(api.scenarioReport(id)).then((s) => alive && setScenario(s), () => undefined);
    track(api.recommendations(id)).then((r) => alive && setRecs(r), () => undefined);
    return () => {
      alive = false;
    };
  }, [run, engine, track, pushError]);

  useEffect(() => {
    setCmpBins(null);
    if (!compare) return;
    let alive = true;
    track(api.bins(compare.run_id)).then((b) => alive && setCmpBins(b), pushError);
    return () => {
      alive = false;
    };
  }, [compare, track, pushError]);

  useEffect(() => {
    if (!choropleth || !run) {
      setEffects(null);
      return;
    }
    let alive = true;
    track(api.districtEffects(run.run_id, compare?.run_id ?? null)).then((e) => alive && setEffects(e), pushError);
    return () => {
      alive = false;
    };
  }, [choropleth, run, compare, track, pushError]);

  // ---------------------------------------------------------------- push into the engine
  const initialSeekDone = useRef(false);
  useEffect(() => {
    if (!engine) return;
    const r: RunInput | null = run ? { runId: run.run_id, tier: run.tier, bins } : null;
    const c: RunInput | null = compare ? { runId: compare.run_id, tier: compare.tier, bins: cmpBins } : null;
    engine.setRuns(r, c, mode);
    const sp = engine.getSpan();
    setSpan(sp);
    if (run && (bins || run.tier === "A")) {
      if (!initialSeekDone.current) {
        initialSeekDone.current = true;
        engine.seek(INITIAL.t ?? sp[0]);
        if (INITIAL.play) engine.setPlaying(true);
      } else if (engine.t < sp[0] || engine.t >= sp[1]) {
        engine.seek(sp[0]);
      }
    }
  }, [engine, run, compare, bins, cmpBins, mode]);

  useEffect(() => engine?.setMetric(metric, hideNoData), [engine, metric, hideNoData]);
  useEffect(() => {
    if (!engine) return;
    engine.setTrips(trips, colorBy);
    setSpan(engine.getSpan());
  }, [engine, trips, colorBy]);
  useEffect(() => engine?.setBuildings(buildings, showBuildings), [engine, buildings, showBuildings]);
  useEffect(() => engine?.setDistricts(districts, showDistricts), [engine, districts, showDistricts]);
  useEffect(() => engine?.setChoropleth(effects, choropleth), [engine, effects, choropleth]);
  useEffect(() => engine?.setScenario(scenario), [engine, scenario]);
  useEffect(() => engine?.setBasemapVisible(basemap), [engine, basemap]);
  useEffect(() => {
    if (engine && engine.playing !== playing) engine.setPlaying(playing);
  }, [engine, playing]);
  useEffect(() => engine?.setSpeed(speed), [engine, speed]);

  // ---------------------------------------------------------------- URL sync (never per frame)
  const stateRef = useRef<UrlState>(INITIAL);
  stateRef.current = {
    run: runId,
    compare: compareId,
    mode,
    metric,
    t: engine ? Math.round(engine.t) : INITIAL.t,
    play: playing,
    speed,
    panel,
    basemap,
    colorBy,
    choropleth,
    buildings: showBuildings,
    districts: showDistricts,
    hideNoData,
    view: viewRef.current,
  };
  const syncUrl = useCallback(() => {
    const s = { ...stateRef.current, t: engine ? Math.round(engine.t) : stateRef.current.t, view: viewRef.current };
    writeUrl(s);
  }, [engine]);
  syncUrlRef.current = syncUrl;
  useEffect(() => {
    if (runs) syncUrl();
  });

  // ---------------------------------------------------------------- render
  const def = metricDef(metric);
  const scale = engine?.scale;
  const hudExtra = useCallback(() => {
    if (!engine) return "";
    const c = engine.cacheStats();
    return `bins ${c.entries} (${c.mb.toFixed(1)} MB)`;
  }, [engine]);
  void scaleVer;

  const modeLabel = mode === "diff" && compare ? `difference: ${run?.run_id ?? ""} minus ${compare.run_id}` : mode === "baseline" && compare ? `showing ${compare.run_id}` : `showing ${run?.run_id ?? ""}`;

  return (
    <div className="app">
      <div className="map" ref={mapEl} />
      <div className="tooltip" ref={tipEl} />
      <div className="banner">
        <b>TrafficTwin Jeddah</b>
        <span className="label-synthetic">{SYNTHETIC_LABEL}</span>
        {run ? (
          <span className="banner-run">
            {run.run_id} · Tier {run.tier} · {run.kind} · seed {run.seed}
          </span>
        ) : null}
      </div>

      <aside className="panel">
        <nav className="tabs">
          <button className={panel === "run" ? "on" : ""} onClick={() => setPanel("run")}>
            Run
          </button>
          {policy || scenario ? (
            <button className={panel === "reports" ? "on" : ""} onClick={() => setPanel("reports")}>
              Reports
            </button>
          ) : null}
          {recs ? (
            <button className={panel === "strategist" ? "on" : ""} onClick={() => setPanel("strategist")}>
              Strategist
            </button>
          ) : null}
          <button className={panel === "jobs" ? "on" : ""} onClick={() => setPanel("jobs")}>
            Start run
          </button>
          <button className={panel === "none" ? "on" : ""} onClick={() => setPanel("none")} title="collapse">
            ×
          </button>
        </nav>

        {panel === "run" ? (
          <div className="section">
            {runsError ? <div className="error">API not reachable: {runsError}</div> : null}
            <label className="block">
              Run
              <select value={runId ?? ""} onChange={(e) => setRunId(e.target.value)}>
                {(runs ?? []).map((r) => (
                  <option key={r.run_id} value={r.run_id}>
                    {r.run_id} · {r.tier} · {r.kind} · seed {r.seed}
                  </option>
                ))}
              </select>
            </label>
            {run ? (
              <div className="muted">
                Tier {run.tier} ({run.mode}) · {run.kind} · seed {run.seed} · {(run.sim_seconds / 3600).toFixed(1)} h simulated ·
                net {run.network_hash}
              </div>
            ) : null}
            <label className="block">
              Compare with
              <select value={compareId ?? ""} onChange={(e) => setCompareId(e.target.value || null)}>
                <option value="">(none)</option>
                {candidates.map((r) => (
                  <option key={r.run_id} value={r.run_id}>
                    {r.run_id} · {r.kind} · seed {r.seed}
                  </option>
                ))}
              </select>
            </label>
            {compare ? (
              <div className="seg">
                {(["scenario", "baseline", "diff"] as const).map((m) => (
                  <button key={m} className={mode === m ? "on" : ""} onClick={() => setMode(m)}>
                    {m === "scenario" ? "show scenario" : m === "baseline" ? "show baseline" : "difference"}
                  </button>
                ))}
              </div>
            ) : candidates.length === 0 ? (
              <div className="muted">No other run on this network to compare with.</div>
            ) : null}
            <label className="block">
              Edge metric
              <select value={metric} onChange={(e) => setMetric(e.target.value)}>
                {METRICS.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.label}
                    {m.unit ? ` (${m.unit})` : ""}
                  </option>
                ))}
              </select>
            </label>
            {run?.tier === "B" ? (
              <label className="block">
                Vehicles coloured by
                <select value={colorBy} onChange={(e) => setColorBy(e.target.value as "speed" | "vtype")}>
                  <option value="speed">speed</option>
                  <option value="vtype">vehicle type</option>
                </select>
              </label>
            ) : null}
            <div className="toggles">
              <label>
                <input type="checkbox" checked={basemap} onChange={(e) => setBasemap(e.target.checked)} /> basemap
              </label>
              <label>
                <input type="checkbox" checked={showBuildings} onChange={(e) => setShowBuildings(e.target.checked)} /> buildings
              </label>
              <label>
                <input type="checkbox" checked={showDistricts} onChange={(e) => setShowDistricts(e.target.checked)} /> districts
              </label>
              <label>
                <input type="checkbox" checked={choropleth} onChange={(e) => setChoropleth(e.target.checked)} /> district effects
              </label>
              <label>
                <input type="checkbox" checked={hideNoData} onChange={(e) => setHideNoData(e.target.checked)} /> hide no-data edges
              </label>
            </div>
            <div className="muted status">
              basemap {status?.basemap ?? "…"} · edges {status?.edges ?? "…"} · bin {status?.bin ?? "…"}
              {run?.tier === "B" ? ` · trips ${status?.trips ?? "…"} (${trips?.vehicles.length ?? 0} veh)` : ""}
              {bins ? ` · ${bins.n_bins} bins of ${bins.bin_s / 60} min · ${bins.n_edges.toLocaleString()} edges` : ""}
            </div>
            {choropleth && effects ? (
              <div className="muted">
                District effects ({effects.source}): {effects.metric}, {effects.districts.filter((d) => d.value !== null).length} districts
              </div>
            ) : choropleth ? (
              <div className="muted">District effects not available for this run.</div>
            ) : null}
            {errors.length ? <div className="error">{errors.join("\n")}</div> : null}
          </div>
        ) : null}
        {panel === "reports" ? (
          <div className="section">
            <ReportsPanel policy={policy} scenario={scenario} />
          </div>
        ) : null}
        {panel === "strategist" ? (
          <div className="section">
            {recs && run ? <StrategistPanel runId={run.run_id} recs={recs} /> : <div className="muted">No recommendations for this run.</div>}
          </div>
        ) : null}
        {panel === "jobs" ? (
          <div className="section">
            <JobsPanel onDone={(id) => refreshRuns(id)} />
          </div>
        ) : null}
      </aside>

      <div className="legends">
        {scale ? (
          <Legend
            title={`${def.label}${mode === "diff" ? " difference" : ""}`}
            unit={def.unit}
            scale={scale}
            digits={def.id === "speed_rel" ? 2 : 1}
            note={`${modeLabel} · grey = no data`}
          />
        ) : null}
        {choropleth && effects ? <Legend
            title={`District ${effects.metric}`}
            unit={effects.unit}
            scale={engine!.choroScale}
            note={`${effects.source === "policy_report" ? "from policy report" : "computed from edge bins"}${compare ? ` vs ${compare.run_id}` : ""}${engine!.choroClipped ? " · scale clipped at p90 |value|" : ""}`}
          /> : null}
        {run?.tier === "B" && trips ? (
          colorBy === "speed" ? (
            <Legend title="Vehicle speed (trails)" unit="m/s" scale={VEHICLE_SCALE} />
          ) : (
            <div className="legend">
              <div className="legend-title">Vehicle type</div>
              {engine?.vtypes.map((v) => {
                const c = engine.vtypeColor(v);
                return (
                  <div key={v} className="vtype">
                    <span className="swatch" style={{ background: `rgb(${c[0]},${c[1]},${c[2]})` }} /> {v}
                  </div>
                );
              })}
            </div>
          )
        ) : null}
      </div>

      <Timeline
        engine={engine}
        playing={playing}
        speed={speed}
        span={span}
        onPlaying={(p) => {
          setPlaying(p);
          if (!p) setTimeout(syncUrl, 0);
        }}
        onSpeed={setSpeed}
        onSeekEnd={() => syncUrl()}
      />
      <Hud extra={hudExtra} />
      <div className="attr">Network, districts and buildings © OpenStreetMap contributors (ODbL). Basemap OpenFreeMap / OpenMapTiles.</div>
    </div>
  );
}
