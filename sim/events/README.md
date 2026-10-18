# sim/events

TraCI events for Tier B (microscopic) windows (M5). Each module has `resolve()` (main process,
sumolib: turns a scenario event into a JSON plan) and an `Event` subclass (worker, TraCI:
`on_start` / `on_step` / `on_end`, scheduled by simulation time). `EventContext` refuses Tier A.

- `accident.py`: closes N lanes (or all) of an edge and its `.s<k>` split parts; rubbernecking
  lowers the speed limit of the opposite carriageway (same nodes, or nearest anti-parallel edges
  on divided roads). Full closures reroute affected vehicles.
- `weather.py` + `weather.yaml`: rain presets (light, heavy, storm) scale speedFactor, accel,
  decel, minGap and tau of all vTypes and running vehicles, restored at the end.
- `flood.py`: storm preset + closure of flood sites (data/jeddah_flood_sites.yaml) inside the
  window, by OSM way id (origId) or radius.
- `motorcade.py`: convoy of `convoy` (vip) vehicles; rolling junction holds driven by the convoy's
  progress (lead time before, clear time after).
- `emergency.py`: emergency vehicle(s) A to B at T; free-flow reference from the network.
- `base.py`: context, closure manager (stacked lane permissions), weather manager, Event.
- `events.yaml`: behavioural defaults (register ids) and model settings.
