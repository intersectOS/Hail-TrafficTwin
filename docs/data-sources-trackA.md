# Data sources: Track A (M2 synthetic population and activity demand)

Compiled 16 Oct 2026 by data-scout. Feeds `sim/population/` YAML (`source:` / `assumption:` fields) and `docs/assumptions.md`.
Nothing here is stored in the repo; all values are quoted or derived from public pages. Derived values (marked "derived") were computed from the cited table, not quoted.
Commercial traffic data (Google, TomTom, HERE, Numbeo) was deliberately not used.

Confidence: **H** = official primary table or official release read directly; **M** = official figure via reputable secondary (press, GLMM re-publication) or a derivation from an H table; **L** = old, indirect or single non-official source; **A** = no source found, value is a proposed assumption.

## 1. Population structure

| Figure | Value | Source | Year | Conf. |
|---|---|---|---|---|
| Jeddah place (city) population | 3,712,917 | GASTAT census via https://citypopulation.de/en/saudiarabia/makkah/0202__jiddah/ | 2022 | H |
| Jeddah governorate population | 3,751,722 (governorate, wider than the place) | same | 2022 | H |
| KSA population, Saudi / non-Saudi | 18,792,262 / 13,382,962 / total 32,175,224 (58.4% Saudi) | GASTAT census table re-published by GLMM: https://gulfmigration.grc.net/saudi-arabia-population-by-nationality-saudis-non-saudis-sex-and-age-group-census-2022/ (official: https://portal.saudicensus.sa/portal/public/1/15?type=TABLE) | 2022 | H |
| Makkah region, Saudi / non-Saudi | "4,153,723 / 3,867,740 / 8,021,463" (51.8% Saudi, derived) | https://gulfmigration.grc.net/?p=9681 (GASTAT census) | 2022 | H |
| Jeddah Saudi / non-Saudi share | not found (governorate table lists regions only) | - | - | A: use Makkah region 52/48; plausible range 45-55% Saudi |
| Non-Saudi sex ratio, KSA | males 10,244,464, females 3,138,498 (77% male, derived) | GLMM census table above | 2022 | H |
| Age shares, KSA total: 0-5 / 6-17 / 18-24 / 25-59 / 60+ | 9.7 / 18.9 / 10.9 / 55.8 / 4.7 % | derived from 5-year bands in the GLMM census table (bands split linearly for 0-5, 6-17, 18-24) | 2022 | M |
| Age shares, Saudis | 14.0 / 26.7 / 13.1 / 40.6 / 5.6 % | derived, same table | 2022 | M |
| Age shares, non-Saudis | 3.8 / 7.9 / 7.7 / 77.2 / 3.4 % | derived, same table | 2022 | M |
| Age by Jeddah or Makkah region | not found | - | - | A: apply national Saudi/non-Saudi age profiles to the Jeddah nationality mix |

## 2. Households

| Figure | Value | Source | Year | Conf. |
|---|---|---|---|---|
| Saudi households, average size | "4.2 million, with an average size of 4.8 individuals per household" | GASTAT press conference via https://www.argaam.com/en/article/articledetail/id/1647819 and https://saudipedia.com/en/saudi-census-2022 | 2022 | M |
| Non-Saudi average household size | "2.7 individuals per household" | https://saudipedia.com/en/saudi-census-2022 | 2022 | M (wording ambiguous) |
| Makkah region / Jeddah household size | not found | - | - | A: Saudi 4.8, non-Saudi 2.7; range 4.5-5.5 / 2.0-3.5. Many non-Saudi males live in single-person or shared labour housing: model as 1-4 person "group" households |

## 3. Labour force and employment by sector

| Figure | Value | Source | Year | Conf. |
|---|---|---|---|---|
| LFPR total (Saudi + non-Saudi), unemployment | "67.1%", "3.2%" | GASTAT LMS Q2 2025, https://stats.gov.sa/en/w/news/93 (released 30 Sep 2025) | Q2 2025 | H |
| LFPR Saudis, unemployment | "49.2%", "6.8%" | same | Q2 2025 | H |
| Saudi males LFPR / unemployment | "64.0%" / "4.3%" | same | Q2 2025 | H |
| Saudi females LFPR / unemployment | "34.5%" / "11.3%" | same | Q2 2025 | H |
| Non-Saudi unemployment | "1.4%" | https://www.argaam.com/en/article/articledetail/id/1846443 | Q2 2025 | M |
| Newer release | Saudi LFPR 49.0%, unemployment 7.5% | https://www.stats.gov.sa/documents/d/guest/lms-q3_2025-en-pdf | Q3 2025 | H |
| Employed (GOSI register, excl. civil service, military, domestic workers) | 11,706,763 (Saudis 2,772,420) | GASTAT register LMS via https://gulfmigration.grc.net/saudi-arabia-employed-population-aged-15-and-above-by-nationality-saudi-non-saudi-sex-and-main-group-of-economic-activities-q2-2024/ | Q2 2024 | H |
| Sector shares of that register (KSA) | construction 24.7; wholesale/retail 14.1; manufacturing 11.5; admin/support 10.0; other 9.2; accommodation/food 5.8; transport/storage 4.8; health 3.8; public admin (GOSI only) 2.4; education (GOSI only) 1.6 % | derived from the table above (e.g. construction 2,894,564; retail 1,648,970; transport 566,981; health 448,912) | Q2 2024 | M |
| Civil-service (government) employees | "1,183,261", of which education cadre "460,901"; non-Saudis 3.27% | MHRSD report via https://www.okaz.com.sa/economy/saudi/2210747 | mid-2025 | M |
| Makkah region / Jeddah sector mix | not found | - | - | A: national mix, then upweight transport/logistics (port) and hospitality, downweight mining; distribute jobs by OSM land use |

