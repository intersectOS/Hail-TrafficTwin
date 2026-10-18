// Frame-rate and memory measurement for the viewer (see docs/viewer.md, "Performance").
//   TT_WEB_URL=http://localhost:5173 npm run perf            (needs the API and `npm run dev`)
// Scenarios: full-city Tier A playing at 300x (static camera, then orbiting camera so every frame
// is a full redraw) and Tier B trips playing (orbiting). Prints one JSON summary.
import { execFileSync } from "node:child_process";
import { BASE, GPU_FLAGS, gpuInfo, launch, sleep, waitReady } from "./lib.mjs";

const SECONDS = Number(process.env.TT_PERF_SECONDS || 20);
const CITY = process.env.TT_PERF_CITY || "smoke-A-s1-5b8a19d3-ab76d081";
const DEMO = process.env.TT_PERF_DEMO || "smoke-B-s1-25c06763-9cfa755f";
const COMPARE = process.env.TT_PERF_COMPARE || "smoke-A-s1-5b8a19d3-6ba142f4";
const DEMO_VIEW = process.env.TT_PERF_DEMO_VIEW || "39.157,21.55,15.2,55,-20";

const SCENARIOS = [
  { name: "tierA_city_300x", url: `/?run=${CITY}&metric=speed_rel&speed=300&panel=none`, speed: 300, orbit: false },
  { name: "tierA_city_300x_orbit", url: `/?run=${CITY}&metric=speed_rel&speed=300&panel=none`, speed: 300, orbit: true },
  { name: "tierA_city_diff_300x_orbit", url: `/?run=${CITY}&compare=${COMPARE}&mode=diff&metric=speed_kmh&speed=300&panel=none`, speed: 300, orbit: true },
  { name: "tierB_trips_60x_orbit", url: `/?run=${DEMO}&speed=60&panel=none&view=${DEMO_VIEW}`, speed: 60, orbit: true },
];

/** RSS (MB) of the Chrome process tree started by puppeteer, split by process type. */
function chromeRss(rootPid) {
  const out = execFileSync("ps", ["-A", "-o", "pid=,ppid=,rss=,command="], { encoding: "utf8", maxBuffer: 64 << 20 });
  const procs = out
    .trim()
    .split("\n")
    .map((l) => {
      const m = /^\s*(\d+)\s+(\d+)\s+(\d+)\s+(.*)$/.exec(l);
      return m ? { pid: +m[1], ppid: +m[2], rss: +m[3], cmd: m[4] } : null;
    })
    .filter(Boolean);
  const tree = new Set([rootPid]);
  let grew = true;
  while (grew) {
    grew = false;
    for (const p of procs) if (!tree.has(p.pid) && tree.has(p.ppid)) (tree.add(p.pid), (grew = true));
  }
  const by = { browser: 0, renderer: 0, gpu: 0, other: 0 };
  for (const p of procs) {
    if (!tree.has(p.pid)) continue;
    const t = /--type=renderer/.test(p.cmd) ? "renderer" : /--type=gpu-process/.test(p.cmd) ? "gpu" : p.pid === rootPid ? "browser" : "other";
    by[t] += p.rss / 1024;
  }
  const total = by.browser + by.renderer + by.gpu + by.other;
  return Object.fromEntries([...Object.entries(by), ["total", total]].map(([k, v]) => [k, Math.round(v)]));
}

const q = (arr, p) => arr[Math.min(arr.length - 1, Math.max(0, Math.floor(p * arr.length)))];

// TT_PERF_UNCAPPED=1 disables vsync / the frame-rate limit to show headroom above 60 fps.
const UNCAPPED = process.env.TT_PERF_UNCAPPED === "1";
const extra = UNCAPPED ? ["--disable-gpu-vsync", "--disable-frame-rate-limit"] : [];
const only = process.argv.slice(2);
const summary = {
  date: new Date().toISOString(),
  chrome_flags: [...GPU_FLAGS, ...extra],
  viewport: "1600x1000 @1x",
  seconds: SECONDS,
  uncapped: UNCAPPED,
  scenarios: {},
};
// A fresh browser per scenario, so heap and RSS are not inflated by earlier pages.
for (const s of SCENARIOS) {
  if (only.length && !only.includes(s.name)) continue;
  const browser = await launch({ width: 1600, height: 1000, extra });
  const rootPid = browser.process()?.pid;
  try {
    const page = await browser.newPage();
    await page.goto(BASE + s.url, { waitUntil: "domcontentloaded" });
    summary.webgl ??= await gpuInfo(page);
    const loadMs = await waitReady(page);
    const res = await page.evaluate(
      async ({ seconds, speed, orbit }) => {
        const e = window.__tt.engine;
        e.perf = { recolours: 0, recolourMsTotal: 0, recolourMsMax: 0 };
        e.setSpeed(speed);
        e.setPlaying(true);
        const frames = [];
        const heap = [];
        // Collect garbage from loading first when exposed (--js-flags=--expose-gc), then measure.
        if (window.gc) window.gc();
        let last = performance.now();
        const t0 = last;
        const bearing0 = e.map.getBearing();
        await new Promise((resolve) => {
          const loop = (now) => {
            frames.push(now - last);
            last = now;
            if (orbit) e.map.jumpTo({ bearing: bearing0 + ((now - t0) / 1000) * 12 });
            if (frames.length % 30 === 0 && performance.memory) heap.push(performance.memory.usedJSHeapSize / 1048576);
            if (now - t0 < seconds * 1000) requestAnimationFrame(loop);
            else resolve();
          };
          requestAnimationFrame(loop);
        });
        e.setPlaying(false);
        return { frames: frames.slice(1), heap, perf: e.perf, cache: e.cacheStats(), simAdvanced: e.t };
      },
      { seconds: SECONDS, speed: s.speed, orbit: s.orbit },
    );
    const rss = rootPid ? chromeRss(rootPid) : null;
    const ft = [...res.frames].sort((a, b) => a - b);
    const fps = ft.map((d) => 1000 / d).sort((a, b) => a - b);
    const meanFps = (res.frames.length * 1000) / res.frames.reduce((a, b) => a + b, 0);
    summary.scenarios[s.name] = {
      load_ms: loadMs,
      frames: res.frames.length,
      mean_fps: +meanFps.toFixed(1),
      median_fps: +q(fps, 0.5).toFixed(1),
      p5_fps: +q(fps, 0.05).toFixed(1),
      p95_frame_ms: +q(ft, 0.95).toFixed(2),
      max_frame_ms: +ft[ft.length - 1].toFixed(1),
      frames_over_33ms: ft.filter((d) => d > 33.4).length,
      heap_mb_max: res.heap.length ? Math.round(Math.max(...res.heap)) : null,
      heap_mb_end: res.heap.length ? Math.round(res.heap[res.heap.length - 1]) : null,
      recolours: res.perf.recolours,
      recolour_ms_mean: res.perf.recolours ? +(res.perf.recolourMsTotal / res.perf.recolours).toFixed(2) : null,
      recolour_ms_max: +res.perf.recolourMsMax.toFixed(2),
      bin_cache: res.cache,
      chrome_rss_mb: rss,
    };
    console.error(`${s.name}: ${JSON.stringify(summary.scenarios[s.name])}`);
  } finally {
    await browser.close();
  }
  await sleep(500);
}
console.log(JSON.stringify(summary, null, 2));
