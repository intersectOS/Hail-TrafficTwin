## What changed

<!-- One paragraph; link the issue (Closes #...). -->

## How it was tested

<!-- Commands and numbers: `make test`, the demo command you ran, run ids, runtime. -->

- [ ] `uv run ruff check . && uv run ruff format --check . && uv run pytest -q` passes
- [ ] `cd web && npm run typecheck` passes (if `web/` changed)
- [ ] New CLI or module has a test on the demo window (`data/demo/`); no city-scale run in pytest

## Results and assumptions

- [ ] Outputs for an existing seed are unchanged, or the change is explained here
- [ ] New behavioural parameters live in YAML with `source:` or `assumption:` and have a row in `docs/assumptions.md` (ids: ...)
- [ ] Results stay labelled "synthetic demand, uncalibrated"

## Hygiene

- [ ] No secrets, `.env`, private or commercial data, imagery crops, or files under `data/` other than the allowed ones
- [ ] No real-city emergency, evacuation or motorcade plans (PROJECT.md section 11)
- [ ] `docs/STATUS.md` / `CHANGELOG.md` updated for user-visible changes
