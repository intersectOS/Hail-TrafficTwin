# Films for the Friday and Ramadan day types

Labels: `films`, `good first issue`

## Context
The policy-lab film shows remote work, staggered schools and the cordon. The two day types with
the most striking results have no film: Friday (no morning peak, Jumu'ah peak at 11:00) and the
Ramadan weekday (flat morning, pre-iftar rush, late-night traffic).

## Acceptance
- `movies/specs/friday.yaml` and `movies/specs/ramadan.yaml` that validate with the spec schema,
  using existing runs (`friday`, `ramadan_weekday`) against the weekday baseline.
- Smoke render passes (`make movie FILM=friday MOVIE_FLAGS=...` at low resolution), GIF preview
  under 3 MB in `docs/img/movies/`, row added to the README films table.
- HUD labels "synthetic demand, uncalibrated".

## Pointers
`docs/movies.md` (spec schema and camera cookbook), `movies/specs/policy-lab.yaml`,
`scripts/movies/`, `movies/specs/order.yaml`.
