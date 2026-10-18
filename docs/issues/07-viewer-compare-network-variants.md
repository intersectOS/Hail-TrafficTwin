# Viewer: compare runs across network variants (I-010)

Labels: `viewer`, `api`

## Context
The viewer only compares runs that share a network hash. Loop runs use a tunnel variant network,
so they show no baseline comparison in the viewer, although the films already compare by edge id
(I-010 in `docs/STATUS.md`).

## Acceptance
- The API returns difference bins for two runs on different networks by matching edge ids, and
  reports how many edges exist only in one of them.
- The viewer allows such a comparison, draws variant-only edges (tunnels) distinctly, and states
  that the networks differ.
- API test on two demo runs with a modified network.

## Pointers
`api/bins.py`, `api/routers/runs.py`, `api/routers/networks.py`, `web/src/`,
`docs/contracts/run-outputs.md`, `docs/viewer.md`.
