# Release checklist: publish TrafficTwin Jeddah v0.1.0 on GitHub

For the owner. Nothing here has been run: no remote exists, nothing was pushed. Commands assume
macOS with `gh` (logged in: `gh auth status`), `git-filter-repo` (`brew install git-filter-repo`)
and the integrated `main` branch (Track G merged). Replace `OWNER` with the GitHub user or
organisation once, in the shell:

```bash
export OWNER=your-github-handle REPO=TrafficTwin
export SRC=~/Documents/Projects/TrafficTwin      # the working checkout (stays untouched)
export PUB=~/Documents/Projects/TrafficTwin-publish
```

## 0. Pre-flight on the working checkout

```bash
cd "$SRC" && git status --short          # clean
uv run ruff check . && uv run ruff format --check . && uv run pytest -q
(cd web && npm run typecheck && npm run build)
actionlint .github/workflows/*.yml
```

## 1. Make a publishable history (required)

The history contains 12 Esri World Imagery crops (`docs/img/lane-audit/*.jpg`, added in 403d2af,
removed in 0bf3c0d) that must not be redistributed (`docs/release-audit.md`, section 3). Rewrite a
**fresh clone**, never the working checkout:

```bash
rm -rf "$PUB" && git clone --no-local --branch main "$SRC" "$PUB" && cd "$PUB"
git filter-repo --force --invert-paths --path docs/img/lane-audit/
# optional, same pass: publish commits under your GitHub no-reply address instead of the company e-mail
#   printf 'Your Name <ID+%s@users.noreply.github.com> <COMMIT_EMAIL>\n' "$OWNER" > /tmp/mailmap   # COMMIT_EMAIL: git log -1 --format=%ae
#   git filter-repo --force --mailmap /tmp/mailmap
git log --all --name-only --format= | grep -c 'docs/img/lane-audit/'   # must print 0
git rev-list --objects --all | git cat-file --batch-check='%(objecttype) %(objectsize) %(rest)' \
  | awk '$1=="blob" && $2>5000000' | wc -l                              # must print 0
git count-objects -vH | grep size-pack                                 # about 31 MiB
```

Rehearsed on a throwaway clone of `main` on 2026-10-17: 0 crop paths left, 31 MiB.
Only `main` is published; the `track*` branches and `.worktrees/` stay local.

## 2. Fill the placeholders

```bash
cd "$PUB"
grep -rln 'OWNER/TrafficTwin' README.md CONTRIBUTING.md CITATION.cff \
  | xargs sed -i '' "s#OWNER/TrafficTwin#$OWNER/$REPO#g"
sed -i '' 's#CONDUCT_CONTACT#your-conduct-address@example.org#' CODE_OF_CONDUCT.md   # pick the address
grep -rn 'OWNER\|CONDUCT_CONTACT' --include='*.md' --include='*.cff' . | grep -v docs/release-checklist.md   # nothing left
# CITATION.cff: confirm the author list and set date-released to the tag date
git commit -am "docs(release): repository URLs and conduct contact for v0.1.0"
```
`site/index.html` keeps `__REPO__`; the Pages workflow fills it from `github.repository`.

## 3. Create the repository and push

```bash
cd "$PUB"
gh repo create "$OWNER/$REPO" --public \
  --description "Open-source traffic digital twin of Jeddah: policy lab, events and emergency strategist on Eclipse SUMO + OpenStreetMap (synthetic demand, uncalibrated)" \
  --homepage "https://$OWNER.github.io/$REPO/"
git remote add origin "https://github.com/$OWNER/$REPO.git"
git push -u origin main
gh repo edit "$OWNER/$REPO" --add-topic traffic-simulation,digital-twin,sumo,openstreetmap,jeddah,saudi-arabia,transport-policy,deckgl,fastapi
```

## 4. Enable Actions, Pages and private vulnerability reporting

Actions are on by default for a new public repository; the `ci` workflow starts on the push.

