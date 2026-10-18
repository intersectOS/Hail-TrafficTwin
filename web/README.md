# web: TrafficTwin Jeddah viewer (M3)

React 19 + TypeScript strict + Vite + deck.gl 9.4 + MapLibre 5 (OpenFreeMap vector basemap, no API
key). Tier A edge-bin playback for the whole city, Tier B trajectory playback with extruded
buildings, difference mode, district choropleth, event/closure overlays, strategist panel with
approve/reject, and a start-run form. All data comes from the API in `api/`
(`docs/contracts/run-outputs.md`). Full documentation, URL parameters and measured performance:
[`docs/viewer.md`](../docs/viewer.md).

```bash
uv run uvicorn api.main:app --port 8000          # API (repo root)
cd web && npm install --include=dev && npm run dev   # http://localhost:5173
```

The dev server proxies `/api` and `/health` to `VITE_API_TARGET`, else `http://api:8000` inside
Docker (`/.dockerenv`), else `http://localhost:8000`.

| script | what |
|---|---|
| `npm run dev` | Vite dev server (port 5173) |
| `npm run typecheck` | `tsc --noEmit` (strict) |
| `npm run build` | typecheck + production bundle in `dist/` |
| `npm run screenshot [-- m3-tierA ...]` | `docs/img/m3-*.png` via puppeteer-core and the installed Chrome (`TT_WEB_URL`, `CHROME_PATH`) |
| `npm run perf` | fps / heap / Chrome RSS JSON for Tier A city and Tier B (`TT_PERF_SECONDS`, `TT_PERF_UNCAPPED=1`) |

Layout: `src/engine.ts` (MapLibre + deck.gl + clock; everything per frame), `src/App.tsx` (panels
and data loading), `src/api.ts` (typed client, `edges.bin` parser), `src/binCache.ts` (LRU +
prefetch), `src/colors.ts` (LUT colour scales), `src/config.ts` (display constants), `src/url.ts`
(deep links), `src/components/`.

Results are labelled "synthetic demand, uncalibrated". Map data © OpenStreetMap contributors (ODbL).
