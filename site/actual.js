// "الزحمة الفعلية": Hail's main corridors coloured by TomTom's typical congestion at the chosen hour
// (travel time / no-traffic time), with the hour-by-hour profile of a tapped road next to the model.
(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const cv = $("map"), ctx = cv.getContext("2d");
  let roads = null, obs = null, hour = 7, sel = null, view = null, dpr = 1, W = 0, H = 0;
  const ar = (v, d = 0) => Number(v).toLocaleString("ar-SA", { maximumFractionDigits: d });
  const clock = (h) => `${h}:00`;
  const idx = (v) => (v && v.free_s ? v.tomtom_s / v.free_s : null);
  // Hail is mostly free-flowing (TomTom: the slowest corridor-hour is about 15 % above free flow), so
  // the scale is in percent above the empty-road time: < 4 % free, 4-10 % some slowing, > 10 % slow.
  const col = (r) => (r == null ? "rgba(184,155,114,0.25)" : r < 1.04 ? "#3fa36b" : r < 1.10 ? "#e2a93b" : "#c8483a");
  const word = (r) => (r == null ? "لا توجد بيانات" : r < 1.04 ? "سالك" : r < 1.10 ? "تباطؤ خفيف" : "تباطؤ واضح");
  const mins = (s) => (s < 90 ? `${ar(s)} ثانية` : `${ar(s / 60, 1)} دقيقة`);

  function fit() {
    dpr = Math.min(window.devicePixelRatio || 1, 2);
    W = cv.clientWidth; H = cv.clientHeight;
    cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr);
    // frame the corridors (the city), not the whole clip
    let x0 = 1e9, y0 = 1e9, x1 = -1e9, y1 = -1e9;
    for (const c of obs.corridors) for (let i = 0; i < c.line.length; i += 2) {
      x0 = Math.min(x0, c.line[i]); x1 = Math.max(x1, c.line[i]); y0 = Math.min(y0, c.line[i + 1]); y1 = Math.max(y1, c.line[i + 1]);
    }
    const s = Math.min(W / (x1 - x0), H / (y1 - y0)) * 0.92;
    view = { s, ox: (W - (x1 - x0) * s) / 2 - x0 * s, oy: (H - (y1 - y0) * s) / 2 - y0 * s };
  }
  const X = (x) => view.ox + x * view.s, Y = (y) => view.oy + y * view.s;

  function draw() {
    if (!obs) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.fillStyle = "#172227"; ctx.fillRect(0, 0, W, H);
    ctx.lineCap = "round"; ctx.lineJoin = "round";
    if (roads) {
      ctx.strokeStyle = "rgba(184,155,114,0.18)"; ctx.lineWidth = 1;
      ctx.beginPath();
      for (const a of roads.lines) { ctx.moveTo(X(a[1]), Y(a[2])); for (let k = 3; k < a.length; k += 2) ctx.lineTo(X(a[k]), Y(a[k + 1])); }
      ctx.stroke();
    }
    for (const c of obs.corridors) {
      const v = c.hours[hour];
      ctx.strokeStyle = col(idx(v)); ctx.lineWidth = c === sel ? 6 : 3.2;
      ctx.beginPath(); ctx.moveTo(X(c.line[0]), Y(c.line[1]));
      for (let k = 2; k < c.line.length; k += 2) ctx.lineTo(X(c.line[k]), Y(c.line[k + 1]));
      ctx.stroke();
    }
    if (sel) {
      ctx.strokeStyle = "#eef1ec"; ctx.lineWidth = 1.5; ctx.setLineDash([4, 3]);
      ctx.beginPath(); ctx.moveTo(X(sel.line[0]), Y(sel.line[1]));
      for (let k = 2; k < sel.line.length; k += 2) ctx.lineTo(X(sel.line[k]), Y(sel.line[k + 1]));
      ctx.stroke(); ctx.setLineDash([]);
    }
  }

  function top() {
    const list = obs.corridors.map((c) => ({ c, r: idx(c.hours[hour]) })).filter((x) => x.r != null).sort((a, b) => b.r - a.r).slice(0, 8);
    $("top").innerHTML = "";
    for (const { c, r } of list) {
      const li = document.createElement("li");
      const v = c.hours[hour];
      li.innerHTML = `<span>${c.name}</span><b>+${ar((r - 1) * 100)}٪ · ${mins(v.tomtom_s)}</b>`;
      li.title = `x${r.toFixed(2)}`;
      li.addEventListener("click", () => pick(c));
      $("top").appendChild(li);
    }
  }

  function pick(c) {
    sel = c;
    const v = c.hours[hour] || {};
    const hs = [...Array(24).keys()];
    // bars start at the empty-road time, so the hours that are slower stand out
    const vals = hs.map((h) => c.hours[h]?.tomtom_s || 0);
    const maxT = Math.max(...vals, 1), base = Math.min(...vals.filter((v) => v > 0), maxT) * 0.97;
    const bars = hs.map((h) => `<span class="${h === hour ? "on" : ""}" style="height:${vals[h] ? Math.max(4, Math.round(((vals[h] - base) / (maxT - base || 1)) * 100)) : 0}%" title="${h}:00"></span>`).join("");
    const r = idx(v);
    $("road").hidden = false;
    $("road").innerHTML = `<h3>${c.name}</h3>
      <p class="what">مقطع طوله ${ar(c.length_m / 1000, 1)} كم. الساعة ${clock(hour)}: ${word(r)}${r ? `، أبطأ من الطريق الفاضي بـ ${ar((r - 1) * 100)}٪` : ""}.</p>
      <div class="pair"><div><small>الزمن المعتاد الساعة ${clock(hour)} (TomTom)</small><b>${v.tomtom_s ? mins(v.tomtom_s) : "–"}</b></div>
      <div><small>والطريق فاضي</small><b>${v.free_s ? mins(v.free_s) : "–"}</b></div></div>
      ${v.model_s ? `<p class="what">في النموذج: ${mins(v.model_s)} (${v.model_s > v.tomtom_s ? "أبطأ" : "أسرع"} من الواقع بـ ${ar(Math.abs(v.model_s / v.tomtom_s - 1) * 100)}٪).</p>` : ""}
      <div class="bars" aria-label="الزمن المعتاد على مدار اليوم">${bars}</div><div class="bars-axis"><span>0</span><span>6</span><span>12</span><span>18</span><span>23</span></div>`;
    draw();
    $("road").scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  cv.addEventListener("click", (e) => {
    if (!obs) return;
    const r = cv.getBoundingClientRect(), px = e.clientX - r.left, py = e.clientY - r.top;
    let best = null, bd = 18;
    for (const c of obs.corridors) for (let k = 0; k + 3 < c.line.length; k += 2) {
      const ax = X(c.line[k]), ay = Y(c.line[k + 1]), bx = X(c.line[k + 2]), by = Y(c.line[k + 3]);
      const dx = bx - ax, dy = by - ay, t = Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy || 1)));
      const d = Math.hypot(px - ax - t * dx, py - ay - t * dy);
      if (d < bd) { bd = d; best = c; }
    }
    if (best) pick(best);
  });

  $("hour").addEventListener("input", (e) => {
    hour = +e.target.value; $("hour-out").textContent = clock(hour);
    top(); if (sel) pick(sel); else draw();
  });
  window.addEventListener("resize", () => { if (obs) { fit(); draw(); } });

  // ------------------------------------------------------------ live: TomTom traffic flow tiles
  let liveMap = null, liveTimer = null;
  const KEY = (window.HAIL_LIVE && window.HAIL_LIVE.tomtomKey) || "";
  const flowUrl = () => `https://api.tomtom.com/traffic/map/4/tile/flow/relative0-dark/{z}/{x}/{y}.png?key=${KEY}&thickness=6&tileSize=256&t=${Math.floor(Date.now() / 120000)}`;
  function stamp() {
    const d = new Date();
    $("live-when").textContent = `من TomTom مباشرة. آخر تحديث الساعة ${d.toLocaleTimeString("ar-SA", { hour: "numeric", minute: "2-digit" })}، ويتحدّث كل دقيقتين.`;
  }
  function startLive() {
    document.querySelector(".stage").classList.add("is-live");
    $("live-panel").hidden = false; $("typical-panel").hidden = true;
    if (!KEY || !window.maplibregl) { $("live-when").textContent = "الزحمة المباشرة غير متاحة حالياً."; return; }
    if (!liveMap) {
      liveMap = new maplibregl.Map({
        container: "live", style: "https://tiles.openfreemap.org/styles/dark", center: [41.705, 27.53], zoom: 11.6,
        attributionControl: { compact: true, customAttribution: "Traffic © TomTom" },
      });
      liveMap.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-left");
      liveMap.on("load", () => {
        liveMap.addSource("flow", { type: "raster", tiles: [flowUrl()], tileSize: 256 });
        liveMap.addLayer({ id: "flow", type: "raster", source: "flow", paint: { "raster-opacity": 0.95 } });
        stamp();
      });
    } else { liveMap.resize(); }
    clearInterval(liveTimer);
    liveTimer = setInterval(() => {
      const src = liveMap && liveMap.getSource("flow");
      if (src && src.setTiles) { src.setTiles([flowUrl()]); stamp(); }
    }, 120000);
  }
  function stopLive() {
    document.querySelector(".stage").classList.remove("is-live");
    $("live-panel").hidden = true; $("typical-panel").hidden = false;
    clearInterval(liveTimer);
    if (obs) { fit(); draw(); }
  }
  document.querySelectorAll("[data-mode]").forEach((b) => b.addEventListener("click", () => {
    document.querySelectorAll("[data-mode]").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
    if (b.dataset.mode === "live") startLive(); else stopLive();
  }));
  if (location.hash === "#now") document.querySelector('[data-mode="live"]').click();

  // start on the current hour in Hail
  hour = (new Date().getUTCHours() + 3) % 24;
  $("hour").value = String(hour); $("hour-out").textContent = clock(hour);

  Promise.all([fetch("data/observed.json").then((r) => (r.ok ? r.json() : null)), fetch("data/roads.json").then((r) => r.json()).catch(() => null)])
    .then(([o, rd]) => {
      roads = rd;
      if (!o || !o.corridors?.length) { $("top").innerHTML = `<li class="muted">بيانات الزحمة الفعلية لم تُسحب بعد.</li>`; return; }
      obs = o;
      fit(); top(); draw();
    });
})();
