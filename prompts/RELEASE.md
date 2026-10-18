# RELEASE - open-source release readiness (Track G, worktree .worktrees/trackG, branch trackG)

Branch `trackG` is cut from `main`. Status file: `docs/status/trackG.md`; finish with
`RELEASE: done` (or `RELEASE: blocked - reason`). Light compute only: no SUMO city runs, no film
renders beyond one smoke frame; another agent is running city simulations on this machine.

Goal: everything a maintainer needs to publish TrafficTwin on GitHub, WITHOUT creating or pushing
any remote (the owner publishes himself). Do not run `gh repo create`, `git push`, or anything
that leaves this machine.

1. **Licence and attribution audit.** Walk every dependency (pyproject, web/package.json) and
   every data source used (Geofabrik/OSM ODbL, GASTAT, Esri World Imagery crops kept local only,
   SUMO EPL-2.0, fonts, deck.gl/MapLibre) and confirm NOTICE and LICENSE are complete and correct;
   confirm no Esri crops, no private data, no secrets, no home paths, no machine-specific paths are
   tracked (`git ls-files` + grep). Fix what you find; record in `docs/release-audit.md`.
2. **CI.** GitHub Actions workflow that runs ruff, pytest and the web type-check/build on the demo
   window on ubuntu-latest (eclipse-sumo wheel; cache uv and npm); a second manual workflow for
   `make demo` smoke; both must pass in `act` or at least be validated with `actionlint`
   (install via brew if missing). Pin action versions.
3. **Repo hygiene.** README: clear "what it is" paragraph, hero GIF, 60-second quickstart,
   the 9 films table, a results section with the headline numbers and their caveats (synthetic,
   uncalibrated, 10 % sample, 50.5 % teleports in v1 network), hardware requirements, a
   "project status" section, and links to every doc. CONTRIBUTING, CODE_OF_CONDUCT, SECURITY.md,
   issue and PR templates, CITATION.cff, CHANGELOG with a v0.1.0 entry, `.github/FUNDING.yml`
   omitted. Make the git history publishable: no large binaries tracked (check `git count-objects`
   and the biggest blobs; if any tracked file is > 5 MB that should not be, say so in the status
   rather than rewriting history).
4. **Good first issues.** Write 10-15 well-scoped issues as markdown in `docs/issues/` (title,
   context, acceptance, pointers), drawn from the open items in docs/STATUS.md, docs/status/*.md
   and the "Still missing" list in docs/status/final.md (lane audit accuracy, 25 %/100 % runs, network
   capacity, induced demand, mode choice, Friday/Ramadan films, viewer comparison across network
   variants I-010, docker on Linux hash difference, etc.).
5. **Project page.** A static `site/` (plain HTML + CSS, no framework, no tracking, no external
   assets except Google Fonts if any) that works as GitHub Pages: hero with the showreel poster,
   the film gallery (GIF previews with links to the MP4 names), the Loop map and 3-line result,
   the policy results table, the architecture diagram, and the quickstart. Validate it renders
   headless (screenshot into docs/img/site.png).
6. **Release checklist** in `docs/release-checklist.md`: the exact commands the owner runs to
   create the GitHub repo, push, enable Pages and Actions, tag v0.1.0, attach the films to the
   release (sizes), and what to say in the announcement (draft a short LinkedIn post and a
   README badge row). Verifier subagent checks: no secrets/paths, CI lint passes, README commands
   work on the demo window, site renders. Then write the status line.
