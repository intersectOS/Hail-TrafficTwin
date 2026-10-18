# Data sources: Track D (Loop tunnels)

All Track D results: synthetic demand, uncalibrated.

Date accessed for every web source below: 2026-10-16. "Verified" means the figure was read on the cited page that day. "Not verified" means no primary or reliable secondary source was found; do not use it as a fact. Commercial traffic APIs (Google, TomTom, HERE) were not used.

Commit status: this file holds only facts and coordinates with attribution. No third-party tables are stored. Coordinates come from OpenStreetMap (ODbL, attribution already in `NOTICE`), so they may be committed.

## A. Loop system facts

### A1. Dubai Loop (RTA and The Boring Company)

| Item | Value | Source URL | Note / verified? |
|---|---|---|---|
| Agreement | RTA signed with The Boring Company on 3 Feb 2026 at the World Governments Summit | https://mediaoffice.ae/en/news/2026/february/03-02/rta-signs-agreement-with-the-boring-company-to-commence-implementation-of-dubai-loop | Verified (Dubai Media Office, official) |
| Pilot length / stations | 6.4 km, 4 stations, DIFC to Dubai Mall | same | Verified: "a 6.4km pilot route, comprising four stations" |
| Pilot cost | about AED 565 M | same | Verified: "estimated at approximately AED 565 million" |
| Full system | 22.2 km, 19 stations | same | Verified: "will extend up to 22.2 km", "19 stations" |
| Full system cost | about AED 2 B | same | Verified: "approximately AED 2 billion" |
| Tunnel diameter | 3.6 m | same | Verified: "tunnels with a diameter of 3.6 metres" |
| Timeline | Pilot about 1 year after design; full route about 3 years | same | Verified |
| Daily capacity (2026 release) | Pilot about 13,000 pax/day; full route about 30,000 pax/day | same | Verified. The release gives daily figures only, not hourly |
| Speed "up to 100 mph" | about 160 km/h top speed claimed | https://www.dezeen.com/2025/02/18/dubai-loop-elon-musk-the-boring-company-tunnel/ | Company claim from the Feb 2025 MoU coverage; not in the 2026 RTA release. Treat it as a claim, not an operating speed |
| Hourly capacity (2025 claim) | over 20,000 pax/h for the earlier 17 km, 11-station pilot; over 100,000 pax/h for the full emirate system | https://blooloop.com/technology/news/elon-musk-boring-company-dubai-loop-tunnels/ | 2025 MoU claims. The 17 km / 11-station pilot was replaced by the 6.4 km / 4-station pilot in 2026. Not verified for the current scope |

### A2. Vegas Loop / LVCC Loop

| Item | Value | Source URL | Note / verified? |
|---|---|---|---|
| Operating speed | 35 mph (56 km/h) in the infobox and history; "not more than 30 mph (48 km/h)" in the Reception section | https://en.wikipedia.org/wiki/Las_Vegas_Convention_Center_Loop | 35 mph per Wikipedia. The 30 mph figure is tagged [citation needed], so not verified. Suggest 35 mph (15.6 m/s) as `assumption:` |
| Measured peak (2021) | 1,355 pax/h, highest hour up to mid-July 2021 | https://techcrunch.com/2021/11/12/early-data-from-elon-musks-las-vegas-loop-shows-a-slower-yet-popular-service/ | Verified. The figure comes from TechCrunch's review of LVCVA/Clark County trip reports. No Clark County report was found online, so cite TechCrunch |
| Test / contract capacity | about 4,400 pax/h in a pre-opening test; 2019 contract penalty if about 4,000 pax/h is not met at large conventions | same; Wikipedia page above | Verified (press and Wikipedia) |
| Operator claim (current) | "over 4,500 passengers per hour", "over 32,000 passengers per day" demonstrated peak | https://www.boringcompany.com/lvcc | Operator claim, not independently verified |
| Full build-out claim | "more than 90,000 passengers per hour" | https://en.wikipedia.org/wiki/Las_Vegas_Convention_Center_Loop | Company claim; Wikipedia notes critics call it inflated |
| Vehicles / drivers | Tesla Model Y (earlier Model 3), driven by employees | same | Verified (Wikipedia) |
| Occupancy | max 4 passengers per car | same | Verified (Wikipedia). The car has 5 seats; use 4 for capacity |
| Typical wait | 10 to 15 min | same | Tagged [citation needed]: not verified |
| LVCC Loop cost | $53 M (Wikipedia, uncited); 2019 contract $48.7 M; operator says "approximately $47 million (firm-fixed price)" | same; https://www.boringcompany.com/lvcc | $47 M (operator) and $48.7 M (contract) are better supported than $53 M |
| LVCC Loop length | 1.7 mi original tunnel (2.7 km); 2.1 mi and 5 stations after the 2024 expansion (operator); Wikipedia infobox says 2.2 mi | https://www.boringcompany.com/lvcc | Verified as operator figures; the Wikipedia infobox and body disagree |
| Trip time | about 2 min end to end (replaces a 45-min walk) | https://www.boringcompany.com/lvcc | Operator claim |