```bash
gh api -X POST "repos/$OWNER/$REPO/pages" -f build_type=workflow           # Pages from GitHub Actions
gh api -X PUT  "repos/$OWNER/$REPO/private-vulnerability-reporting"        # SECURITY.md relies on it
gh workflow run pages.yml -R "$OWNER/$REPO"                                 # first deploy
gh workflow run demo-smoke.yml -R "$OWNER/$REPO" -f city=0                  # optional: make demo on Linux
gh run list -R "$OWNER/$REPO" --limit 5                                    # ci, pages, demo-smoke green
```
Then open `https://$OWNER.github.io/$REPO/` and check the hero, the GIFs and the table.
Optional: Settings > Branches, protect `main` and require the `ci` checks.

## 5. Tag v0.1.0 and attach the films

The MP4s are not in git; they live in the working checkout's `movies/` (rebuild with `make movies`
and, for the Arabic edition, `make movies-ar` if missing). Both editions are release assets: the
English `<film>.mp4` for English speakers and the Arabic `<film>.ar.mp4` (Arabic voice-over and
subtitles, docs/movies-arabic.md) for Arabic speakers. The site and README link to
`releases/download/v0.1.0/<film>.mp4`, so the asset names must stay as below. Sizes as rendered on
2026-10-17 (English: pass 7 / Track I; Arabic: pass 8); every file is under GitHub's 2 GiB asset
limit, 1352.6 MB in all.

| film | English asset | size | Arabic asset | size |
|---|---|---|---|---|
| `city-24h` | `city-24h.mp4` | 93.2 MB | `city-24h.ar.mp4` | 107.9 MB |
| `tahlia-street` | `tahlia-street.mp4` | 25.9 MB | `tahlia-street.ar.mp4` | 26.5 MB |
| `incident` | `incident.mp4` | 40.4 MB | `incident.ar.mp4` | 46.1 MB |
| `events` | `events.mp4` | 44.6 MB | `events.ar.mp4` | 50.1 MB |
| `strategist` | `strategist.mp4` | 35.0 MB | `strategist.ar.mp4` | 40.1 MB |
| `evacuation` | `evacuation.mp4` | 34.6 MB | `evacuation.ar.mp4` | 37.5 MB |
| `policy-lab` | `policy-lab.mp4` | 51.9 MB | `policy-lab.ar.mp4` | 57.0 MB |
| `loop` | `loop.mp4` | 93.7 MB | `loop.ar.mp4` | 104.5 MB |
| `obhur-bridge` | `obhur-bridge.mp4` | 35.9 MB | `obhur-bridge.ar.mp4` | 37.7 MB |
| `showreel` | `showreel.mp4` | 195.5 MB | `showreel.ar.mp4` | 194.5 MB |
| **total** | | **650.7 MB** | | **701.9 MB** |

```bash
cd "$PUB"
git tag -a v0.1.0 -m "TrafficTwin Jeddah v0.1.0: first public release (synthetic demand, uncalibrated)"
git push origin v0.1.0
awk '/^## \[0.1.0\]/{f=1;next} /^## \[/{f=0} f' CHANGELOG.md > /tmp/tt-notes.md
gh release create v0.1.0 -R "$OWNER/$REPO" --title "TrafficTwin Jeddah v0.1.0" --notes-file /tmp/tt-notes.md \
  "$SRC"/movies/{city-24h,tahlia-street,incident,events,strategist,evacuation,policy-lab,loop,obhur-bridge,showreel}{,.ar}.mp4
gh release view v0.1.0 -R "$OWNER/$REPO" --json assets --jq '.assets[] | "\(.name) \(.size)"'
```

## 6. Open the good first issues

```bash
cd "$PUB"
for l in network realism performance population modelling policies films viewer api determinism data "good first issue" "help wanted"; do
  gh label create "$l" -R "$OWNER/$REPO" --force >/dev/null; done
for f in docs/issues/[0-9]*.md; do
  title=$(head -1 "$f" | sed 's/^# //')
  labels=$(grep -m1 '^Labels:' "$f" | sed 's/^Labels: //; s/`//g; s/, /,/g')
  gh issue create -R "$OWNER/$REPO" --title "$title" --label "$labels" --body-file "$f"
