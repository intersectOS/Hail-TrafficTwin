// Capture viewer screenshots for arbitrary runs (integration checks). Needs the API and `npm run dev`.
//   TT_WEB_URL=http://localhost:5173 node scripts/screenshot-runs.mjs shots.json
// shots.json: [{"name": "integration-baseline", "q": {"run": "<run_id>", "t": "08:00"}, "play": 0}, ...]
// Each shot fails loudly when its run is not listed by /api/runs.
import { mkdirSync, readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { BASE, launch, sleep, waitReady } from "./lib.mjs";

const here = dirname(fileURLToPath(import.meta.url));
const OUT = resolve(here, "../../docs/img");
mkdirSync(OUT, { recursive: true });
const shots = JSON.parse(readFileSync(process.argv[2], "utf8"));

const browser = await launch();
const results = [];
let failed = false;
try {
  const page = await browser.newPage();
  page.on("console", (m) => {
    if (m.type() === "error") console.log(`  [page error] ${m.text().slice(0, 200)}`);
  });
  await page.goto(BASE + "/?panel=none", { waitUntil: "domcontentloaded" });
  const runs = await page.evaluate(async () => (await fetch("/api/runs")).json());
  const ids = new Set(runs.map((r) => r.run_id));
  for (const s of shots) {
    for (const key of ["run", "compare"]) {
      if (s.q[key] && !ids.has(s.q[key])) {
        console.log(`MISSING ${s.name}: run ${s.q[key]} not listed by /api/runs`);
        failed = true;
      }
    }
    const url = `${BASE}/?${new URLSearchParams(s.q)}`;
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
    await page.screenshot({ path: resolve(OUT, `${s.name}.png`) });
    results.push({ name: s.name, url, ready_ms: ms });
    console.log(`${s.name}.png  ready in ${ms} ms  ${url}`);
  }
} finally {
  await browser.close();
}
console.log(JSON.stringify(results, null, 2));
if (failed) process.exit(1);
