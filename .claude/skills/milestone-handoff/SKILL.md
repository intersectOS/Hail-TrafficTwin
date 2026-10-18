---
name: milestone-handoff
description: End-of-milestone procedure: run tests and the README demo command, invoke the verifier subagent, update docs/STATUS.md with measured numbers and decisions, commit, and write the handoff summary. Use at the end of every milestone and before stopping a session.
---
# Milestone handoff

1. `uv run ruff check . && uv run ruff format --check . && uv run pytest -q` must pass.
2. Run the milestone's README demo command exactly as written in the README; fix the README if it differs from reality.
3. Ask the `verifier` subagent to check the milestone. Fix every FAIL, then re-run the verifier. Do not declare done with an open FAIL.
4. Update `docs/STATUS.md` (create from the template below if missing). Numbers must be measured in this session, not estimated.
5. Commit: `git add -A && git commit -m "feat(<area>): complete M<n> <title>"`. Check `git status` is clean and no data or secrets are tracked.
6. End the session with the handoff summary (also appended to STATUS.md):

```
## M<n> <title> — <date>
Built: ...
Measured: network edges/junctions/TLS, runtime, teleports, population size, test count ...
Decisions: ...
Could not verify: ...
Next: M<n+1> <title> — first three tasks
```

STATUS.md template:
```
# TrafficTwin Jeddah — status
Last updated: <date>
Environment: <python, sumo version and install path, osmium, node>
## Milestones
| M | Title | State | Evidence |
## Measured
## Decisions
## Open issues
## Handoffs
```
