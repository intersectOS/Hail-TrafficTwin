#!/usr/bin/env bash
# Hail city pipeline driven by .github/sim-request.yml (used by the `simulate` workflow; also runs
# locally once data/hail/hail.v2.net.xml and data/osm/hail.osm.pbf exist).
#   zones -> baseline(s) -> policies -> window demand hour -> tier link -> Tier B scenarios,
#   strategist, evacuations. Every step logs to logs/sim-<step>.log. Synthetic demand, uncalibrated.
set -euo pipefail
REQ=${1:-.github/sim-request.yml}
mkdir -p logs runs
q() { uv run python -c "import yaml,json,sys; d=yaml.safe_load(open('$REQ')); v=d.get('$1'); print(' '.join(map(str,v)) if isinstance(v,list) else ('' if v is None else v))"; }
SAMPLE=$(q sample); SEED=$(q seed); DAYTYPES=$(q daytypes); POLICIES=$(q policies)
WINDOWS=$(q windows); HOUR=($(q demand_hour)); SCENARIOS=$(q scenarios)
STRATEGIST=$(q strategist); EVACS=$(q evacuations)
step() { local name=$1; shift; echo "::group::$name"; local t0=$SECONDS
  if "$@" > "logs/sim-$name.log" 2>&1; then echo "ok $name $((SECONDS-t0)) s" | tee -a logs/sim-summary.txt
  else echo "FAILED $name $((SECONDS-t0)) s" | tee -a logs/sim-summary.txt; tail -40 "logs/sim-$name.log"; echo "::endgroup::"; return 1; fi
  tail -5 "logs/sim-$name.log"; echo "::endgroup::"; }

echo "request: sample=$SAMPLE seed=$SEED daytypes=[$DAYTYPES] policies=[$POLICIES] windows=[$WINDOWS] scenarios=[$SCENARIOS]" | tee logs/sim-summary.txt
step zones uv run python -m sim.population.zones
for d in $DAYTYPES; do
  step "baseline-$d" uv run python -m sim.runner --baseline --daytype "$d" --sample "$SAMPLE" --seed "$SEED" --gzip
done
for p in $POLICIES; do
  step "policy-$p" uv run python -m sim.runner --policy "$p" --daytype weekday --sample "$SAMPLE" --seed "$SEED" || true
done

if [ -n "$WINDOWS" ]; then
  BASE=$(ls -dt runs/baseline-weekday-* 2>/dev/null | head -1)
  test -n "$BASE" || { echo "no weekday baseline run"; exit 1; }
  SRC=runs/hail-source-hour
  step window-demand uv run python -m scripts.hail.window_demand "$BASE/routes.rou.xml.gz" \
    --begin "${HOUR[0]}" --end "${HOUR[1]}" --out "$SRC/routes.rou.xml"
  step tier-a uv run python -m sim.link tier-a --routes "$SRC/routes.rou.xml" --out runs/tierA-exit-hour --seed "$SEED"
  for w in $WINDOWS; do
    step "link-window-$w" uv run python -m sim.link window --name "$w"
    step "link-cut-$w" uv run python -m sim.link cut --window "$w" --tier-a runs/tierA-exit-hour
    step "link-tls-$w" uv run python -m sim.link tls --window "$w" || true
  done
fi
for s in $SCENARIOS; do step "scenario-$s" uv run python -m sim.runner --scenario "$s" --seed "$SEED" || true; done
for s in $STRATEGIST; do step "strategist-$s" uv run python -m strategist.run --scenario "$s" --seed "$SEED" || true; done
for s in $EVACS; do step "evac-$s" uv run python -m sim.runner --scenario "$s" --seed "$SEED" || true; done
echo "done" | tee -a logs/sim-summary.txt
