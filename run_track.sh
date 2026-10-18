#!/bin/zsh
# Run one track's milestones sequentially in its worktree: ./run_track.sh trackC M3 LANE_AUDIT_V2
set -u; setopt null_glob
cd "$(dirname "$0")"; ROOT=$PWD
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
LOG=$ROOT/logs/orch; mkdir -p "$LOG"
note(){ echo "$(date '+%F %T') $*" | tee -a "$LOG/orchestrator.log"; }
run_prompt(){ local dir=$1 track=$2 label=$3 pf=$4 tries=0 rc body out
  while (( tries < 4 )); do tries=$((tries+1))
    if (( tries == 1 )) && ! grep -qE "^${label}:" "$dir/docs/status/$track.md" 2>/dev/null; then body="$(cat "$ROOT/prompts/_common.md"; echo; cat "$pf")"
    else body="$(cat "$ROOT/prompts/_common.md"; echo; sed "s/M<n>/$label/g; s/<track>/$track/g" "$ROOT/prompts/_resume.md"; echo; cat "$pf")"; fi
    out="$LOG/$track-$label-x$tries.jsonl"; note "$track $label (extra) try $tries start"
    (cd "$dir" && claude -p "$body" --dangerously-skip-permissions --verbose --output-format stream-json < /dev/null > "$out" 2>&1); rc=$?
    note "$track $label (extra) try $tries end rc=$rc"
    grep -qE "^${label}: done" "$dir/docs/status/$track.md" 2>/dev/null && { note "$track $label DONE"; return 0; }
    grep -qE "^${label}: blocked" "$dir/docs/status/$track.md" 2>/dev/null && { note "$track $label BLOCKED"; return 2; }
    if grep -qiE "rate.?limit|overloaded|usage limit|429" "$out"; then note "rate-limited; sleeping 15 min"; sleep 900; else sleep 60; fi
  done; note "$track $label FAILED"; return 1; }
track=$1; shift
for label in "$@"; do run_prompt "$ROOT/.worktrees/$track" "$track" "$label" "$ROOT/prompts/$label.md" || note "$track $label did not finish (continuing with next label)"; done
note "$track (extra) finished"
