// What-if engine (Web Worker). Loads the Hail road graph and one hour of baseline routes
// (scripts/hail/whatif_data.py), applies an event to some streets for a duration, reroutes the
// vehicles whose routes use those streets (method of successive averages over the affected vehicles,
// everyone else keeps their route) and recomputes link times with a volume-delay function plus a
// point-queue term for over-capacity links. Returns per-edge flow/time changes and city totals.
// This is a fast estimate built on the simulation's routes, not a new simulation run.
"use strict";

// ---------------------------------------------------------------- parameters (documented on the page)
const CAP = [2000, 1900, 1700, 1500, 1300, 900, 700, 600, 500, 700]; // veh/h/lane by class (HCM-style planning values)
const SIGNAL_CAP = 0.5;      // share of the hour an approach gets green at a signal
const SIGNAL_DELAY_S = 12;   // mean stop delay at a signal at low volume
const BPR_A = 0.15, BPR_B = 4;
const ITER = 5;              // successive-averages iterations
const RAIN = { speed: 0.85, cap: 0.85 }; // heavy rain (same factors as sim/events/weather.yaml order)
const WORKS = { speed: 0.6 };            // roadworks: one lane less, 60 % of the limit

let G = null, R = null, hour = -1;

function parseGraph(buf, meta) {
  const dv = new DataView(buf);
  const n = dv.getUint32(4, true), m = dv.getUint32(8, true);
  let p = 12;
  const from = new Uint32Array(n), len = new Float32Array(n), spd = new Float32Array(n);
  const lanes = new Uint8Array(n), cls = new Uint8Array(n), tls = new Uint8Array(n), name = new Uint16Array(n);
  for (let i = 0; i < n; i++, p += 20) {
    from[i] = dv.getUint32(p, true); len[i] = dv.getFloat32(p + 4, true); spd[i] = dv.getFloat32(p + 8, true);
    lanes[i] = dv.getUint8(p + 12); cls[i] = dv.getUint8(p + 13); tls[i] = dv.getUint8(p + 14); name[i] = dv.getUint16(p + 16, true);
  }
  const succOff = new Uint32Array(buf.slice(p, p + 4 * (n + 1))); p += 4 * (n + 1);
  const succ = new Uint32Array(buf.slice(p, p + 4 * m)); p += 4 * m;
  const geoOff = new Uint32Array(buf.slice(p, p + 4 * (n + 1))); p += 4 * (n + 1);
  const geo = new Uint16Array(buf.slice(p, p + 4 * geoOff[n]));
  return { n, from, len, spd, lanes, cls, tls, name, succOff, succ, geoOff, geo, weight: meta.weight };
}

function parseRoutes(buf) {
  const dv = new DataView(buf);
  const w = dv.getUint8(4), n = dv.getUint32(8, true);
  let p = 12;
  const dep = new Uint16Array(n), off = new Uint32Array(n + 1);
  const tmp = [];
  let total = 0;
  for (let i = 0; i < n; i++) {
    dep[i] = dv.getUint16(p, true); const k = dv.getUint16(p + 2, true); p += 4;
    tmp.push([p, k]); off[i] = total; total += k; p += w * k;
  }
  off[n] = total;
  const edges = new Uint32Array(total);
  for (let i = 0; i < n; i++) {
    const [q, k] = tmp[i];
    for (let j = 0; j < k; j++) edges[off[i] + j] = w === 2 ? dv.getUint16(q + 2 * j, true) : dv.getUint32(q + 4 * j, true);
  }
  return { n, dep, off, edges };
}

// ---------------------------------------------------------------- link model
function capacity(e, mod) {
  let c = CAP[G.cls[e]] * Math.max(G.lanes[e], 1);
  if (G.tls[e]) c *= SIGNAL_CAP;
  if (mod) c *= mod.cap;
  return c;
}
function freeTime(e, mod) { return G.len[e] / Math.max(G.spd[e] * (mod ? mod.speed : 1), 0.5); }
function cost(e, v, mods, durS) {
  const md = mods.get(e);
  if (md && md.blocked) return Infinity;
  const c = capacity(e, md), t0 = freeTime(e, md);
  const x = v / c;
  let t = t0 * (1 + BPR_A * Math.pow(Math.min(x, 1.2), BPR_B));
  if (G.tls[e]) t += SIGNAL_DELAY_S * (1 + Math.min(x, 1) * Math.min(x, 1));
  if (x > 1 && durS > 0) t += ((v - c) / c) * (durS / 2); // point queue grows for the event's duration
  return t;
}

