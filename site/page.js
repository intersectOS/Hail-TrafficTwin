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

  // ------------------------------------------------------------------ results
  const AR = {
    remote_work_30: "العمل عن بعد لـ 30٪ من موظفي المكاتب",
    staggered_schools_60: "تدريج دوام المدارس ساعة",
    cordon_center: "رسوم دخول مركز حائل 10 ريالات (7:00–19:00)",
    wadi_adiri_flowing: "جريان وادي الأديرع: إغلاق المعابر الأرضية (الجسور مفتوحة)",
    widen_king_abdulaziz: "توسعة طريق الملك عبدالعزيز إلى 4 مسارات",
    bus_line_king_abdulaziz: "خط حافلات على طريق الملك عبدالعزيز",
    ridehail_plus_10: "تحوّل 10٪ إلى تطبيقات التوصيل",
    friday: "يوم الجمعة",
    ramadan_weekday: "يوم عمل في رمضان",
    accident_center: "حادث يغلق طريق الملك عبدالعزيز جنوباً 20 دقيقة",
    rain_center: "أمطار غزيرة 40 دقيقة",
    flood_center: "سيل الأديرع يغلق معبري شارع جرير وطريق الملك فيصل",
    motorcade_center: "موكب على طريق الملك عبدالعزيز",
    emergency_center: "إسعاف إلى مستشفى الملك خالد مع حادث على طريقه",
    emergency_center_0830: "إسعاف الساعة 8:30 إلى مستشفى الملك خالد",
    evac_stadium: "إخلاء جمهور المدينة الرياضية (3,000 سيارة)",
    evac_wadi_flood: "إخلاء ضفة الأديرع في يوم سيل (1,200 سيارة)",
  };
  const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const fmt = (v, d = 1) => (v == null || Number.isNaN(v) ? "–" : Number(v).toLocaleString("en-US", { maximumFractionDigits: d }));
  const pct = (v) => {
    if (v == null || Number.isNaN(v)) return "–";
    const cls = v < -0.05 ? "good" : v > 0.05 ? "bad" : "";
    return `<span class="${cls}">${v > 0 ? "+" : ""}${fmt(v, 1)}٪</span>`;
  };
  const minutes = (s) => (s == null ? "–" : `${fmt(s / 60, 1)} د`);

  function render(r) {
    const body = document.getElementById("results-body");
    const out = [];
    const bl = (r.baselines || []).find((b) => b.daytype === "weekday");
    if (bl) {
      document.getElementById("results-intro").insertAdjacentHTML("beforeend",
        ` اليوم الأساسي يحاكي ${fmt((bl.sample || 0) * 100, 0)}٪ من السكان.`);
    }
    const pols = (r.policies || []).filter((p) => p.kpis);
    if (pols.length) {
      out.push(`<h3>قرارات المدينة مقارنة باليوم العادي</h3><div class="table-wrap"><table><thead><tr>
        <th>القرار</th><th>متوسط التأخير لكل رحلة</th><th>التأخير في ذروة الصباح</th><th>ساعات السفر الكلية</th><th>الانبعاثات</th></tr></thead><tbody>`);
      for (const p of pols) {
        const k = p.kpis;
        out.push(`<tr><td>${esc(AR[p.id] || p.title || p.id)}</td>
          <td class="num">${pct(k.mean_delay_s?.delta_pct)}</td><td class="num">${pct(k.am_peak_mean_delay_s?.delta_pct)}</td>
          <td class="num">${pct(k.vht?.delta_pct)}</td><td class="num">${pct(k.co2_t?.delta_pct)}</td></tr>`);
      }
      out.push(`</tbody></table></div><p class="note">الأخضر تحسّن والأحمر سوء، مقارنةً بيوم عمل عادي على البذرة العشوائية نفسها. الفروق تحت 2٪ قريبة من تذبذب المحاكاة.</p>`);
    }
    const sc = (r.scenarios || []).filter((s) => s.baseline && s.scenario);
    if (sc.length) {
      out.push(`<h3>حوادث وطوارئ في وسط حائل (ساعة الذروة الصباحية)</h3><div class="table-wrap"><table><thead><tr>
        <th>الحدث</th><th>متوسط التأخير بدونه</th><th>متوسط التأخير معه</th><th>أطول طابور</th></tr></thead><tbody>`);
      for (const s of sc) {
        out.push(`<tr><td>${esc(AR[s.id] || s.title || s.id)}</td><td class="num">${fmt(s.baseline.mean_delay_s, 0)} ث</td>
          <td class="num">${fmt(s.scenario.mean_delay_s, 0)} ث</td><td class="num">${fmt(s.scenario.queue_max_m, 0)} م</td></tr>`);
      }
      out.push(`</tbody></table></div>`);
    }
    for (const st of r.strategist || []) {
      const o = st.options || [];
      if (!o.length) continue;
      out.push(`<h3>مستشار الطوارئ: ${esc(AR[st.id] || st.title || st.id)}</h3><div class="table-wrap"><table><thead><tr>
        <th>الترتيب</th><th>الخيار</th><th>زمن الوصول</th><th>مقارنة بدون خطة</th></tr></thead><tbody>`);
      for (const x of o) {
        out.push(`<tr><td class="num">${x.rank}</td><td dir="ltr" style="text-align:start">${esc(x.label)}</td>
          <td class="num">${fmt(x.travel_time_s, 0)} ث</td><td class="num">${x.vs_no_strategy_s == null ? "–" : `<span class="${x.vs_no_strategy_s < 0 ? "good" : "bad"}">${fmt(x.vs_no_strategy_s, 0)} ث</span>`}</td></tr>`);
      }
      out.push(`</tbody></table></div>`);
      if (o[0].reason) out.push(`<p class="reason">${esc(o[0].reason)}</p>`);
    }
    const ev = (r.evacuations || []).filter((e) => e.clearance);
    if (ev.length) {
      out.push(`<h3>الإخلاء</h3><div class="table-wrap"><table><thead><tr>
        <th>السيناريو</th><th>نصف السيارات خرجت</th><th>90٪ خرجت</th><th>الجميع خرج</th></tr></thead><tbody>`);
      for (const e of ev) {
        const c = e.clearance;
        out.push(`<tr><td>${esc(AR[e.id] || e.title || e.id)}</td><td class="num">${minutes(c.t50_s)}</td>
          <td class="num">${minutes(c.t90_s)}</td><td class="num">${c.t100_s == null ? `${fmt((c.out_share || 0) * 100, 0)}٪ عند نهاية المحاكاة` : minutes(c.t100_s)}</td></tr>`);
      }
      out.push(`</tbody></table></div><p class="note">يُقاس من لحظة أمر الإخلاء. السيناريوهات افتراضية وليست خطط إخلاء حقيقية.</p>`);
    }
    body.innerHTML = out.length ? out.join("") : `<p class="muted">لم تكتمل محاكاة المدينة بعد. افتح المنصة التفاعلية لاستعراض التشغيلات المتاحة.</p>`;
  }
  fetch("data/results.json").then((r) => r.json()).then(render).catch(() => render({}));
})();
