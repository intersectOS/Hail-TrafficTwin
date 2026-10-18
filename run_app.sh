#!/usr/bin/env bash
# Start the TrafficTwin API (FastAPI, uvicorn) and viewer (Vite) over runs/ and open the browser.
# `make demo` runs this after producing the demo runs; on its own it only serves what is in runs/.
#
#   ./run_app.sh             foreground; Ctrl-C stops both
#   ./run_app.sh --detach    leave both running in the background (stop with `make stop`)
#
# Env: TT_API_PORT (8000), TT_WEB_PORT (5173), TT_NO_OPEN=1 (do not open a browser).
# Logs: logs/api.log, logs/web.log; process ids in logs/app.pids.
set -euo pipefail
cd "$(dirname "$0")"

API_PORT="${TT_API_PORT:-8000}"
WEB_PORT="${TT_WEB_PORT:-5173}"
DETACH=0
[[ "${1:-}" == "--detach" ]] && DETACH=1
mkdir -p logs

busy() { lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1; }
for p in "$API_PORT" "$WEB_PORT"; do
  if busy "$p"; then
    echo "port $p is already in use (stop the other server, run 'make stop', or set TT_API_PORT / TT_WEB_PORT)" >&2
    exit 1
  fi
done
if [[ ! -x web/node_modules/.bin/vite || ! -x .venv/bin/python ]]; then
  echo "dependencies missing: run 'make setup' first" >&2
  exit 1
fi

# exec, so the recorded pids are the servers themselves (stopping them stops everything)
(TT_CORS_ORIGINS="http://localhost:${WEB_PORT}" \
  exec .venv/bin/python -m uvicorn api.main:app --port "$API_PORT") >logs/api.log 2>&1 &
API_PID=$!
(cd web && VITE_API_TARGET="http://localhost:${API_PORT}" \
  exec ./node_modules/.bin/vite --port "$WEB_PORT" --strictPort) >logs/web.log 2>&1 &
WEB_PID=$!
echo "$API_PID $WEB_PID" >logs/app.pids

stop() { kill "$API_PID" "$WEB_PID" 2>/dev/null || true; rm -f logs/app.pids; }
if [[ $DETACH -eq 0 ]]; then trap stop INT TERM EXIT; fi

wait_for() {  # url, name, pid
  for _ in $(seq 1 120); do
    if curl -fsS "$1" >/dev/null 2>&1; then return 0; fi
    if ! kill -0 "$3" 2>/dev/null; then echo "$2 exited; see logs/$2.log" >&2; tail -20 "logs/$2.log" >&2; exit 1; fi
    sleep 1
  done
  echo "$2 did not answer at $1 within 120 s; see logs/$2.log" >&2
  exit 1
}
wait_for "http://localhost:${API_PORT}/health" api "$API_PID"
wait_for "http://localhost:${WEB_PORT}/" web "$WEB_PID"
wait_for "http://localhost:${WEB_PORT}/api/runs" web "$WEB_PID"

URL="http://localhost:${WEB_PORT}"
echo "TrafficTwin viewer: $URL   (API http://localhost:${API_PORT}/docs)   [synthetic demand, uncalibrated]"
if [[ "${TT_NO_OPEN:-0}" != "1" ]] && command -v open >/dev/null 2>&1; then open "$URL"; fi

if [[ $DETACH -eq 1 ]]; then
  echo "running in the background (pids $API_PID $WEB_PID); stop with 'make stop'"
  exit 0
fi
echo "Ctrl-C to stop"
wait "$API_PID" "$WEB_PID"