Modelling note: GOSI register + civil service ≈ 12.9M workers (derived); government ≈ 9%, of which ~39% teachers. Military/security excluded from both: assumption needed (range 3-6% of workers).

## 4. Students

| Figure | Value | Source | Year | Conf. |
|---|---|---|---|---|
| General-education students | "6.72 million"; primary ~3.27M, intermediate ~1.57M, secondary ~1.46M; ~36,800 schools | MoE via https://www.argaam.com/en/article/articledetail/id/1762550 (21 Oct 2024) | 2024/25 | M |
| Tertiary gross enrolment ratio | 83.88% (UNESCO UIS) | https://www.okaz.com.sa/local/na/2241852 ; https://measuredworld.com/countries/saudi-arabia/education/enrollment | 2024 | M |
| School enrolment of 6-17 | not quoted directly | - | - | A: 6.72M / ~6.1M aged 6-17 nationally (derived) implies ~100%; use 95-98% for Saudis, 85-95% non-Saudis; 18-24 in tertiary 35-45% (GER counts the 5-year cohort, not all 18-24) |

## 5. Vehicles and drivers

| Figure | Value | Source | Year | Conf. |
|---|---|---|---|---|
| Insured vehicles, KSA | 11.0M (2025), 7.0M (2021) | Insurance Authority, Saudi Insurance Market Report 2025 (ia.gov.sa) | 2025 | M (proxy for the active fleet; URL to confirm) |
| New registrations | "1,000,201 new vehicles" registered in 2024 | https://eletric-vehicles.com/ford/saudi-arabia-breaks-record-with-1-million-vehicles-registered-in-2024/ | 2024 | L |
| Jeddah fleet composition | "64 percent of Jeddah's cars are privately owned, while taxis account for 8 percent" | https://www.arabnews.com/news/534591 (4 Mar 2014) | 2014 | L |
| Vehicles per household / per 1,000, Jeddah | not found | - | - | A: 11.0M / 32.2M ≈ 340 per 1,000 nationally (derived, includes commercial); Saudi households 1.5-2.5 cars; non-Saudi labour households 0-0.3 |
| Women with driving licences | "174,624 driving licenses had been issued to women" by 20 Jan 2020; Riyadh, Makkah, Eastern = 90% | GASTAT via https://www.arabnews.pk/node/1638686 | 2020 | L (stale) |
| Women ride-hail drivers | 14.7k → 21.8k | TGA annual report via https://www.argaam.com/en/article/articledetail/id/1819544 | 2024 | M |
| Share of women who drive (2024+) | not found | - | - | A: 20-35% of adult Saudi women have car access as driver; sweep it |

## 6. Trip rates, mode shares, commute

| Figure | Value | Source | Year | Conf. |
|---|---|---|---|---|
| Jeddah daily trips | "6 million trips made daily in Jeddah" | Jeddah Metro Co. DG via https://www.arabnews.com/news/534591 | 2014 | L |
| Jeddah trips per person per day | ≈1.7 (6M / ~3.4-3.6M residents, derived) | derived from the above | 2014 | L |
| Jeddah public transport share | "only accounts for 1.2 percent of total daily traffic movement" | same | 2014 | L |
| Jeddah PT share history | 19% (1970) to 2.3% (2007) | Aljoufie, WIT Trans. Built Env. 138, https://www.witpress.com/elibrary/wit-transactions-on-the-built-environment/138/26130 | 2007 | M |
| Riyadh mode share | "car mode commuters constitute 85% of trips"; ~2% bus, of ~8M daily trips | https://doi.org/10.3390/su13010337 ; https://www.preprints.org/manuscript/202306.0352 | 2021-23 | L (survey not named) |
| Riyadh/Jeddah household travel survey (ADA/RCRC) | not found publicly | - | - | A: 2.0-2.8 trips/person/day for Saudis, 1.2-1.8 for non-Saudi workers; car 80-88%, ride-hail/taxi 5-10%, bus 1-3%, walk 3-8% |
| Jeddah average commute time | no official figure; 2007 GulfTalent survey "46 minutes" per day (professionals) | https://www.gulftalent.com/press/dubai-most-congested-city-in-middle-east-study-46 | 2007 | L |
| | | | | A: one-way commute 20-35 min, 10-20 km |