done
```

## 7. Announce

### README badge row (already at the top of README.md once `OWNER` is filled)

```markdown
[![ci](https://github.com/OWNER/TrafficTwin/actions/workflows/ci.yml/badge.svg)](https://github.com/OWNER/TrafficTwin/actions/workflows/ci.yml)
[![licence: Apache-2.0](https://img.shields.io/badge/licence-Apache--2.0-blue)](LICENSE)
[![python 3.12](https://img.shields.io/badge/python-3.12-blue)](pyproject.toml)
[![Eclipse SUMO 1.28](https://img.shields.io/badge/Eclipse%20SUMO-1.28-green)](https://eclipse.dev/sumo/)
[![data: synthetic, uncalibrated](https://img.shields.io/badge/data-synthetic%2C%20uncalibrated-orange)](docs/assumptions.md)
```

### LinkedIn post (draft; attach the showreel MP4 or the `city-24h` GIF)

> I've open-sourced **TrafficTwin Jeddah**: a traffic digital twin of the whole city, built on
> Eclipse SUMO and OpenStreetMap.
>
> It simulates a full 24-hour day for every road in Jeddah, with demand from a synthetic
> population (homes, jobs, schools, prayer times) instead of random trips. Then it asks policy
> questions:
> • 30 % remote work: about 9 % less delay and 7 % less CO2
> • Staggering school start times by an hour: about 9 % less morning-peak delay
> • A Loop tunnel from Al-Salamah to King Abdulaziz University: tens of thousands of
>   vehicle-hours saved per day, under measured (not vendor) capacity
>
> It also injects crashes, rain, floods and motorcades into street-level windows, and an
> emergency strategist ranks ambulance routes and evacuation plans for a human to approve.
>
> An honest caveat: the demand is synthetic and uncalibrated, and missing lane counts in
> OpenStreetMap still choke the network, so read the numbers as comparisons, not forecasts.
> That's exactly where help is welcome: lane counts, real counts, mode choice. Good first issues
> are open.
>
> Code (Apache-2.0), films and docs: https://github.com/OWNER/TrafficTwin
> Project page: https://OWNER.github.io/TrafficTwin
>
> #Jeddah #DigitalTwin #OpenSource #TrafficSimulation #SmartCities #SaudiArabia

Arabic version (optional, for a second post or the first comment):

> أطلقتُ مشروع **TrafficTwin Jeddah** مفتوح المصدر: توأم رقمي لحركة المرور في جدة كاملةً، مبني
> على Eclipse SUMO وبيانات OpenStreetMap. يحاكي يوماً كاملاً على كل طرق المدينة انطلاقاً من سكان
> افتراضيين (السكن والعمل والمدارس وأوقات الصلاة)، ويختبر سياسات مثل العمل عن بُعد وتغيير أوقات
> الدوام المدرسي وأنفاق Loop، ويرتّب خيارات الاستجابة للطوارئ ليعتمدها الإنسان.
> تنبيه: البيانات افتراضية وغير معايَرة، فالأرقام للمقارنة لا للتنبؤ. المساهمات مرحّب بها.
> https://github.com/OWNER/TrafficTwin

Numbers in the post come from `docs/policies.md` (remote_work_30: mean delay -9.3 %, CO2 -6.9 %;
staggered_schools_60: AM-peak delay -9.1 % against its matched control) and `docs/loop.md`
(63,349 VHT/day two-seed mean, band 23,435 to 103,263). Keep the caveat paragraph.

## 8. After publishing

- Check the README renders (badges, GIFs, links) and that `docs/img/site.png` matches the live page.
- Watch the first `ci` run; if the runner image changes, the apt list in `ci.yml` is the place to fix.
- Delete `$PUB` only after the push is verified; keep working in `$SRC` and push from a clone that
  has the filtered history (the rewritten commit ids differ from `$SRC`). Simplest: after
  publishing, re-clone from GitHub and continue there.
