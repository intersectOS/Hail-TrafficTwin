// "جرّب بنفسك": pick an experiment, play the simulated vehicles of the window with and without the
// event. Data from data/play/ (scripts/hail/playback.py): positions every 3 simulated seconds; the
// dots move linearly between two simulated positions for display. Synthetic demand, uncalibrated.
(() => {
  "use strict";
  const L = {
    accident_center: ["حادث على طريق الملك عبدالعزيز", "حادث يغلق مسارات الطريق جنوباً عشرين دقيقة في ذروة الصباح.", "وقع الحادث: أُغلق طريق الملك عبدالعزيز جنوباً"],
    flood_center: ["سيل وادي الأديرع", "الوادي يجري ويغلق معبري شارع جرير وطريق الملك فيصل.", "جرى الوادي: أُغلق معبرا الأديرع"],
    rain_center: ["أمطار غزيرة", "أربعون دقيقة من المطر الغزير على وسط حائل.", "بدأ المطر الغزير: السائقون يبطئون"],
    motorcade_center: ["موكب رسمي", "موكب من ست سيارات على طريق الملك عبدالعزيز مع إيقاف التقاطعات.", "انطلق الموكب: التقاطعات تُوقف بالتتابع"],
    emergency_center: ["إسعاف إلى مستشفى الملك خالد", "إسعاف من حي الوسيطاء وأمامه حادث يغلق مساراً على طريقه.", "انطلق الإسعاف إلى مستشفى الملك خالد"],
    evac_stadium: ["إخلاء المدينة الرياضية", "3,000 سيارة تغادر ملعب الأمير عبدالعزيز بن مساعد بعد فعالية.", "صدر أمر الإخلاء: الجمهور يغادر الملعب"],
    evac_wadi_flood: ["إخلاء ضفة الأديرع في يوم سيل", "1,200 سيارة تُخلى من الأحياء الملاصقة للوادي.", "صدر أمر الإخلاء: سكان ضفة الوادي يغادرون"],
    demo_events: ["حادث وأمطار وموكب (تجربة صغيرة)", "نافذة تجريبية صغيرة في وسط حائل.", "بدأت الأحداث"],
    evac_demo: ["إخلاء صغير (تجربة صغيرة)", "نافذة تجريبية صغيرة في وسط حائل.", "صدر أمر الإخلاء"],
  };
  const ORDER = ["accident_center", "flood_center", "evac_stadium", "emergency_center", "motorcade_center", "rain_center", "evac_wadi_flood"];
  const $ = (id) => document.getElementById(id);
  const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const cv = $("map"), ctx = cv.getContext("2d");
  let W = 0, H = 0, dpr = 1;
  let data = null, sides = {}, side = "scen", simT = 0, speed = 30, playing = false, last = 0, bannerUntil = 0, announced = false;
  let view = { s: 1, ox: 0, oy: 0 }, roads = null;
  const ar = (n) => Number(n).toLocaleString("ar-SA");

  // ------------------------------------------------------------ choices
  let chosen = null;
  fetch("data/play/index.json").then((r) => r.json()).then((idx) => {
    const box = $("choices");
    box.innerHTML = "";
    const real = idx.filter((x) => !x.id.includes("demo"));
    const list = (real.length ? real : idx).slice().sort((a, b) => (ORDER.indexOf(a.id) + 99) % 99 - (ORDER.indexOf(b.id) + 99) % 99);
    for (const it of list) {
      const [t, d] = L[it.id] || [it.id, ""];
      const b = document.createElement("button");
      b.type = "button"; b.className = "choice"; b.setAttribute("role", "radio"); b.setAttribute("aria-checked", "false");
      b.innerHTML = `<b>${t}</b><span>${d}</span>`;
      b.addEventListener("click", () => {
        chosen = it.id;
        box.querySelectorAll(".choice").forEach((x) => x.setAttribute("aria-checked", String(x === b)));
        $("run").disabled = false;
      });
      box.appendChild(b);
    }
    if (!list.length) box.innerHTML = `<p class="muted">لا توجد تجارب بعد: محاكاة المدينة ما زالت تعمل.</p>`;
  }).catch(() => { $("choices").innerHTML = `<p class="muted">تعذّر تحميل قائمة التجارب.</p>`; });

  $("run").addEventListener("click", () => chosen && start(chosen));
  $("again").addEventListener("click", () => { playing = false; $("play").hidden = true; $("pick").hidden = false; });

  // ------------------------------------------------------------ data
  function decode(buf) {
    const dv = new DataView(buf);
    const n = dv.getUint32(4, true), t0 = dv.getFloat32(8, true), step = dv.getFloat32(12, true), frames = dv.getUint32(16, true);
    const veh = [];
    let p = 20;
    for (let i = 0; i < n; i++) {
      const f0 = dv.getUint32(p, true), k = dv.getUint32(p + 4, true);
      p += 8;
      const xy = new Uint16Array(buf, p, 2 * k); p += 4 * k;
      const sp = new Uint8Array(buf, p, k); p += k;
      p += (4 - (p % 4)) % 4;
      veh.push({ f0, k, xy, sp });
    }
    return { t0, step, frames, veh };
  }

  async function start(id) {
    $("run").disabled = true; $("run").textContent = "تُحمَّل المحاكاة…";
    try {
      data = await (await fetch(`data/play/${id}.json`)).json();
      sides = {};
      await Promise.all(Object.entries(data.sides).map(async ([k, v]) => {
        const buf = await (await fetch(`data/play/${v.file}`)).arrayBuffer();
        sides[k] = { ...decode(buf), running: v.running, stopped: v.stopped };
      }));
    } catch (e) {
      $("run").textContent = "تعذّر التحميل، حاول مرة أخرى"; $("run").disabled = false; return;
    }
    $("run").textContent = "شغّل المحاكاة"; $("run").disabled = false;
    const [t, d] = L[id] || [data.title || id, ""];
    $("play-title").textContent = t; $("play-what").textContent = d;
    $("side-scen").textContent = id.startsWith("evac") ? "مع الإخلاء" : "مع الحدث";
    document.querySelector('[data-side="base"]').disabled = !sides.base;
    $("pick").hidden = true; $("play").hidden = false;
    side = "scen"; setSidePressed();
    simT = data.t0; announced = false; bannerUntil = 0; $("banner").hidden = true;
    focusEvent();
    playing = !reduce; $("pp").textContent = playing ? "❚❚" : "▶";
    $("stage-top")?.scrollIntoView?.();
    window.scrollTo({ top: 0, behavior: reduce ? "auto" : "smooth" });
    last = performance.now();
    requestAnimationFrame(loop);
  }

  // ------------------------------------------------------------ view
  function fit() {
    dpr = Math.min(window.devicePixelRatio || 1, 2);
    W = cv.clientWidth; H = cv.clientHeight;
    cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr);
    roads = null;
  }
  function focusEvent() {
    fit();
    const m = (data.marks || [])[0];
    let cx = 5000, cy = 5000, z = 1;
    if (m) {
      const pts = m.pt || m.line || m.poly || [];
      if (pts.length >= 2) {
        let sx = 0, sy = 0, c = 0;
        for (let i = 0; i < pts.length; i += 2) { sx += pts[i]; sy += pts[i + 1]; c++; }
        cx = sx / c; cy = sy / c; z = 2.6;
      }
    }
    const base = Math.min(W, H) / 10000;
    view.s = base * z;
    view.ox = W / 2 - cx * view.s; view.oy = H / 2 - cy * view.s;
  }
  const X = (x) => view.ox + x * view.s, Y = (y) => view.oy + y * view.s;

  function drawRoads() {
    roads = document.createElement("canvas");
    roads.width = cv.width; roads.height = cv.height;
    const c = roads.getContext("2d");
    c.setTransform(dpr, 0, 0, dpr, 0, 0);
    c.lineCap = "round"; c.lineJoin = "round";
    for (const Ln of data.lines) {
      c.strokeStyle = Ln[0] === 5 ? "rgba(184,155,114,0.22)" : "rgba(184,155,114,0.5)";
      c.lineWidth = Ln[0] === 5 ? 1 : 2.2;
      c.beginPath(); c.moveTo(X(Ln[1]), Y(Ln[2]));
      for (let k = 3; k < Ln.length; k += 2) c.lineTo(X(Ln[k]), Y(Ln[k + 1]));
      c.stroke();
    }
  }

  // pan (drag), zoom (wheel, pinch)
  const ptrs = new Map();
  let pinch0 = 0;
  cv.addEventListener("pointerdown", (e) => { cv.setPointerCapture(e.pointerId); ptrs.set(e.pointerId, [e.offsetX, e.offsetY]); if (ptrs.size === 2) pinch0 = dist(); });
  cv.addEventListener("pointerup", (e) => { ptrs.delete(e.pointerId); pinch0 = 0; });
  cv.addEventListener("pointercancel", (e) => { ptrs.delete(e.pointerId); pinch0 = 0; });
  cv.addEventListener("pointermove", (e) => {
    if (!ptrs.has(e.pointerId) || !data) return;
    const [px, py] = ptrs.get(e.pointerId);
    ptrs.set(e.pointerId, [e.offsetX, e.offsetY]);
    if (ptrs.size === 1) { view.ox += e.offsetX - px; view.oy += e.offsetY - py; roads = null; draw(); }
    else if (ptrs.size === 2 && pinch0) { const d = dist(); zoomAt(d / pinch0, ...mid()); pinch0 = d; }
  });
  cv.addEventListener("wheel", (e) => { if (!data) return; e.preventDefault(); zoomAt(e.deltaY < 0 ? 1.15 : 1 / 1.15, e.offsetX, e.offsetY); }, { passive: false });
  function dist() { const [a, b] = [...ptrs.values()]; return Math.hypot(a[0] - b[0], a[1] - b[1]) || 1; }
  function mid() { const [a, b] = [...ptrs.values()]; return [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2]; }
  function zoomAt(f, x, y) {
    const ns = Math.min(Math.max(view.s * f, Math.min(W, H) / 10000 * 0.8), Math.min(W, H) / 10000 * 12);
    f = ns / view.s;
    view.ox = x - (x - view.ox) * f; view.oy = y - (y - view.oy) * f; view.s = ns; roads = null; draw();
  }
  window.addEventListener("resize", () => { if (data) { const cx = (W / 2 - view.ox) / view.s, cy = (H / 2 - view.oy) / view.s, z = view.s / (Math.min(W, H) / 10000); fit(); view.s = Math.min(W, H) / 10000 * z; view.ox = W / 2 - cx * view.s; view.oy = H / 2 - cy * view.s; draw(); } });

  // ------------------------------------------------------------ playback
  const col = (v) => (v >= 40 ? "#3fa36b" : v >= 15 ? "#e2a93b" : "#c8483a");
  function draw() {
    if (!data) return;
    if (!roads) drawRoads();
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, cv.width, cv.height);
    ctx.drawImage(roads, 0, 0);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const S = sides[side];
    // event marks while the event is active
    for (const m of data.marks || []) {
      const active = simT >= (m.t ?? 0) && (m.end == null || simT <= m.end);
      if (!active) continue;
      if (m.line && m.line.length >= 4) {
        ctx.setLineDash([6, 5]); ctx.lineWidth = 3; ctx.strokeStyle = m.type === "emergency_trip" ? "#eef1ec" : "#b89b72";
        ctx.beginPath(); ctx.moveTo(X(m.line[0]), Y(m.line[1]));
        for (let k = 2; k < m.line.length; k += 2) ctx.lineTo(X(m.line[k]), Y(m.line[k + 1]));
        ctx.stroke(); ctx.setLineDash([]);
      } else if (m.poly) {
        ctx.lineWidth = 2; ctx.strokeStyle = "#eef1ec"; ctx.fillStyle = "rgba(238,241,236,0.08)";
        ctx.beginPath(); ctx.moveTo(X(m.poly[0]), Y(m.poly[1]));
        for (let k = 2; k < m.poly.length; k += 2) ctx.lineTo(X(m.poly[k]), Y(m.poly[k + 1]));
        ctx.closePath(); ctx.fill(); ctx.stroke();
      } else if (m.pt) {
        const pulse = reduce ? 0 : (Math.sin(performance.now() / 250) + 1) * 4;
        ctx.beginPath(); ctx.arc(X(m.pt[0]), Y(m.pt[1]), 9 + pulse, 0, 6.283);
        ctx.fillStyle = m.type === "flood" ? "rgba(70,140,220,0.45)" : "rgba(200,72,58,0.45)"; ctx.fill();
        ctx.beginPath(); ctx.arc(X(m.pt[0]), Y(m.pt[1]), 5, 0, 6.283);
        ctx.fillStyle = m.type === "flood" ? "#468cdc" : "#c8483a"; ctx.fill();
      }
    }
    if (!S) return;
    const f = (simT - S.t0) / S.step, fi = Math.floor(f), a = f - fi;
    const r = Math.max(1.6, Math.min(4, view.s * 9));
    const groups = { "#3fa36b": [], "#e2a93b": [], "#c8483a": [] };
    for (const v of S.veh) {
      const j = fi - v.f0;
      if (j < 0 || j >= v.k) continue;
      const j2 = Math.min(j + 1, v.k - 1);
      const x = v.xy[2 * j] + (v.xy[2 * j2] - v.xy[2 * j]) * a, y = v.xy[2 * j + 1] + (v.xy[2 * j2 + 1] - v.xy[2 * j + 1]) * a;
      groups[col(v.sp[j])].push(X(x), Y(y));
    }
    for (const [c, pts] of Object.entries(groups)) {
      ctx.fillStyle = c; ctx.beginPath();
      for (let i = 0; i < pts.length; i += 2) { ctx.moveTo(pts[i] + r, pts[i + 1]); ctx.arc(pts[i], pts[i + 1], r, 0, 6.283); }
      ctx.fill();
    }
    const k = Math.min(Math.max(fi, 0), S.running.length - 1);
    $("n-run").textContent = ar(S.running[k] || 0);
    $("n-stop").textContent = ar(S.stopped[k] || 0);
    const clk = data.clock0_s + simT, hh = Math.floor(clk / 3600) % 24, mm = Math.floor((clk % 3600) / 60);
    $("clock").textContent = `${hh}:${String(mm).padStart(2, "0")}`;
    $("scrub").value = String(Math.round(((simT - data.t0) / (data.t1 - data.t0)) * 1000));
  }

  function loop(now) {
    if (!data) return;
    const dt = Math.min(0.1, (now - last) / 1000);
    last = now;
    if (playing) {
      simT += dt * speed;
      if (simT >= data.t1) { simT = data.t1; playing = false; $("pp").textContent = "▶"; }
    }
    if (!announced && simT >= data.t_event && side === "scen") {
      announced = true;
      const clk = data.clock0_s + data.t_event;
      $("banner").textContent = `${Math.floor(clk / 3600)}:${String(Math.floor((clk % 3600) / 60)).padStart(2, "0")} ${(L[data.id] || [])[2] || "بدأ الحدث"}`;
      $("banner").hidden = false; bannerUntil = now + 6000;
    }
    if (bannerUntil && now > bannerUntil) { $("banner").hidden = true; bannerUntil = 0; }
    draw();
    if (!$("play").hidden) requestAnimationFrame(loop);
  }

  function setSidePressed() { document.querySelectorAll("[data-side]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.side === side))); }
  document.querySelectorAll("[data-side]").forEach((b) => b.addEventListener("click", () => { if (!sides[b.dataset.side]) return; side = b.dataset.side; setSidePressed(); draw(); }));
  $("pp").addEventListener("click", () => {
    if (!data) return;
    if (simT >= data.t1) { simT = data.t0; announced = false; }
    playing = !playing; $("pp").textContent = playing ? "❚❚" : "▶"; $("pp").setAttribute("aria-label", playing ? "إيقاف مؤقت" : "تشغيل");
  });
  $("scrub").addEventListener("input", (e) => { if (!data) return; simT = data.t0 + (data.t1 - data.t0) * (+e.target.value / 1000); announced = simT >= data.t_event; draw(); });
  $("speed").addEventListener("change", (e) => { speed = +e.target.value; });
})();
