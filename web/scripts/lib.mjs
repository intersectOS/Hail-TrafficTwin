// Shared helpers for screenshot.mjs and perf.mjs (puppeteer-core + the installed Google Chrome).
import puppeteer from "puppeteer-core";

export const CHROME =
  process.env.CHROME_PATH || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
export const BASE = process.env.TT_WEB_URL || "http://localhost:5173";

// Flags tried for hardware-accelerated WebGL in headless mode on macOS (Apple Silicon).
// TT_CHROME_FLAGS overrides them (space separated).
export const GPU_FLAGS = process.env.TT_CHROME_FLAGS
  ? process.env.TT_CHROME_FLAGS.split(" ").filter(Boolean)
  : ["--headless=new", "--use-angle=metal", "--enable-gpu", "--ignore-gpu-blocklist", "--enable-webgl"];

export async function launch({ width = 1600, height = 1000, extra = [] } = {}) {
  const browser = await puppeteer.launch({
    executablePath: CHROME,
    headless: false, // the headless mode is chosen by --headless=new in the flags
    args: [...GPU_FLAGS, `--window-size=${width},${height}`, "--enable-precise-memory-info", "--js-flags=--expose-gc", "--hide-scrollbars", ...extra],
    defaultViewport: { width, height, deviceScaleFactor: 1 },
  });
  return browser;
}

/** WebGL vendor/renderer as seen by the page (tells hardware GPU from SwiftShader). */
export async function gpuInfo(page) {
  return page.evaluate(() => {
    const c = document.createElement("canvas");
    const gl = c.getContext("webgl2") || c.getContext("webgl");
    if (!gl) return { webgl: false };
    const ext = gl.getExtension("WEBGL_debug_renderer_info");
    return {
      webgl: true,
      vendor: ext ? gl.getParameter(ext.UNMASKED_VENDOR_WEBGL) : gl.getParameter(gl.VENDOR),
      renderer: ext ? gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) : gl.getParameter(gl.RENDERER),
    };
  });
}

/** Wait until the viewer reports that every fetch finished and deck + MapLibre have drawn. */
export async function waitReady(page, { timeout = Number(process.env.TT_READY_TIMEOUT_MS || 120000), settleMs = 1500 } = {}) {
  const t0 = Date.now();
  try {
    await page.waitForFunction(() => window.__tt && window.__tt.ready(), { timeout, polling: 250 });
  } catch (e) {
    const dbg = await page.evaluate(() => window.__tt?.debug());
    throw new Error(`viewer not ready after ${timeout} ms: ${JSON.stringify(dbg)}`);
  }
  // Require readiness to hold for a moment (bins may still be streaming in after the first frame).
  await new Promise((r) => setTimeout(r, settleMs));
  await page.waitForFunction(() => window.__tt.ready(), { timeout, polling: 250 });
  return Date.now() - t0;
}

export const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