// ---------------------------------------------------------------- shortest path (edge graph)
let dist = null, prev = null, heap = null;
function sp(src, dst, costs) {
  const n = G.n;
  if (!dist) { dist = new Float64Array(n); prev = new Int32Array(n); heap = { k: new Float64Array(n * 4), v: new Int32Array(n * 4), s: 0 }; }
  dist.fill(Infinity); prev.fill(-1);
  heap.s = 0;
  const push = (k, v) => { let i = heap.s++; heap.k[i] = k; heap.v[i] = v; while (i > 0) { const pa = (i - 1) >> 1; if (heap.k[pa] <= heap.k[i]) break; [heap.k[pa], heap.k[i]] = [heap.k[i], heap.k[pa]]; [heap.v[pa], heap.v[i]] = [heap.v[i], heap.v[pa]]; i = pa; } };
  const pop = () => { const v = heap.v[0], k = heap.k[0]; heap.s--; heap.k[0] = heap.k[heap.s]; heap.v[0] = heap.v[heap.s]; let i = 0; for (;;) { const l = 2 * i + 1, r = l + 1; let mn = i; if (l < heap.s && heap.k[l] < heap.k[mn]) mn = l; if (r < heap.s && heap.k[r] < heap.k[mn]) mn = r; if (mn === i) break; [heap.k[mn], heap.k[i]] = [heap.k[i], heap.k[mn]]; [heap.v[mn], heap.v[i]] = [heap.v[i], heap.v[mn]]; i = mn; } return [k, v]; };
  dist[src] = 0; push(0, src);
  let settled = 0;
  while (heap.s) {
    const [d, u] = pop();
    if (d > dist[u]) continue;
    if (u === dst) break;
    if (++settled > 400000 || heap.s > heap.k.length - 64) break;
    for (let j = G.succOff[u]; j < G.succOff[u + 1]; j++) {
      const w = G.succ[j], c = costs[w];
      if (c === Infinity) continue;
      const nd = d + c;
      if (nd < dist[w]) { dist[w] = nd; prev[w] = u; push(nd, w); }
    }
  }
  if (dist[dst] === Infinity) return null;
  const path = [];
  for (let u = dst; u !== -1; u = prev[u]) { path.push(u); if (u === src) break; }
  return path.reverse();
}

