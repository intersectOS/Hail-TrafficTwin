# sim/policies

Policy lab (PROJECT.md section 7, M4). A policy is a YAML file (`kind: policy`, validated by
`sim.schemas.Policy`; `python -m sim.validate sim/policies/*.yaml`) whose transforms edit the
population's plans or the network before a Tier A run. Full description: `docs/policies.md`.

| file | what |
|---|---|
| `*.yaml` | demo policies (remote work, staggered schools, Friday, Ramadan, Tahlia bus line, central cordon, Corniche closure, Ramadan + remote work, ride-hail) |
| `config/policy_run.yaml` | run settings (re-routing, report windows, sweep workers) |
| `transforms.py` | `Plan` and the transforms (tour-level edits of trips and vehicles) |
| `ptline.py`, `netedit.py` | bus line via `ptlines2flows.py`; network variants via netconvert |
| `routes.py` | route-file streaming, routing weights, one-shot re-routing, route merge |
| `run.py` | `run_policy`: baselines, transforms, incremental routing, meso run, KPIs |
| `report.py` | `policy_report.json` / `.md` |
| `sweep.py` | parameter grid in parallel processes -> response curve CSV + PNG |
| `summary.py` | markdown results table from several runs |
| `edges.py` | cached edge table (names, coordinates) of a network |

```
uv run python -m sim.runner --policy remote_work_30 --daytype weekday --sample 0.10 --seed 1
uv run python -m sim.policies.sweep --policy remote_work --param share=0.1:0.5:0.1 --sample 0.10
```
