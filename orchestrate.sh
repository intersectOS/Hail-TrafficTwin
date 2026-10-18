#!/bin/zsh
# Overnight build: three parallel tracks in git worktrees, then integration, then the final clean-clone check.
# Run as:  caffeinate -dimsu ./orchestrate.sh        (keeps the Mac awake; keep it plugged in, lid open)
set -u
setopt null_glob
cd "$(dirname "$0")"; ROOT=$PWD
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
mkdir -p logs/orch .worktrees docs/status
LOG=$ROOT/logs/orch
note(){ echo "$(date '+%F %T') $*" | tee -a "$LOG/orchestrator.log"; }

setup_wt(){ # track
  local t=$1 wt=$ROOT/.worktrees/$1
  if [[ ! -d $wt ]]; then
    git -C "$ROOT" show-ref --quiet "refs/heads/$t" || git -C "$ROOT" branch "$t" main
    git -C "$ROOT" worktree add "$wt" "$t" >> "$LOG/orchestrator.log" 2>&1 || { note "worktree $t failed"; return 1; }
  fi
  mkdir -p "$wt/data/osm" "$wt/logs" "$wt/runs" "$wt/docs/status"
  [[ -e $wt/data/jeddah ]] || ln -s "$ROOT/data/jeddah" "$wt/data/jeddah"
  for f in "$ROOT"/data/osm/*.pbf "$ROOT"/data/osm/*.gz "$ROOT"/data/osm/*.xml; do
    [[ -e $f && ! -e $wt/data/osm/$(basename "$f") ]] && ln -s "$f" "$wt/data/osm/"
  done
  (cd "$wt" && uv sync -q >> "$LOG/orchestrator.log" 2>&1) || note "uv sync in $t reported an error (continuing)"
  note "worktree $t ready"
}

run_prompt(){ # dir track label promptfile
  local dir=$1 track=$2 label=$3 pf=$4 tries=0 rc body out
  while (( tries < 4 )); do
    tries=$((tries+1))
    if (( tries == 1 )); then body="$(cat "$ROOT/prompts/_common.md"; echo; cat "$pf")"
    else body="$(cat "$ROOT/prompts/_common.md"; echo; sed "s/M<n>/$label/g; s/<track>/$track/g" "$ROOT/prompts/_resume.md"; echo; cat "$pf")"; fi
    out="$LOG/$track-$label-try$tries.jsonl"
    note "$track $label try $tries start"
    (cd "$dir" && claude -p "$body" --dangerously-skip-permissions --verbose --output-format stream-json < /dev/null > "$out" 2>&1)
    rc=$?
    note "$track $label try $tries end rc=$rc"
    if grep -qE "^${label}: done" "$dir/docs/status/$track.md" 2>/dev/null; then note "$track $label DONE"; return 0; fi
    if grep -qE "^${label}: blocked" "$dir/docs/status/$track.md" 2>/dev/null; then note "$track $label BLOCKED"; return 2; fi
    if grep -qiE "rate.?limit|overloaded|usage limit|429" "$out"; then note "$track $label looks rate-limited; sleeping 15 min"; sleep 900; else sleep 60; fi
  done
  note "$track $label FAILED after $tries tries"; return 1
}

run_track(){ # track labels...
  local track=$1; shift
  local dir=$ROOT/.worktrees/$track rc
  for label in "$@"; do
    run_prompt "$dir" "$track" "$label" "$ROOT/prompts/$label.md"; rc=$?
    (( rc == 0 )) || { note "$track stops at $label (rc=$rc)"; break; }
  done
  note "$track finished"
}

note "=== orchestrator start ==="
setup_wt trackA; setup_wt trackB; setup_wt trackC
run_track trackA M2 M4 M8 &  pA=$!
run_track trackB M5 M6 M7 &  pB=$!
run_track trackC LANE_AUDIT M3 &  pC=$!
wait $pA; wait $pB; wait $pC
note "=== all tracks finished; integrating ==="
run_prompt "$ROOT" integration INTEGRATE "$ROOT/prompts/INTEGRATE.md"
note "=== final clean-clone check ==="
run_prompt "$ROOT" final FINAL "$ROOT/prompts/FINAL.md"
note "=== orchestrator end ==="
