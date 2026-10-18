// Release screenshots (docs/img/final-*.png) of the runs `make demo` produced, read from
// runs/demo-manifest.json. Needs the API and the viewer running (`make demo DETACH=1`).
//   node scripts/final-shots.mjs            (TT_WEB_URL defaults to http://localhost:5173)
// Shots: (a) city, (b) Tier A playback mid-day, (c) Tier B scenario with vehicles, (d) strategist
// panel, (e) policy comparison, (f) Loop candidate map only when a Loop run is listed by the API.
import { execFileSync } from "node:child_process";
import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { BASE } from "./lib.mjs";

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, "../..");
const manifest = JSON.parse(readFileSync(resolve(root, "runs/demo-manifest.json"), "utf8"));
const seed = process.env.TT_SEED || "1";
const step = (name) => manifest.steps[`${name}-s${seed}`];
const CITY_VIEW = "39.2,21.55,10.6";
const DEMO_VIEW = "39.157,21.55,15.2,45,-15";

const shots = [];
const tierA = step("tier-a");
if (tierA) {
  const run = tierA.runs[0];
  shots.push({ name: "final-city", q: { run, t: "12:30", metric: "speed_rel", hidenodata: "1", view: CITY_VIEW } });
  shots.push({ name: "final-tierA-midday", q: { run, t: "12:30", metric: "speed_rel", hidenodata: "1", view: "39.17,21.56,12.2,40,0" } });
} else {
  console.log("no tier-a step in the manifest (CITY=0?): skipping (a) and (b)");
}
const events = step("events");
if (events) {
  shots.push({ name: "final-tierB-scenario", q: { run: events.runs[0], t: "00:04:00", metric: "speed_rel", panel: "reports", view: DEMO_VIEW }, play: 3000 });
}
const strat = step("strategist");
if (strat) shots.push({ name: "final-strategist", q: { run: strat.runs[0], t: "00:03:20", panel: "strategist", view: DEMO_VIEW } });
const policy = step("policy");
if (policy) {
  const [run, compare] = policy.runs;
  shots.push({ name: "final-policy", q: { run, compare, mode: "diff", metric: "speed_kmh", t: "07:00", panel: "reports", view: "39.157,21.55,14.6" } });
}

// (f) Loop runs exist only once Track D is merged; detect them through the API.
const runs = await (await fetch(`${BASE}/api/runs`)).json();
const loop = runs.find((r) => /loop/i.test(r.run_id) || /loop/i.test(r.kind ?? ""));
if (loop) shots.push({ name: "final-loop", q: { run: loop.run_id, panel: "reports", view: CITY_VIEW } });
else console.log("no Loop run listed by /api/runs (Track D not merged): skipping (f)");

mkdirSync(resolve(root, "logs"), { recursive: true });
const file = resolve(root, "logs/final-shots.json");
writeFileSync(file, JSON.stringify(shots, null, 1));
execFileSync(process.execPath, [resolve(here, "screenshot-runs.mjs"), file], { stdio: "inherit" });