### A3. Music City Loop (Nashville)

| Item | Value | Source URL | Note / verified? |
|---|---|---|---|
| Cost | "at least $240 million" (reported range $240-300 M, privately funded) | https://tennesseelookout.com/2025/09/30/nashvilles-airport-transit-tunnel-could-cost-boring-at-least-240-million/ | Headline verified (30 Sep 2025). The page returned HTTP 403, so the body was not read |
| Length | about 10 mi (16 km), downtown to BNA airport; route table 8.5-9.5 mi | https://en.wikipedia.org/wiki/Music_City_Loop | Verified (citing Tennessean / WKRN / governor's release, 28 Jul 2025). "About 13 miles": not verified. One outlet (Nashville Scene) mentions 19 miles of twin one-way tunnels |

### A4. Vehicle

| Item | Value | Source URL | Note / verified? |
|---|---|---|---|
| Tesla Model Y length | 4.751 m (2020-2024); 4.790 m (2025 refresh) | https://www.tesla.com/ownersmanual/2020_2024_modely/fr_be/GUID-E47C4A6D-528E-419C-8C57-FD3864644C34.html ; https://vehiclescore.co.uk/car-dimensions-check/tesla/model-y | Verified. Width 1.921 m without mirrors. Suggest `length="4.79"` for a vType |

## B. Jeddah anchor coordinates (WGS84, lon, lat)

Source: OpenStreetMap, from the local Geofabrik GCC extract `data/osm/gcc-states-latest.osm.pbf` (data timestamp 2026-10-14) plus Nominatim lookups. For polygons the coordinate is the vertex mean, about the same as the centroid. Licence: ODbL.

| Item | Value (lon, lat) | Source | Note / verified? |
|---|---|---|---|
| KAIA Terminal 1 building (centroid) | 39.1711, 21.6673 | OSM relation 20056128 "صالة 1 / Terminal 1" (aeroway=terminal) | Verified OSM feature |
| KAIA Terminal 1 landside forecourt (curbside) | 39.1734, 21.6655 | OSM one-way service roads along the concave east (landside) face of relation 20056128 | Derived from OSM geometry, not checked on imagery. The curbside runs about 39.1720-39.1776, 21.6625-21.6727 |
| Haramain HSR station, KAIA Airport | 39.1745, 21.6588 | OSM way 550729660 (railway=station) | Verified OSM feature; about 0.9 km SE of the forecourt point |
| Al Balad centre | 39.1877, 21.4860 | OSM place node 13426472192 "البلد / Al-Balad" (relation 20039250 gives the same) | Verified OSM. Bait Naseef (node 2520141053) is at 39.1877, 21.4840 |
| Nearest Corniche point to Al Balad | 39.1807, 21.4884 | Nearest vertex of OSM "طريق الكورنيش" (way 41426966) | Derived; about 0.78 km WNW of the Al Balad node. The Corniche Center mall (node 1096434773) is at 39.1825, 21.4861 |
| Tahlia St (Prince Mohammed bin Abdulaziz St) x Al Andalus Rd | 39.1293, 21.5470 | Closest vertices of the OSM Tahlia ways and the Al Andalus Road way (primary), 15 m apart | Derived; no shared node (dual carriageway). The Al Andalus district place node is at 39.1332, 21.5417 |
| King Abdulaziz University main campus | 39.2489, 21.4964 | OSM node 556022181 "King Abdulaziz University" | Verified OSM. The campus polygon (way 1072356349) centroid is 39.2485, 21.4934 |
| Red Sea Mall | 39.1113, 21.6278 | OSM way 111645517 | Verified OSM (Nominatim) |
| Mall of Arabia | 39.1561, 21.6327 | OSM way 44213515 "مول العرب" | Verified OSM (Nominatim) |
| Jeddah Corniche Circuit (North Corniche) | 39.1061, 21.6277 (southern part); 39.1018, 21.6491 (northern part) | OSM ways 1359884761 and 1007989410 | Verified OSM (Nominatim); the circuit is linear, so these are reference points |
| Haramain HSR Jeddah (Al Sulaymaniyah) station | 39.2454, 21.5176 | OSM way 485762503 (railway=station, building=train_station) | Verified OSM |
| King Abdullah Sports City (stadium) | 39.1643, 21.7632 | OSM way 292395768 (leisure=stadium); way 504162355 sports centre | Verified OSM |

## C. Economic constants

| Item | Value | Source URL | Note / verified? |
|---|---|---|---|
| USD/SAR | 3.75 SAR per USD (official peg) | https://sama.gov.sa/en-US/News/Pages/news-557.aspx | Verified (SAMA): "maintaining the exchange rate at the official rate of 3.75 riyals to the dollar"; peg since 1986 (Wikipedia, Saudi riyal) |
| Saudi value of travel time | none found | n/a | Not verified: no published Saudi VOTT study was found in a quick search. Fallback: register it as an `assumption:` in YAML, e.g. a share of the average wage from GASTAT Labour Force Survey earnings (commonly 50% of the wage rate for commuting in appraisal guides), and run sensitivity bands. Label it as an assumption in `docs/assumptions.md` |
