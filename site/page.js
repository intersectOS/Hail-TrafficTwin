// Project page: the hero draws Hail's main roads (data/roads.json, from the simulation network) with
// vehicles moving along them, and the results section is filled from data/results.json (the
// reports of the latest simulation run). Synthetic demand, uncalibrated.
(() => {
  "use strict";
  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  // ------------------------------------------------------------------ hero
  const canvas = document.getElementById("roads");
  const ctx = canvas.getContext("2d");
  const WIDTH = [2.4, 2.1, 1.6, 1.1, 0.7]; // motorway .. tertiary
  const ALPHA = [0.55, 0.5, 0.42, 0.3, 0.2];
  let lines = [], base = null, cars = [], dpr = 1, W = 0, H = 0, tr = null;

  function fit() {
    dpr = Math.min(window.devicePixelRatio || 1, 2);
    W = canvas.clientWidth; H = canvas.clientHeight;
    canvas.width = Math.round(W * dpr); canvas.height = Math.round(H * dpr);
    // cover the hero with the city, centred a little left of the text (RTL page: text on the right)
    const s = Math.max(W, H) / 10000 * 1.25;
    tr = { s, ox: W * 0.38 - 5000 * s, oy: H * 0.5 - 5000 * s };
    drawBase();
  }
  const X = (x) => (tr.ox + x * tr.s) * dpr;
  const Y = (y) => (tr.oy + y * tr.s) * dpr;

  function drawBase() {
    if (!lines.length) return;
    base = document.createElement("canvas");
    base.width = canvas.width; base.height = canvas.height;
    const b = base.getContext("2d");
    b.lineCap = "round"; b.lineJoin = "round";
    for (let k = 4; k >= 0; k--) {
      b.strokeStyle = `rgba(184,155,114,${ALPHA[k]})`;
      b.lineWidth = WIDTH[k] * dpr;
      b.beginPath();
      for (const L of lines) {
        if (L.k !== k) continue;
        b.moveTo(X(L.p[0]), Y(L.p[1]));
        for (let i = 2; i < L.p.length; i += 2) b.lineTo(X(L.p[i]), Y(L.p[i + 1]));
      }
      b.stroke();
    }
    paint();
  }

  function spawn() {
    // busier classes carry more vehicles: pick a line weighted by length and class
    const L = pickLine();
    const n = L.p.length / 2 - 1;
    const seg = Math.floor(Math.random() * n);
    // speed colour: arterials near the centre run slower in this illustration
    const r = Math.random();
    const col = L.k <= 1 ? (r < 0.85 ? "#3fa36b" : "#e2a93b") : r < 0.6 ? "#3fa36b" : r < 0.88 ? "#e2a93b" : "#c8483a";
    return { L, seg, t: Math.random(), v: (0.004 + Math.random() * 0.01) * (L.k <= 1 ? 1.6 : 1), dir: Math.random() < 0.5 ? 1 : -1, col };
  }
  let cum = [], total = 0;
  function pickLine() {
    const r = Math.random() * total;
    let lo = 0, hi = cum.length - 1;
    while (lo < hi) { const m = (lo + hi) >> 1; if (cum[m] < r) lo = m + 1; else hi = m; }
    return lines[lo];
  }

  function paint() {
    if (!base) return;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(base, 0, 0);
    for (const c of cars) {
      const p = c.L.p, i = c.seg * 2;
      const x = p[i] + (p[i + 2] - p[i]) * c.t, y = p[i + 1] + (p[i + 3] - p[i + 1]) * c.t;
      ctx.fillStyle = c.col;
      ctx.beginPath(); ctx.arc(X(x), Y(y), (c.L.k <= 1 ? 1.9 : 1.5) * dpr, 0, 6.283); ctx.fill();
    }
  }

  function step() {
    for (const c of cars) {
      const p = c.L.p, i = c.seg * 2;
      const len = Math.hypot(p[i + 2] - p[i], p[i + 3] - p[i + 1]) || 1;
      c.t += (c.v * 140) / len * c.dir;
      if (c.t > 1 || c.t < 0) {
        c.seg += c.dir;
        if (c.seg < 0 || c.seg >= p.length / 2 - 1) Object.assign(c, spawn());
        else c.t = c.dir > 0 ? 0 : 1;
      }
    }
    paint();
    if (!document.hidden) requestAnimationFrame(step);
  }
  document.addEventListener("visibilitychange", () => { if (!document.hidden && !reduce && cars.length) requestAnimationFrame(step); });

  fetch("data/roads.json").then((r) => r.json()).then((d) => {
    lines = d.lines.map((a) => ({ k: a[0], p: a.slice(1) }));
    for (const L of lines) {
      let len = 0;
      for (let i = 2; i < L.p.length; i += 2) len += Math.hypot(L.p[i] - L.p[i - 2], L.p[i + 1] - L.p[i - 1]);
      total += len * (L.k <= 1 ? 3 : L.k === 2 ? 2 : 1);
      cum.push(total);
    }
    fit();
    cars = Array.from({ length: Math.min(900, Math.round(W * H / 1400)) }, spawn);
    paint();
    if (!reduce) requestAnimationFrame(step);
  }).catch(() => { /* the hero text stands on its own without the drawing */ });
  window.addEventListener("resize", () => { if (lines.length) fit(); });

  // ------------------------------------------------------------------ scenario cards
  // stories.json: per scenario, road speed/limit on the normal day ("before") and with the decision
  // or event ("after") at the moment they differ most. results.json: the reports' measured numbers.
  const T = {
    wadi_adiri_flowing: ["جريان وادي الأديرع", "أُغلقت كل المعابر الأرضية على الوادي داخل المدينة طوال اليوم، وبقيت الجسور مفتوحة.", "بعد الإغلاق"],
    widen_king_abdulaziz: ["توسعة طريق الملك عبدالعزيز", "أربعة مسارات بدل ثلاثة في كل اتجاه، من المدينة الرياضية إلى الزهراء.", "بعد التوسعة"],
    bus_line_king_abdulaziz: ["خط حافلات على طريق الملك عبدالعزيز", "حافلة كل عشر دقائق من الخماشية إلى طريق الجامعة، وتحوّل 10٪ من الرحلات القريبة إليها.", "مع الخط"],
    cordon_center: ["رسوم دخول مركز حائل", "عشرة ريالات لدخول برزان والعليا وما حولهما من 7 صباحاً إلى 7 مساءً.", "مع الرسوم"],
    remote_work_30: ["العمل عن بعد", "30٪ من موظفي المكاتب يعملون من البيت ثلاثة أيام في الأسبوع.", "مع العمل عن بعد"],
    staggered_schools_60: ["تدريج دوام المدارس", "نصف المدارس يبدأ دوامها بعد ساعة من النصف الآخر.", "بعد التدريج"],
    ridehail_plus_10: ["تطبيقات التوصيل", "10٪ من سائقي السيارات يتحولون إلى تطبيقات التوصيل.", "بعد التحوّل"],
    accident_center: ["حادث على طريق الملك عبدالعزيز", "حادث يغلق مسارات الطريق جنوباً عشرين دقيقة في ذروة الصباح.", "مع الحادث"],
    rain_center: ["أمطار غزيرة على وسط حائل", "أربعون دقيقة من المطر الغزير في ذروة الصباح.", "مع المطر"],
    flood_center: ["سيل الأديرع في وسط المدينة", "الوادي يجري ويغلق معبري شارع جرير وطريق الملك فيصل.", "مع السيل"],
    motorcade_center: ["موكب على طريق الملك عبدالعزيز", "موكب من ست سيارات مع إيقاف التقاطعات بالتتابع.", "مع الموكب"],
    emergency_center: ["إسعاف إلى مستشفى الملك خالد", "إسعاف من حي الوسيطاء وأمامه حادث يغلق مساراً على طريقه.", "مع الحادث"],
    evac_stadium: ["إخلاء المدينة الرياضية", "3,000 سيارة تغادر ملعب الأمير عبدالعزيز بن مساعد بعد فعالية.", "أثناء الإخلاء"],
    evac_wadi_flood: ["إخلاء ضفة الأديرع في يوم سيل", "1,200 سيارة تُخلى من الأحياء الملاصقة للوادي بعد إغلاق معبره.", "أثناء الإخلاء"],
    emergency_center_0830: ["مستشار الطوارئ: إسعاف الساعة 8:30", "يقترح المستشار ثلاثة خيارات مرتبة لوصول الإسعاف إلى مستشفى الملك خالد، والقرار للمسؤول.", ""],
    // demo-window test runs (shown only when no city results exist yet)
    demo_events: ["حادث وأمطار وموكب (نافذة تجريبية)", "تجربة صغيرة على وسط حائل.", "مع الأحداث"],
    evac_demo: ["إخلاء صغير (نافذة تجريبية)", "تجربة صغيرة على وسط حائل.", "أثناء الإخلاء"],
  };
  const ORDER = ["wadi_adiri_flowing", "accident_center", "flood_center", "evac_stadium", "emergency_center_0830", "widen_king_abdulaziz",
    "remote_work_30", "staggered_schools_60", "cordon_center", "bus_line_king_abdulaziz", "emergency_center", "motorcade_center",
    "rain_center", "evac_wadi_flood", "ridehail_plus_10"];
  const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const n0 = (v) => Math.round(Math.abs(v)).toLocaleString("ar-SA");
  const n1 = (v) => (Math.round(Math.abs(v) * 10) / 10).toLocaleString("ar-SA");
  const clock = (s) => { const h = Math.floor(s / 3600) % 24, m = Math.floor((s % 3600) / 60); return `${h}:${String(m).padStart(2, "0")}`; };
  const change = (pctv, what) => pctv == null ? "" : Math.abs(pctv) < 1 ? `${what} لا يتغيّر تقريباً` : `${what} ${pctv < 0 ? "ينخفض" : "يرتفع"} ${n1(pctv)}٪`;

  function sentence(kind, id, R) {
    if (kind === "policy") {
      const p = (R.policies || []).find((x) => x.id === id);
      if (!p) return "";
      const k = p.kpis;
      const parts = [change(k.mean_delay_s?.delta_pct, "متوسط التأخير لكل رحلة"), change(k.am_peak_mean_delay_s?.delta_pct, "وفي ذروة الصباح"),
        change(k.vht?.delta_pct, "ومجموع ساعات القيادة في المدينة")].filter(Boolean);
      return parts.join("، ") + ".";
    }
    if (kind === "scenario") {
      const s = (R.scenarios || []).find((x) => x.id === id);
      if (!s || !s.baseline) return "";
      let t = `متوسط تأخير المركبة في النطاق من ${n0(s.baseline.mean_delay_s)} إلى ${n0(s.scenario.mean_delay_s)} ثانية`;
      if (s.scenario.queue_max_m) t += `، وأطول طابور ${n0(s.scenario.queue_max_m)} متر`;
      const em = s.emergency && (Array.isArray(s.emergency) ? s.emergency[0] : s.emergency);
      if (em && em.travel_time_s) t += `، ووصل الإسعاف في ${n0(em.travel_time_s)} ثانية`;
      return t + ".";
    }
    if (kind === "evacuation") {
      const e = (R.evacuations || []).find((x) => x.id === id);
      const c = e && e.clearance;
      if (!c) return "";
      let t = `خرج نصف السيارات خلال ${n1(c.t50_s / 60)} دقيقة، و90٪ خلال ${n1(c.t90_s / 60)} دقيقة`;
      t += c.t100_s ? `، والجميع خلال ${n1(c.t100_s / 60)} دقيقة.` : `، وبقي ${n0((1 - c.out_share) * 100)}٪ عند نهاية المحاكاة.`;
      return t;
    }
    return "";
  }

  const PLACES = [
    ["برزان", 41.6985, 27.5235], ["مستشفى الملك خالد", 41.6971, 27.5072], ["المدينة الرياضية", 41.6975, 27.5040],
    ["مستشفى حائل العام", 41.6993, 27.5166], ["جامعة حائل", 41.7116, 27.6820], ["مطار حائل", 41.6876, 27.4417],
    ["الأديرع", 41.7180, 27.5160], ["المدينة الصناعية", 41.7971, 27.4671], ["الخماشية", 41.7200, 27.4901], ["العزيزية", 41.6871, 27.5314],
  ];
  const colour = (v) => v === 255 ? null : v >= 80 ? "#3fa36b" : v >= 50 ? "#e2a93b" : "#c8483a";
  function drawMap(cv, geom, vals) {
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const w = cv.clientWidth, h = cv.clientHeight;
    cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr);
    const c = cv.getContext("2d");
    c.setTransform(dpr, 0, 0, dpr, 0, 0);
    c.fillStyle = "#172227"; c.fillRect(0, 0, w, h);
    const s = Math.min(w, h) / 10000 * 0.95, ox = (w - 10000 * s) / 2, oy = (h - 10000 * s) / 2;
    c.lineCap = "round"; c.lineJoin = "round";
    const pass = (coloured) => {
      geom.lines.forEach((L, i) => {
        const col = colour(vals[i]);
        if (!!col !== coloured) return;
        c.strokeStyle = col || "rgba(184,155,114,0.22)";
        c.lineWidth = (L[0] === 5 ? 1 : L[0] <= 2 ? 2.4 : 1.6) * (coloured ? 1.15 : 1);
        c.beginPath(); c.moveTo(ox + L[1] * s, oy + L[2] * s);
        for (let k = 3; k < L.length; k += 2) c.lineTo(ox + L[k] * s, oy + L[k + 1] * s);
        c.stroke();
      });
    };
    pass(false); pass(true);
    // a few place names so the map can be read without a basemap
    const [w0, , , n0b] = geom.bbox, span = geom.span;
    c.font = "600 12px 'IBM Plex Sans Arabic', system-ui, sans-serif";
    c.textAlign = "center";
    const city = geom.lines.length > 4000 || span > 0.08;
    for (const [name, lon, lat] of PLACES) {
      if (city && !["برزان", "جامعة حائل", "مطار حائل", "المدينة الصناعية"].includes(name)) continue;
      const x = ox + ((lon - w0) / span) * 10000 * s, y = oy + ((n0b - lat) / span) * 10000 * s;
      if (x < 30 || x > w - 30 || y < 14 || y > h - 8) continue;
      c.lineWidth = 3; c.strokeStyle = "rgba(23,34,39,0.9)"; c.strokeText(name, x, y);
      c.fillStyle = "#eef1ec"; c.fillText(name, x, y);
    }
  }

  function card(st, geom, R) {
    const [title, what, afterLabel] = T[st.id] || [st.id, "", "بعد"];
    const el = document.createElement("article");
    el.className = "story";
    const say = sentence(st.kind, st.id, R);
    el.innerHTML = `<div class="story-text"><h3>${esc(title)}</h3><p class="what">${esc(what)}</p>
      ${say ? `<p class="say">${esc(say)}</p>` : ""}
      <div class="seg" role="group" aria-label="قبل وبعد"><button type="button" data-v="before">اليوم العادي</button><button type="button" data-v="after" aria-pressed="true">${esc(afterLabel)}</button></div>
      <p class="when">الخريطة: الساعة ${clock(st.t0_s + (st.tier === "B" ? 8 * 3600 : 0))}–${clock(st.t1_s + (st.tier === "B" ? 8 * 3600 : 0))}، اللحظة التي يظهر فيها الفرق أوضح${st.tier === "B" ? "، وسط حائل" : "، مدينة حائل"}.</p></div>
      <canvas class="story-map" aria-label="خريطة ${esc(title)}"></canvas>`;
    const cv = el.querySelector("canvas");
    let view = "after";
    const redraw = () => drawMap(cv, geom, st[view]);
    el.querySelectorAll(".seg button").forEach((b) => b.addEventListener("click", () => {
      view = b.dataset.v;
      el.querySelectorAll(".seg button").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
      redraw();
    }));
    requestAnimationFrame(redraw);
    window.addEventListener("resize", redraw);
    return el;
  }

  function strategistCard(sr) {
    const [title, what] = T[sr.id] || [sr.title || sr.id, ""];
    const o = sr.options || [];
    const ns = o[0] && o[0].no_strategy_tt_s;
    const el = document.createElement("article");
    el.className = "story no-map";
    el.innerHTML = `<div class="story-text"><h3>${esc(title)}</h3><p class="what">${esc(what)}</p>
      ${ns ? `<p class="say">بدون خطة يصل الإسعاف في ${n0(ns)} ثانية. أفضل خيار يوصله في ${n0(o[0].travel_time_s)} ثانية.</p>` : ""}
      <ol class="opts">${o.map((x) => `<li><b>${n0(x.travel_time_s)} ثانية</b> <span dir="ltr">${esc(x.label)}</span></li>`).join("")}</ol></div>`;
    return el;
  }

  Promise.all([fetch("data/stories.json").then((r) => r.json()).catch(() => null), fetch("data/results.json").then((r) => r.json()).catch(() => ({}))])
    .then(([S, R]) => {
      const list = document.getElementById("story-list");
      const items = [];
      for (const st of (S && S.stories) || []) items.push({ id: st.id, el: () => card(st, S.geoms[st.geom], R) });
      for (const sr of R.strategist || []) items.push({ id: sr.id, el: () => strategistCard(sr) });
      if (!items.length) { document.getElementById("story-wait").textContent = "المحاكاة الكاملة تعمل الآن، وتظهر السيناريوهات هنا عند انتهائها."; return; }
      const rank = (id) => { const i = ORDER.indexOf(id); return i < 0 ? 99 : i; };
      items.sort((a, b) => rank(a.id) - rank(b.id));
      list.innerHTML = "";
      for (const it of items) list.appendChild(it.el());
    });
})();
