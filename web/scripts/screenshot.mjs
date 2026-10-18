// Capture the M3 screenshots into docs/img/. Needs the API (port 8000) and `npm run dev`.
//   TT_WEB_URL=http://localhost:5173 npm run screenshot [-- name ...]
import { mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { BASE, GPU_FLAGS, gpuInfo, launch, sleep, waitReady } from "./lib.mjs";

const here = dirname(fileURLToPath(import.meta.url));
const OUT = resolve(here, "../../docs/img");
mkdirSync(OUT, { recursive: true });

const CITY = "smoke-A-s1-5b8a19d3-ab76d081";
const CITY2 = "smoke-A-s1-5b8a19d3-6ba142f4";
const DEMO = "smoke-B-s1-25c06763-9cfa755f";
const DEMO2 = "smoke-B-s2-25c06763-1c6e8f12";

async function runExists(page, id) {
  return page.evaluate(async (id) => {
    const r = await fetch("/api/runs");
    return (await r.json()).some((x) => x.run_id === id && x.has?.edgedata);
  }, id);
}

const SHOTS = [
  { name: "m3-tierA", q: { run: CITY, metric: "speed_rel", t: "00:30", hidenodata: "1", view: "39.2,21.55,10.6" } },
  {
    name: "m3-tierA-diff",
    q: async (page) =>
      (await runExists(page, CITY2))
        ? { run: CITY, compare: CITY2, mode: "diff", metric: "speed_kmh", t: "00:45", hidenodata: "1", view: "39.19,21.545,11.6" }
        : { run: DEMO, compare: DEMO2, mode: "diff", metric: "speed_kmh", t: "00:20" },
  },
  {
    name: "m3-tierB",
    q: { run: DEMO, t: "00:20:00", view: "39.1565,21.5495,15.6,58,-25", metric: "speed_rel" },
    // Short play so the TripsLayer trails are drawn mid-motion, then pause.
    play: 4000,
  },
  { name: "m3-events", q: { run: DEMO, t: "00:40", view: "39.1508,21.5512,16.6,50,-10", panel: "reports" } },
  { name: "m3-strategist", q: { run: DEMO, t: "00:40", panel: "strategist", view: "39.157,21.55,15.2,45,-15" } },
  { name: "m3-choropleth", q: { run: CITY, compare: CITY2, choropleth: "1", t: "00:30", districts: "1", hidenodata: "1", view: "39.2,21.55,10.6" } },
];

const only = process.argv.slice(2);
const browser = await launch();
const results = [];
try {
  const page = await browser.newPage();
  page.on("console", (m) => {
    if (m.type() === "error" || m.type() === "warn") console.log(`  [page ${m.type()}] ${m.text().slice(0, 200)}`);
  });
  await page.goto(BASE + "/?panel=none", { waitUntil: "domcontentloaded" });
  const gpu = await gpuInfo(page);
  console.log("chrome flags:", GPU_FLAGS.join(" "));
  console.log("webgl:", JSON.stringify(gpu));
  for (const s of SHOTS) {
    if (only.length && !only.includes(s.name)) continue;
    const q = typeof s.q === "function" ? await s.q(page) : s.q;
    const url = `${BASE}/?${new URLSearchParams(q)}`;
    await page.goto(url, { waitUntil: "domcontentloaded" });
    const ms = await waitReady(page);
    if (s.play) {
      await page.evaluate(() => {
        const e = window.__tt.engine;
        e.setSpeed(10);
        e.setPlaying(true);
      });
      await sleep(s.play);
      await page.evaluate(() => window.__tt.engine.setPlaying(false));
      await sleep(500);
    }
    const file = resolve(OUT, `${s.name}.png`);
    await page.screenshot({ path: file });
    results.push({ name: s.name, url, ready_ms: ms });
    console.log(`${s.name}.png  ready in ${ms} ms  ${url}`);
  }
} finally {
  await browser.close();
}
console.log(JSON.stringify(results, null, 2));
