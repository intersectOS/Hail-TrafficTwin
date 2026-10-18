// Frame-stepping renderer for the movie pipeline (driven by scripts/movies/render.py).
// Opens `<url>/?cinema=<film>` in headless Chrome (puppeteer-core, as the screenshot scripts),
// waits for window.__cinema, then reads JSON commands on stdin, one per line:
//   {"cmd": "render", "from": 0, "to": 150, "dir": "/abs/frames"}  -> f_000000.png ...
//   {"cmd": "quit"}
// and answers with one JSON line per command on stdout ({"event": "ready" | "done" | "error"}).
// Frame i is rendered by window.__cinema.renderFrame(i): no wall-clock time is involved.
import { createInterface } from "node:readline";
import { join } from "node:path";
import { gpuInfo, launch } from "./lib.mjs";

const args = Object.fromEntries(
  process.argv.slice(2).reduce((acc, a, i, all) => (a.startsWith("--") ? [...acc, [a.slice(2), all[i + 1]]] : acc), []),
);
const width = Number(args.width || 1920);
const height = Number(args.height || 1080);
const timeout = Number(args.timeout || 120000);
const say = (o) => process.stdout.write(JSON.stringify(o) + "\n");

const browser = await launch({ width, height });
try {
  const page = await browser.newPage();
  await page.setViewport({ width, height, deviceScaleFactor: 1 });
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  page.on("console", (m) => {
    if (m.type() === "error") errors.push(m.text());
  });
  await page.goto(`${args.url}/?cinema=${encodeURIComponent(args.film)}`, { waitUntil: "load", timeout });
  await page.waitForFunction(() => window.__cinema && (window.__cinema.ready() || window.__cinema.error), {
    timeout,
    polling: 200,
  });
  const err = await page.evaluate(() => window.__cinema.error);
  if (err) throw new Error(err);
  const frames = await page.evaluate(() => window.__cinema.frameCount());
  say({ event: "ready", frames, gpu: await gpuInfo(page), browser_pid: browser.process()?.pid ?? null, errors });
  const rl = createInterface({ input: process.stdin });
  for await (const line of rl) {
    if (!line.trim()) continue;
    const cmd = JSON.parse(line);
    if (cmd.cmd === "quit") break;
    if (cmd.cmd !== "render") {
      say({ event: "error", message: `unknown command ${cmd.cmd}` });
      continue;
    }
    const t0 = Date.now();
    for (let i = cmd.from; i < cmd.to; i++) {
      await page.evaluate((k) => window.__cinema.renderFrame(k), i);
      await page.screenshot({
        path: join(cmd.dir, `f_${String(i).padStart(6, "0")}.png`),
        type: "png",
        captureBeyondViewport: false,
      });
    }
    say({ event: "done", from: cmd.from, to: cmd.to, ms: Date.now() - t0, errors: errors.splice(0) });
  }
} catch (e) {
  say({ event: "error", message: String(e?.stack || e) });
  process.exitCode = 1;
} finally {
  await browser.close();
}
