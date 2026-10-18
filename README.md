# التوأم الرقمي لمرور حائل · TrafficTwin Hail

**المنصة:** https://intersectos.github.io/Hail-TrafficTwin/ · **المنصة التفاعلية:** https://intersectos.github.io/Hail-TrafficTwin/viewer/

نموذج محاكاة مفتوح المصدر لشبكة طرق مدينة حائل كاملة، يحاكي يوماً مرورياً من 24 ساعة لسكان حائل
(448,623 نسمة في تعداد 2022)، ثم يختبر عليه القرارات قبل تنفيذها: جريان وادي الأديرع، توسعة طريق الملك
عبدالعزيز، خط حافلات، رسوم دخول المركز، العمل عن بعد، تدريج دوام المدارس، والحوادث والسيول والمواكب،
ومستشار طوارئ يرتّب خيارات وصول الإسعاف ليعتمدها المسؤول، ومحاكاة الإخلاء.

> كل النتائج على **طلب مروري مُركّب غير مُعايَر**: لا توجد بعد عدّادات مرور حقيقية من حائل في النموذج،
> فالأرقام مقارنات بين سيناريوهات وليست توقعات. أداة دعم قرار ومحاكاة فقط، لا تتحكم بأي بنية تحتية حقيقية.

## ما الذي فيه

| الجزء | حائل |
|---|---|
| الشبكة | OpenStreetMap (مستخرج 2026-10-17): 47,360 مقطع طريق، 18,608 تقاطع، 9,149 كم-مسار، 85 حياً |
| الإشارات | 209 إشارة عند تقاطعات المحاور الرئيسية (قاعدة A-net-303؛ الخريطة المفتوحة تعرف 22 فقط) |
| السكان | تعداد 2022: 448,623 نسمة، 70.7٪ سعوديون (منطقة حائل)، أسر ووظائف ومدارس وجامعة حائل |
| اليوم | يوم عمل، جمعة، سبت، يوم رمضان، يوم من موسم الشتاء (الرالي والمهرجانات)؛ أوقات صلاة حائل الفعلية |
| السياسات | `wadi_adiri_flowing`، `widen_king_abdulaziz`، `bus_line_king_abdulaziz`، `cordon_center`، `remote_work_30`، `staggered_schools_60`، وغيرها في `sim/policies/` |
| النوافذ | وسط حائل (برزان وطريق الملك عبدالعزيز والمستشفيات)، والمدينة الرياضية |
| الطوارئ | حادث، أمطار، سيل الأديرع، موكب، إسعاف إلى مستشفى الملك خالد، إخلاء الملعب، إخلاء ضفة الوادي |

## ما ينقصه ليصبح توقعاً

1. عدّادات حركة المرور على الطرق الرئيسية (مسار المعايرة `sim/calibrate.py` جاهز).
2. قائمة الإشارات المرورية وأزمنتها من الأمانة.
3. عدد المسارات على المحاور الرئيسية.
4. مسح أصل الرحلة ووجهتها، ولو كان صغيراً ومجهّل الهوية.

---

## English

An open-source traffic digital twin of **Hail, Saudi Arabia**: a 24-hour city simulation on the real
OpenStreetMap road network with demand from a synthetic population of Hail's 448,623 residents
(GASTAT Census 2022), a policy lab, Tier B incident windows, an emergency strategist and evacuation
runs. Everything runs on Eclipse SUMO, Python, FastAPI and a React + deck.gl viewer, from public data
only. All results are **synthetic demand, uncalibrated**.

### How it runs

Map data cannot be downloaded from every machine, so the heavy steps run on GitHub Actions:

| workflow | what it does | output |
|---|---|---|
| `fetch-osm` | downloads the Geofabrik GCC extract and clips the Hail study area (`data/osm/hail-clip.poly`) | branch `osm-data` |
| `build-network` | builds networks v1 and v2 (`data/osm/hail.poly`), lane defaults measured on the Hail clip, arterial signals, districts and buildings, and the Tier B windows | branch `build` |
| `simulate` | runs `.github/sim-request.yml`: zones, 24 h baseline, policies, the 08:00-09:00 window demand, tier link, scenarios, strategist, evacuations (`scripts/hail/simulate.sh`) | branch `results` (reports, logs), artifact `hail-runs` |
| `publish` | ingests the runs, exports the viewer API as static files (`scripts/hail/export_static.py`), builds the project page and the static viewer | branch `gh-pages` (GitHub Pages) |

To change what is simulated, edit `.github/sim-request.yml` and push.

Locally (macOS or Linux with uv, Node 22+, osmium-tool):

```bash
git clone https://github.com/intersectOS/Hail-TrafficTwin.git && cd Hail-TrafficTwin
uv sync && (cd web && npm ci --include=dev)
# networks: copy them from the build branch, or build them (needs data/osm/hail-clip.osm.pbf from osm-data)
uv run python -m sim.demo                      # demo-window runs (central Hail, a few minutes)
uv run python -m api.ingest --all && ./run_app.sh   # viewer on http://localhost:5173
uv run pytest -q                               # tests on the committed demo window
```

### What changed from the Jeddah original

- Study area, windows (`center`, `sports_city`, `demo`), flood sites (`data/hail_flood_sites.yaml`: Wadi Al-Adiri crossings and the OSM underpasses) and all scenarios are Hail's.
- Population control total, nationality split, sectors, airport volumes and prayer-time location are Hail's; the Umrah day type became Hail's winter season.
- Network v2 measures its lane and speed defaults on the Hail clip and adds signals at arterial crossings (A-net-303).
- Window demand comes from the behavioural 24 h baseline (08:00-09:00), expanded back to full volumes, instead of random trips (`scripts/hail/window_demand.py`).
- The viewer can be built as a static site (`VITE_STATIC=1`) and is read-only there.
- Jeddah-only modules (Obhur bridges, Loop tunnels) were removed. The Jeddah documentation under `docs/` describes the method and the original measurements; Hail numbers are in the `results` branch and on the project page.

### Licence

Code: Apache-2.0 (`LICENSE`). Based on [TrafficTwin](https://github.com/alturkestani/TrafficTwin) (Apache-2.0); see `NOTICE`.
Map data (c) OpenStreetMap contributors, ODbL. SUMO is EPL-2.0. GASTAT open data with attribution.

---

تم تطوير هذه المنصة بواسطة سليمان الخطيب 0559965929 · This platform has been developed by Sulaiman Alkhateeb 0559965929
