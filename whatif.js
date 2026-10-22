// «لو صار الآن»: tap a street on Hail's live traffic map, describe an event, and see where the
// traffic goes (whatif-worker.js does the computation on the simulation's routes for that hour).
(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const KEY = (window.HAIL_LIVE && window.HAIL_LIVE.tomtomKey) || "";
  const BASE = "data/whatif/";
  const ar = (v, d = 0) => Number(v).toLocaleString("ar-SA", { maximumFractionDigits: d });
  const hailHour = () => (new Date().getUTCHours() + 3) % 24;
  const hourLabel = (h) => (h === 0 ? "12 ليلاً" : h < 5 ? `${h} ليلاً` : h < 12 ? `${h} صباحاً` : h === 12 ? "12 ظهراً" : h < 16 ? `${h - 12} ظهراً` : h < 19 ? `${h - 12} عصراً` : `${h - 12} مساءً`);
  const TYPES = { closure: "حادث يغلق الطريق", lane: "حادث يغلق مساراً", motorcade: "إغلاق لموكب", works: "حفريات", rain: "مطر غزير" };
  const DUR = { 15: "ربع ساعة", 30: "نص ساعة", 60: "ساعة", 120: "ساعتين" };

  // ------------------------------------------------------------ map
  const map = new maplibregl.Map({
    container: "map", style: "https://tiles.openfreemap.org/styles/dark", center: [41.698, 27.52], zoom: 12.4,
    attributionControl: { compact: true, customAttribution: "Traffic © TomTom · © OpenStreetMap" },
  });
  const flowUrl = () => `https://api.tomtom.com/traffic/map/4/tile/flow/relative0-dark/{z}/{x}/{y}.png?key=${KEY}&tileSize=256`;
  function addLive() {
    if (!KEY) { $("live-dot").classList.add("off"); $("live-dot").textContent = "بدون بث"; return; }
    if (map.getLayer("live")) { map.removeLayer("live"); map.removeSource("live"); }
    map.addSource("live", { type: "raster", tiles: [flowUrl()], tileSize: 256 });
    map.addLayer({ id: "live", type: "raster", source: "live", paint: { "raster-opacity": 0.85 } }, map.getLayer("chg") ? "chg" : undefined);
    const d = new Date();
    $("wi-clock").textContent = `زحمة حائل الآن من TomTom · ${d.toLocaleTimeString("ar-SA", { hour: "numeric", minute: "2-digit" })}`;
  }
  const empty = { type: "FeatureCollection", features: [] };
  map.on("load", () => {
    addLive();
    setInterval(addLive, 120000);
    for (const id of ["sel", "chg", "cut", "q", "dots"]) map.addSource(id, { type: "geojson", data: empty });
    map.addLayer({ id: "chg", type: "line", source: "chg", layout: { "line-cap": "round", "line-join": "round" },
      paint: { "line-color": ["get", "c"], "line-width": ["get", "w"], "line-opacity": 0.95 } });
    map.addLayer({ id: "sel-halo", type: "line", source: "sel", paint: { "line-color": "#ffffff", "line-width": 11, "line-opacity": 0.55 } });
    map.addLayer({ id: "sel", type: "line", source: "sel", layout: { "line-cap": "round" }, paint: { "line-color": "#f2c14e", "line-width": 6 } });
    map.addLayer({ id: "cut", type: "line", source: "cut", paint: { "line-color": "#111", "line-width": 7 } });
    map.addLayer({ id: "cut-dash", type: "line", source: "cut", paint: { "line-color": "#fff", "line-width": 2.5, "line-dasharray": [1.2, 1.2] } });
    map.addLayer({ id: "q", type: "circle", source: "q", paint: { "circle-color": "#f2c14e", "circle-opacity": 0.85,
      "circle-radius": ["interpolate", ["linear"], ["get", "m"], 0, 6, 300, 13, 1500, 22], "circle-stroke-color": "#111", "circle-stroke-width": 1.5 } });
    map.addLayer({ id: "dots", type: "circle", source: "dots", paint: { "circle-color": "#ffb347", "circle-radius": 3.2, "circle-stroke-color": "#3a1d00", "circle-stroke-width": 0.8 } });
  });

  // ------------------------------------------------------------ graph (geometry, names, lookup)
  let G = null, meta = null;
  const worker = new Worker("whatif-worker.js");
  async function loadGraph() {
    meta = await (await fetch(BASE + "graph.json")).json();
    const buf = await (await fetch(BASE + "graph.bin")).arrayBuffer();
    const dv = new DataView(buf);
    const n = dv.getUint32(4, true), m = dv.getUint32(8, true);
    let p = 12;
    const lanes = new Uint8Array(n), cls = new Uint8Array(n), name = new Uint16Array(n), len = new Float32Array(n);
    for (let i = 0; i < n; i++, p += 20) { len[i] = dv.getFloat32(p + 4, true); lanes[i] = dv.getUint8(p + 12); cls[i] = dv.getUint8(p + 13); name[i] = dv.getUint16(p + 16, true); }
    const succOff = new Uint32Array(buf.slice(p, p + 4 * (n + 1))); p += 4 * (n + 1);
    const succ = new Uint32Array(buf.slice(p, p + 4 * m)); p += 4 * m;
    const geoOff = new Uint32Array(buf.slice(p, p + 4 * (n + 1))); p += 4 * (n + 1);
    const geo = new Uint16Array(buf.slice(p, p + 4 * geoOff[n]));
    const [w, , , nn] = meta.bbox, span = meta.span;
    const lonlat = new Float64Array(geo.length);
    for (let i = 0; i < geo.length; i += 2) { lonlat[i] = w + (geo[i] / 65535) * span; lonlat[i + 1] = nn - (geo[i + 1] / 65535) * span; }
    const pred = Array.from({ length: n }, () => []);
    for (let e = 0; e < n; e++) for (let j = succOff[e]; j < succOff[e + 1]; j++) pred[succ[j]].push(e);
    // grid of edge midpoints for tap lookup
    const cell = 0.004, grid = new Map(), mid = new Float64Array(2 * n), head = new Float32Array(n);
    for (let e = 0; e < n; e++) {
      const a = geoOff[e], b = geoOff[e + 1] - 1;
      const k = (a + b) >> 1;
      mid[2 * e] = lonlat[2 * k]; mid[2 * e + 1] = lonlat[2 * k + 1];
      head[e] = Math.atan2(lonlat[2 * b + 1] - lonlat[2 * a + 1], lonlat[2 * b] - lonlat[2 * a]);
      for (let q = a; q <= b; q++) {
        const key = Math.floor(lonlat[2 * q] / cell) + ":" + Math.floor(lonlat[2 * q + 1] / cell);
        let arr = grid.get(key); if (!arr) grid.set(key, (arr = [])); if (arr[arr.length - 1] !== e) arr.push(e);
      }
    }
    G = { n, lanes, cls, name, len, succOff, succ, geoOff, lonlat, pred, grid, cell, mid, head };
    if (location.search.includes("probe")) window.__wiProbe = (e) => { map.jumpTo({ center: [G.mid[2 * e], G.mid[2 * e + 1]], zoom: 15 }); const q = map.project([G.mid[2 * e], G.mid[2 * e + 1]]); return [q.x, q.y]; };
  }
  const coords = (e) => { const out = []; for (let q = G.geoOff[e]; q < G.geoOff[e + 1]; q++) out.push([G.lonlat[2 * q], G.lonlat[2 * q + 1]]); return out; };
  const nameOf = (e) => meta.names[G.name[e]] || "شارع بدون اسم";
  const line = (e, props = {}) => ({ type: "Feature", properties: props, geometry: { type: "LineString", coordinates: coords(e) } });

  function nearestEdge(lngLat, point) {
    const cx = Math.floor(lngLat.lng / G.cell), cy = Math.floor(lngLat.lat / G.cell);
    let best = -1, bd = 22;
    for (let dx = -1; dx <= 1; dx++) for (let dy = -1; dy <= 1; dy++) {
      for (const e of G.grid.get(cx + dx + ":" + (cy + dy)) || []) {
        if (G.cls[e] >= 8) continue; // service roads are not offered
        const c = coords(e);
        for (let k = 0; k + 1 < c.length; k++) {
          const a = map.project(c[k]), b = map.project(c[k + 1]);
          const vx = b.x - a.x, vy = b.y - a.y, t = Math.max(0, Math.min(1, ((point.x - a.x) * vx + (point.y - a.y) * vy) / (vx * vx + vy * vy || 1)));
          const d = Math.hypot(point.x - a.x - t * vx, point.y - a.y - t * vy) - (G.cls[e] <= 4 ? 4 : 0);
          if (d < bd) { bd = d; best = e; }
        }
      }
    }
    return best;
  }
  // the tapped edge plus the same street ahead and behind, about 250 m each way
  function chain(e0) {
    const out = [e0], nm = G.name[e0];
    const grow = (e, next, room) => {
      while (room > 0) {
        const cand = next(e).filter((x) => G.name[x] === nm && nm !== 0 && !out.includes(x) && Math.abs(Math.atan2(Math.sin(G.head[x] - G.head[e]), Math.cos(G.head[x] - G.head[e]))) < 0.8);
        if (!cand.length) break;
        e = cand[0]; out.push(e); room -= G.len[e];
      }
    };
    const succs = (e) => Array.from(G.succ.subarray(G.succOff[e], G.succOff[e + 1]));
    grow(e0, succs, 250); grow(e0, (e) => G.pred[e], 250);
    return out;
  }
  // the other carriageway / direction: same name, nearby, heading the other way
  function opposite(edges) {
    const set = new Set(edges), out = [];
    for (const e of edges) {
      const cx = Math.floor(G.mid[2 * e] / G.cell), cy = Math.floor(G.mid[2 * e + 1] / G.cell);
      for (let dx = -1; dx <= 1; dx++) for (let dy = -1; dy <= 1; dy++) for (const x of G.grid.get(cx + dx + ":" + (cy + dy)) || []) {
        if (set.has(x) || G.name[x] !== G.name[e]) continue;
        const dd = Math.hypot((G.mid[2 * x] - G.mid[2 * e]) * 98000, (G.mid[2 * x + 1] - G.mid[2 * e + 1]) * 111000);
        const dh = Math.abs(Math.atan2(Math.sin(G.head[x] - G.head[e]), Math.cos(G.head[x] - G.head[e])));
        if (dd < 70 && dh > 2.2) { set.add(x); out.push(x); }
      }
    }
    return out;
  }

  // ------------------------------------------------------------ state and steps
  const state = { edges: [], type: "closure", dir: "one", hour: hailHour(), dur: 30, lngLat: null };
  const show = (id) => { for (const s of ["s-pick", "s-event", "s-result"]) $(s).hidden = s !== id; $("sheet").classList.remove("min"); $("sheet").scrollTop = 0; };
  // tap the handle to fold the sheet down and see more of the map
  document.querySelector(".grab").addEventListener("click", () => $("sheet").classList.toggle("min"));
  function chips(groupId, key, cast = (x) => x) {
    $(groupId).querySelectorAll(".chip").forEach((b) => b.addEventListener("click", () => {
      $(groupId).querySelectorAll(".chip").forEach((x) => x.setAttribute("aria-checked", String(x === b)));
      state[key] = cast(b.dataset.v); paintSelection();
    }));
  }
  // hour chips: now first, then the usual peaks
  const hours = [...new Set([hailHour(), 7, 13, 17, 21])];
  $("ev-hour").innerHTML = hours.map((h, i) => `<button type="button" class="chip" data-v="${h}" role="radio" aria-checked="${i === 0}">${i === 0 ? `الآن (${hourLabel(h)})` : hourLabel(h)}</button>`).join("");
  chips("ev-type", "type"); chips("ev-dir", "dir"); chips("ev-hour", "hour", Number); chips("ev-dur", "dur", Number);

  function selectedEdges() { return state.dir === "both" ? [...state.edges, ...opposite(state.edges)] : state.edges; }
  function paintSelection() {
    if (!map.getSource("sel")) return;
    map.getSource("sel").setData({ type: "FeatureCollection", features: selectedEdges().map((e) => line(e)) });
  }
  function clearResult() { for (const id of ["chg", "cut", "q", "dots"]) map.getSource(id) && map.getSource(id).setData(empty); detours = []; }

  map.on("click", (ev) => {
    if (!G) return;
    if (!$("s-result").hidden) return; // finish or edit the current result first
    const e = nearestEdge(ev.lngLat, ev.point);
    if (e < 0) return;
    state.edges = chain(e); state.lngLat = ev.lngLat;
    const lenM = state.edges.reduce((s, x) => s + G.len[x], 0);
    $("st-name").textContent = nameOf(e);
    $("st-meta").textContent = `مقطع طوله ${ar(lenM)} متر، ${ar(G.lanes[e])} ${G.lanes[e] === 1 ? "مسار" : "مسارات"} في هذا الاتجاه`;
    paintSelection(); clearResult(); show("s-event"); liveSpeed(ev.lngLat);
  });
  $("st-clear").addEventListener("click", () => { state.edges = []; paintSelection(); show("s-pick"); });
  document.querySelector('[data-city="rain"]').addEventListener("click", () => { state.edges = []; runEvent("rain"); });

  async function liveSpeed(ll) {
    $("st-now").hidden = true;
    if (!KEY) return;
    try {
      const u = `https://api.tomtom.com/traffic/services/4/flowSegmentData/relative0/10/json?key=${KEY}&point=${ll.lat.toFixed(5)},${ll.lng.toFixed(5)}&unit=KMPH`;
      const d = (await (await fetch(u)).json()).flowSegmentData;
      if (!d) return;
      const r = d.currentSpeed / d.freeFlowSpeed;
      $("st-now").textContent = `الآن على هذا الشارع: ${ar(d.currentSpeed)} كم/س، والمعتاد وهو فاضي ${ar(d.freeFlowSpeed)} كم/س (${r > 0.9 ? "سالك" : r > 0.7 ? "تباطؤ خفيف" : "زحمة"}).`;
      $("st-now").hidden = false;
    } catch { /* live speed is a bonus; the experiment works without it */ }
  }

  // ------------------------------------------------------------ run
  $("go").addEventListener("click", () => runEvent(state.type));
  $("r-edit").addEventListener("click", () => { clearResult(); show(state.edges.length ? "s-event" : "s-pick"); });
  $("r-new").addEventListener("click", () => { clearResult(); state.edges = []; paintSelection(); show("s-pick"); });
  let busy = false, lastType = "closure";
  function runEvent(type) {
    if (busy || !G) return;
    busy = true; lastType = type;
    $("go").disabled = true; $("go").textContent = "يحسب…";
    const edges = type === "rain" ? [] : selectedEdges();
    worker.postMessage({ cmd: "run", base: BASE, hour: state.hour, event: { type, edges, duration: state.dur } });
  }
  worker.onmessage = (m) => {
    const d = m.data;
    if (d.cmd === "ready") { $("engine-status").textContent = "جاهز. كبّر الخريطة واضغط على الشارع."; return; }
    if (d.cmd === "error") { busy = false; $("go").disabled = false; $("go").textContent = "شغّل المحاكاة"; $("engine-status").textContent = "تعذّر الحساب: " + d.message; return; }
    if (d.cmd === "result") { busy = false; $("go").disabled = false; $("go").textContent = "شغّل المحاكاة"; render(d.res); }
  };
  worker.postMessage({ cmd: "init", base: BASE });

  // ------------------------------------------------------------ results
  let detours = [], animT = 0;
  function render(r) {
    const W = meta.weight;
    const feats = [];
    const thr = Math.max(25, 3 * W);
    for (let e = 0; e < G.n; e++) {
      const dv = r.delta[e];
      if (Math.abs(dv) < thr || G.cls[e] >= 8) continue;
      const up = dv > 0, mag = Math.min(1, Math.abs(dv) / 600);
      feats.push(line(e, { c: up ? (mag > 0.5 ? "#ff3b2f" : "#ff7a45") : "#3d8fd6", w: 2.5 + 5 * mag }));
    }
    if (r.type === "rain") {
      for (let e = 0; e < G.n; e++) if (r.ratio[e] > 1.15 && G.cls[e] <= 6) feats.push(line(e, { c: r.ratio[e] > 1.5 ? "#ff3b2f" : "#ff9a3c", w: 3 }));
    }
    map.getSource("chg").setData({ type: "FeatureCollection", features: feats });
    const cut = r.type === "closure" || r.type === "motorcade" || r.type === "lane" || r.type === "works" ? selectedEdges() : [];
    map.getSource("cut").setData({ type: "FeatureCollection", features: (r.type === "closure" || r.type === "motorcade") ? cut.map((e) => line(e)) : [] });
    map.getSource("sel").setData({ type: "FeatureCollection", features: (r.type === "lane" || r.type === "works") ? cut.map((e) => line(e)) : [] });
    map.getSource("q").setData({ type: "FeatureCollection", features: r.queues.filter((q) => q.m > 40).map((q) => {
      const c = coords(q.e); return { type: "Feature", properties: { m: q.m }, geometry: { type: "Point", coordinates: c[c.length - 1] } };
    }) });
    detours = r.detours.filter((x) => x.path.length > 1).map((x) => {
      const pts = []; for (const e of x.path) for (const c of coords(e)) pts.push(c);
      let L = 0; const cum = [0]; for (let k = 1; k < pts.length; k++) { L += Math.hypot(pts[k][0] - pts[k - 1][0], pts[k][1] - pts[k - 1][1]); cum.push(L); }
      return { pts, cum, L, k: Math.max(1, Math.min(6, Math.round(x.n / (4 * W)))) };
    });

    // text
    const street = state.edges.length ? nameOf(state.edges[0]) : "حائل";
    $("r-title").textContent = r.type === "rain" ? "مطر غزير على حائل" : `${TYPES[r.type]}: ${street}`;
    $("r-sub").textContent = `${hourLabel(r.hour)} لمدة ${DUR[r.duration] || r.duration + " دقيقة"}`;
    const q0 = r.queues[0];
    $("k-aff").textContent = ar(Math.round(r.affected || r.vehiclesInWindow));
    $("k-min").textContent = ar(Math.max(0, r.extraPerAffectedMin), 1);
    $("k-vh").textContent = ar(Math.max(0, r.extraVehHours), r.extraVehHours < 10 ? 1 : 0);
    $("k-q").textContent = q0 && q0.m > 20 ? `${ar(Math.round(q0.m / 10) * 10)} م` : "لا يوجد";
    let head;
    if (r.type === "rain") head = `المطر يبطّئ المدينة كلها: كل سيارة تتأخر في المتوسط ${ar(Math.max(0, r.extraPerVehicleMin), 1)} دقيقة، والأشد على الطرق المزدحمة أصلاً في هذه الساعة.`;
    else if (!r.affected) head = "ما فيه سيارات تمر بهذا المقطع في هذه الساعة حسب المحاكاة، فالأثر لا يُذكر. جرّب شارعاً رئيسياً أو ساعة ذروة.";
    else head = `${ar(Math.round(r.affected))} سيارة كانت بتمر من هنا خلال ${DUR[r.duration] || r.duration + " دقيقة"}. ${r.type === "lane" || r.type === "works" ? "بعضها يكمل ببطء وبعضها يغيّر طريقه" : "كلها تتحول لطرق بديلة"}، وتتأخر السيارة المتأثرة ${ar(Math.max(0, r.extraPerAffectedMin), 1)} دقيقة في المتوسط${q0 && q0.m > 40 ? `، ويتكوّن طابور طوله حوالي ${ar(Math.round(q0.m / 10) * 10)} متر عند ${q0.name ? meta.names[q0.name] : "أحد التقاطعات"}` : ""}.`;
    $("r-head").textContent = head;
    $("r-roads").innerHTML = r.topRoads.length
      ? r.topRoads.map(([nm, dv]) => `<li>${meta.names[nm] || "شارع"} <small>+${ar(dv >= 100 ? Math.round(dv / 10) * 10 : Math.round(dv))} سيارة/ساعة</small></li>`).join("")
      : `<li>${r.type === "rain" ? "لا تحويلات: المطر يبطّئ الجميع في أماكنهم" : "لا تحويلات تُذكر"}</li>`;
    show("s-result");
    // frame the affected area
    const b = new maplibregl.LngLatBounds();
    for (const f of feats.slice(0, 400)) for (const c of f.geometry.coordinates) b.extend(c);
    for (const e of cut) for (const c of coords(e)) b.extend(c);
    if (!b.isEmpty()) map.fitBounds(b, { padding: { top: 90, bottom: Math.round(window.innerHeight * 0.55), left: 30, right: window.innerWidth > 900 ? 440 : 30 }, maxZoom: 15.5, duration: 900 });
  }

  // detour dots move along the new routes
  function animate(t) {
    if (detours.length && map.getSource("dots")) {
      animT = t / 1000;
      const pts = [];
      for (const d of detours) for (let j = 0; j < d.k; j++) {
        const s = ((animT * 0.0016 + j / d.k) % 1) * d.L;
        let k = 1; while (k < d.cum.length && d.cum[k] < s) k++;
        if (k >= d.pts.length) continue;
        const a = d.pts[k - 1], b = d.pts[k], f = (s - d.cum[k - 1]) / (d.cum[k] - d.cum[k - 1] || 1);
        pts.push({ type: "Feature", properties: {}, geometry: { type: "Point", coordinates: [a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f] } });
      }
      map.getSource("dots").setData({ type: "FeatureCollection", features: pts });
    }
    if (!window.matchMedia("(prefers-reduced-motion: reduce)").matches) requestAnimationFrame(animate);
  }
  requestAnimationFrame(animate);

  loadGraph().catch(() => { $("engine-status").textContent = "تعذّر تحميل شبكة الطرق."; });
})();