// ---------------------------------------------------------------- the experiment
function run(ev) {
  const t0 = performance.now();
  const n = G.n, W = G.weight;
  const durS = ev.duration * 60;
  const mods = new Map();
  for (const e of ev.edges || []) {
    if (ev.type === "closure" || ev.type === "motorcade") mods.set(e, { blocked: true });
    else if (ev.type === "lane") mods.set(e, G.lanes[e] <= 1 ? { blocked: true } : { cap: (G.lanes[e] - 1) / G.lanes[e], speed: 0.7 });
    else if (ev.type === "works") mods.set(e, { cap: G.lanes[e] <= 1 ? 0.5 : (G.lanes[e] - 1) / G.lanes[e], speed: WORKS.speed });
  }
  const rain = ev.type === "rain";
  if (rain) for (let e = 0; e < n; e++) mods.set(e, { cap: RAIN.cap, speed: RAIN.speed });

  // base flows (veh/h at city scale) from every vehicle departing in the hour
  const v0 = new Float64Array(n);
  for (let i = 0; i < R.n; i++) for (let j = R.off[i]; j < R.off[i + 1]; j++) v0[R.edges[j]] += W;
  // vehicles inside the event window and those of them whose routes touch a modified street
  const win = []; const aff = []; const stuckSet = new Set();
  for (let i = 0; i < R.n; i++) {
    if (R.dep[i] >= Math.min(durS, 3600)) continue;
    win.push(i);
    if (rain) continue;
    for (let j = R.off[i]; j < R.off[i + 1]; j++) if (mods.has(R.edges[j])) { aff.push(i); break; }
  }
  // group affected vehicles by (entry edge, destination). The entry is the last edge before the
  // first modified street from which the destination can still be reached (stepping back along the
  // route up to 8 edges when the street just before is itself a dead end into the closure).
  const none = new Map();
  const c0 = new Float64Array(n), cb = new Float64Array(n);
  for (let e = 0; e < n; e++) { c0[e] = cost(e, v0[e], none, 0); const md = mods.get(e); cb[e] = md && md.blocked ? Infinity : c0[e]; }
  const reach = new Map();
  const reachable = (src, dst) => {
    const k = src + ":" + dst;
    if (!reach.has(k)) { const p = src === dst ? [src] : sp(src, dst, cb); reach.set(k, p ? p.reduce((s, e, j) => s + (j ? c0[e] : 0), 0) : -1); }
    return reach.get(k) >= 0;
  };
  const groups = new Map();
  let stuckVeh = 0;
  for (const i of aff) {
    let a = R.off[i];
    while (a < R.off[i + 1] && !mods.has(R.edges[a])) a++;
    const dst = R.edges[R.off[i + 1] - 1];
    let entry = -1;
    if (!(mods.get(dst) || {}).blocked) {
      for (let back = 1; back <= 8 && a - back >= R.off[i]; back++) if (reachable(R.edges[a - back], dst)) { entry = a - back; break; }
      if (entry < 0 && a === R.off[i] && !(mods.get(R.edges[a]) || {}).blocked) entry = a; // starts on a narrowed street
    }
    if (entry < 0) { stuckVeh++; stuckSet.add(i); continue; }
    const src = R.edges[entry];
    const key = src + ":" + dst;
    let g = groups.get(key);
    if (!g) { g = { src, dst, veh: [], entry: [], paths: [], ref: 0 }; groups.set(key, g); }
    g.veh.push(i); g.entry.push(entry);
  }
  // reference: the best path between the same two points with no event (same link model), so
  // the delay compares like with like rather than with the simulation's own route choice
  for (const g of groups.values()) {
    const p = g.src === g.dst ? [g.src] : sp(g.src, g.dst, c0);
    g.ref = p ? p.reduce((s, e, j) => s + (j ? c0[e] : 0), 0) : 0;
  }
  // remove the affected vehicles' original suffixes from the flows
  const vfix = Float64Array.from(v0);
  for (const g of groups.values()) g.veh.forEach((i, k) => { for (let j = g.entry[k] + 1; j < R.off[i + 1]; j++) vfix[R.edges[j]] -= W; });

  // successive averages: affected flows on their current best paths
  let vaff = new Float64Array(n);
  const costs = new Float64Array(n);
  const flowsFor = (vtot) => { for (let e = 0; e < n; e++) costs[e] = cost(e, vtot[e], mods, durS); };
  const total = new Float64Array(n);
  let stuck = 0;
  for (let k = 0; k < ITER; k++) {
    for (let e = 0; e < n; e++) total[e] = vfix[e] + vaff[e];
    flowsFor(total);
    const aon = new Float64Array(n);
    stuck = 0;
    for (const g of groups.values()) {
      const p = g.src === g.dst ? [g.src] : sp(g.src, g.dst, costs);
      const q = g.veh.length * W;
      if (!p) { stuck += q; continue; }
      for (let j = 1; j < p.length; j++) aon[p[j]] += q;
      g.paths.push(p);
    }
    const a = 1 / (k + 1);
    for (let e = 0; e < n; e++) vaff[e] = vaff[e] + a * (aon[e] - vaff[e]);
  }
  const v1 = new Float64Array(n);
  for (let e = 0; e < n; e++) v1[e] = vfix[e] + vaff[e];
  flowsFor(v1);
  const c1 = Float64Array.from(costs);

  // travel times of every vehicle departing in the window: base route vs. now
  let base = 0, now = 0, affBase = 0, affNow = 0;
  const affSet = new Set(aff);
  const groupOf = new Map();
  const entryOf = new Map();
  for (const g of groups.values()) g.veh.forEach((i, k) => { groupOf.set(i, g); entryOf.set(i, g.entry[k]); });
  for (const i of win) {
    let tb = 0, tn = 0;
    const g = groupOf.get(i);
    if (!g) {
      for (let j = R.off[i]; j < R.off[i + 1]; j++) { tb += c0[R.edges[j]]; tn += c1[R.edges[j]]; }
      if (stuckSet.has(i)) tn = tb + durS / 2; // cannot get past: waits on average half the event
    } else {
      const en = entryOf.get(i);
      for (let j = R.off[i]; j <= en; j++) { tb += c0[R.edges[j]]; tn += c1[R.edges[j]]; }
      let sum = 0, cnt = 0;
      for (const p of g.paths) { let s = 0; for (let k = 1; k < p.length; k++) s += c1[p[k]]; if (isFinite(s)) { sum += s; cnt++; } }
      tb += g.ref; tn += cnt ? sum / cnt : g.ref + durS / 2;
    }
    if (!isFinite(tn)) tn = tb + durS / 2;
    base += tb * W; now += tn * W;
    if (affSet.has(i)) { affBase += tb * W; affNow += tn * W; }
  }
  // queues on over-capacity links at the end of the event
  const queues = [];
  for (let e = 0; e < n; e++) {
    const md = mods.get(e); if (md && md.blocked) continue;
    const c = capacity(e, md), x = v1[e] / c;
    if (x > 1) queues.push([e, ((v1[e] - c) * Math.min(durS, 3600)) / 3600]);
  }
  queues.sort((a, b) => b[1] - a[1]);
  // roads that took the detours (by street name), and per-edge change for the map
  const byName = new Map();
  const delta = new Float32Array(n), ratio = new Float32Array(n);
  for (let e = 0; e < n; e++) {
    delta[e] = v1[e] - v0[e];
    ratio[e] = c0[e] > 0 && isFinite(c1[e]) ? c1[e] / c0[e] : 0;
    if (delta[e] > 0 && G.name[e]) byName.set(G.name[e], Math.max(byName.get(G.name[e]) || 0, delta[e]));
  }
  const affN = aff.length * W, winN = win.length * W;
  return {
    ms: Math.round(performance.now() - t0),
    hour, type: ev.type, duration: ev.duration,
    vehiclesInWindow: winN, affected: affN, stuck: stuck + stuckVeh * W,
    extraVehHours: (now - base) / 3600,
    extraPerAffectedMin: affN ? (affNow - affBase) / affN / 60 : (winN ? (now - base) / winN / 60 : 0),
    extraPerVehicleMin: winN ? (now - base) / winN / 60 : 0,
    topRoads: [...byName.entries()].sort((a, b) => b[1] - a[1]).slice(0, 6),
    queues: queues.slice(0, 5).map(([e, q]) => ({ e, veh: q, m: (q * 7) / Math.max(G.lanes[e], 1), name: G.name[e] })),
    delta, ratio,
    detours: [...groups.values()].sort((a, b) => b.veh.length - a.veh.length).slice(0, 60)
      .map((g) => ({ path: g.paths.length ? Array.from(g.paths[g.paths.length - 1]) : [], n: g.veh.length * W })),
  };
}

self.onmessage = async (msg) => {
  const d = msg.data;
  try {
    if (d.cmd === "init") {
      const meta = await (await fetch(d.base + "graph.json")).json();
      G = parseGraph(await (await fetch(d.base + "graph.bin")).arrayBuffer(), meta);
      self.postMessage({ cmd: "ready", meta });
    } else if (d.cmd === "run") {
      if (d.hour !== hour) {
        const buf = await (await fetch(`${d.base}h${String(d.hour).padStart(2, "0")}.bin`)).arrayBuffer();
        R = parseRoutes(buf); hour = d.hour;
      }
      const res = run(d.event);
      self.postMessage({ cmd: "result", res }, [res.delta.buffer, res.ratio.buffer]);
    }
  } catch (e) {
    self.postMessage({ cmd: "error", message: String(e && e.message || e) });
  }
};