## 7. Working and school hours

| Figure | Value | Source | Year | Conf. |
|---|---|---|---|---|
| Government hours 07:30-14:30 | not verified; only a 2020 COVID-era notice of flexible starts "(7:30am - 8:30am - 9:30am)" | https://gulfnews.com/world/gulf/saudi/all-public-sector-employees-in-saudi-arabia-to-return-to-office-from-august-30-1.1598152034888 | 2020 | A: start 07:30-09:30, 7 h day, end 14:30-16:30 |
| Government Ramadan hours | 10:00-15:00 (five hours) | HRSD via https://www.bayt.com/en/blog/31628/ramadan-2025-working-hours-in-ksa/ (circular not found) | 2025 | M |
| Private sector limits | 8 h/day or 48 h/week (Labour Law Art. 98) | https://www.qoyod.com/en/learn/working-hours-weekly-rest-saudi-labor-law/ | current | M |
| Private sector Ramadan | 6 h/day or 36 h/week for Muslim workers | MHRSD via https://english.ajel.sa/news/saudi-arabia/mhrsd-announces-ramadan-working-hours-for-private-sector | 2022 | M |
| School start, Riyadh (summer timing) | "morning assembly will begin at 6:15am, with the first class starting promptly at 6:30am" | https://gulfnews.com/world/gulf/saudi/saudi-arabia-introduces-daylight-saving-time-in-schools-starting-sunday-1.500083180 | Apr 2025 | M |
| School start, Riyadh winter / Ramadan | assembly 6:45, first class 7:00; Ramadan first lesson 9:00 | Riyadh directorate via Ajel (english.ajel.sa) | 2025-26 | L |
| School start, Makkah/Jeddah directorate | not found (set per directorate) | - | - | A: assembly 06:30-06:45, end 12:30-13:30; Ramadan 09:00-13:00 |
| Academic year 2025/26 | start 24 Aug 2025; two-semester system | https://www.schoolvoice.com/blog/saudi-arabia-returns-to-two-semester-school-system-starting-1447-ah-2025-2026 | 2025 | M |

## 8. Ride-hail and bus

| Figure | Value | Source | Year | Conf. |
|---|---|---|---|---|
| Ride-hail trips, KSA | "80.5 million trips" (2023: 63.9M) | TGA annual report via https://www.argaam.com/en/article/articledetail/id/1819544 | 2024 | M |
| Ride-hail trips, Makkah region | "19.5 million trips, or 24% of the total" (≈53,500/day, derived) | same | 2024 | M |
| Ride-hail share of Jeddah trips | not found | - | - | A: if Jeddah ≈ 60-70% of Makkah-region rides, ≈32-37k/day vs ~6-7M daily trips → ≈0.5-1% of trips (plus street taxis) |
| Jeddah city-bus passengers | 995,000 (Q2 2025); 1.19 million (Q4 2025) ≈ 11-13k/day (derived) | TGA via https://saudiauto.com.sa/en/public-transport-surge-2025/ and https://saudiauto.com.sa/en/transport-stats-bus-users/ | 2025 | M |
| Jeddah bus network | 14 routes, 80 stops, 117 stations (46 built, 71 under construction); forecast "9 million passengers annually" | https://www.arabnews.com/node/2599998/saudi-arabia | 2025 | M (forecast, not ridership) |

## 9. Umrah / KAIA

| Figure | Value | Source | Year | Conf. |
|---|---|---|---|---|
| KAIA annual passengers | "over 49.1 million passengers in 2024" (≈134k/day, derived), 278,000+ flights | https://economymiddleeast.com/news/king-abdulaziz-international-airport-hits-record-49-million-passengers-in-2024-highest-in-saudi-airports-history | 2024 | M |
| KAIA pre-Ramadan + Ramadan peak | "over 5.4 million passengers on 30,572 flights" 11 Feb-20 Mar 2024 (≈139k/day, derived; arr+dep) | https://arab.news/r6r6a | 2024 | M |
| Umrah performers, KSA | 35.68M total; ~16.80M from abroad (47%), 18.88M domestic | GASTAT via https://www.argaam.com/en/article/articledetail/id/1799151 | 2024 | M |
| Umrah arrivals via KAIA specifically | not found | - | - | A: 50-65% of foreign Umrah by air via KAIA; umrah_season day = +15-30% KAIA flows and Makkah-highway coaches |

## Licence and storage notes
- GASTAT tables: public statistics, re-published by GLMM (Gulf Research Center) with attribution; GASTAT open-data terms to be confirmed before committing any CSV to `data/census/`. Only the derived age-share and nationality figures above are needed; keep them in YAML with `source:` URLs instead of storing tables.
- Press articles (Argaam, Arab News, Gulf News, Okaz, Saudi Auto): cite only, do not store.
- Every "A" row must enter `docs/assumptions.md` and be exposed in the sweep tool; label all outputs "synthetic demand, uncalibrated".
