# Security policy

TrafficTwin Jeddah is a simulation and decision-support tool. It never actuates real
infrastructure, and the API is meant to run on localhost (`./run_app.sh`, `docker compose`); it
has no authentication and should not be exposed to the internet as is.

## Supported versions

| version | supported |
|---|---|
| 0.1.x (`main`) | yes |
| older | no |

## Reporting a vulnerability

Please **do not open a public issue**. Report it privately through GitHub: the repository's
**Security** tab, **Report a vulnerability** (private vulnerability reporting). Include the
affected version or commit, steps to reproduce, and the impact you expect.

We aim to acknowledge reports within 7 days and to agree a fix and disclosure date with you. Valid
reports are credited in `CHANGELOG.md` unless you prefer otherwise.

## Scope

In scope: the Python packages (`sim/`, `strategist/`, `api/`), the viewer (`web/`), the Docker and
CI configuration, and anything that could leak data or execute code (for example path traversal
in the run-file API, unsafe YAML loading, or command injection through SUMO tool calls).

Out of scope: the accuracy of simulation results (they are synthetic and uncalibrated by design;
open a normal issue), and vulnerabilities in dependencies that are already public (please still
tell us if we pin an affected version).

## Sensitive scenarios

Real-city emergency, evacuation and motorcade plans (specific routes, timings, critical sites) are
not published in this repository (`PROJECT.md` section 11). If you find such material in the repo
or its history, report it through the same private channel.
