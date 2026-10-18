# Data sources: Track H (car vs Loop binary logit)

Checked 17 Oct 2026 by web search and fetch. "Verified" means the number was read in the primary
document or the publisher's own page; "secondary" means read on a third-party page only; "could not
verify" means no source gave it. No file below is stored in the repo: all are cited only (copyright
publications, or web pages with no open licence). Nothing here is calibrated to Jeddah; any model
built on it stays "synthetic demand, uncalibrated".

## 1. In-vehicle time (IVT) coefficient

- **Source (verified):** Cambridge Systematics et al. (2012), *NCHRP Report 716: Travel Demand
  Forecasting: Parameters and Techniques*, Transportation Research Board.
  https://nap.nationalacademies.org/catalog/14665 (full text read from the copy hosted by the
  Kentucky Transportation Cabinet: https://transportation.ky.gov/Planning/Documents/Travel%20Demand%20Forecasting.pdf).
  Copyright National Academies; cite only.
- **Values, Table 4.8 (home-based work, 9 US MPO models, per minute):** -0.021, -0.030, -0.036,
  -0.019, -0.025, -0.044, -0.028, -0.033, -0.025. Text: "range from -0.019 to -0.044". FTA New Starts
  guidance (FTA 2006, as quoted in NCHRP 716) asks for "compelling evidence" outside -0.020 to -0.030.
- **Table 4.11 (home-based non-work, 8 models):** -0.007 to -0.025. **Table 4.14 (non-home-based,
  11 models):** -0.006 to -0.035.
- **Saudi evidence (verified):** Youssef, Z., Alshuwaikhat, H., Reza, I. (2021), "Modeling the Modal
  Shift towards a More Sustainable Transport by Stated Preference in Riyadh, Saudi Arabia",
  *Sustainability* 13(1), 337, https://doi.org/10.3390/su13010337 (CC BY 4.0). Binary car-vs-Metro
  logit, stated preference, N = 716 to 720 observations from one neighbourhood (Al-Naseem), eq. 10-11:
  car travel time -0.022/min, Metro in-vehicle time -0.029/min.
- **Not verified:** the 2012 NCHRP 716 table for IVT is not called "4.16" (4.16 is car occupancy).
- **Recommendation:** central **-0.025 /min** (commute), range **-0.019 to -0.044**. For non-work
  trips use -0.015 (range -0.007 to -0.025). The Riyadh values (-0.022, -0.029) sit inside the range.

## 2. Out-of-vehicle time multipliers (wait, walk)

- **NCHRP 716 (verified, same document):** Table 4.9 (home-based work): OVT/IVT 1.5 to 2.5; walk/IVT
  2.6 to 3.1; first wait/IVT 1.2 to 4.7. Tables 4.29 and 4.30 (MPO transit path-building, regions of
  more than 1 million): walk/IVT mean 2.2 (min 1.5, max 3.0); wait/IVT mean 2.1 (1.5 to 2.6, peak).
  FTA asks for compelling evidence if OVT/IVT is outside 2.0 to 3.0.
- **Wardman, M. (2004), "Public transport values of time", *Transport Policy* 11(4), 363-377,
  https://doi.org/10.1016/j.tranpol.2004.05.001 (verified, White Rose eprint 3393).** Table 6, UK
  meta-analysis: walk 1.68 (urban 1.69; urban car users 1.55), wait 1.76 (urban commute 2.02; urban
  bus 1.59), in units of IVT.
- **Abrantes, P.A.L., Wardman, M. (2011), "Meta-analysis of UK values of travel time: An update",
  *Transportation Research Part A* 45(1), 1-17, https://doi.org/10.1016/j.tra.2010.08.003.**
  Verified from the abstract only: walk and wait ratios "substantially lower than the commonly used
  value of two"; GDP-per-capita elasticity of VOT = 0.9. **Could not verify** the exact multipliers
  (paywalled).
- **Wardman, M., Murphy, P., Ojeda-Cabral, M., Mitrani, A., Neki, K., Humphreys, R.M. (2026), "Value
  of time multipliers for walk time, wait time, service headway, displacement time, reliability and
  congested travel time: review and meta-analysis of worldwide evidence", *Transportation Research
  Part A* 207, 104925, https://doi.org/10.1016/j.tra.2026.104925 (verified, CC BY 4.0,
  White Rose eprint 239301).** 2,872 multipliers, 606 studies, 52 countries. Table 5 means: walk 1.67,
  wait 1.72, access/egress 1.70, OVT 1.87, parking search 1.60 (CI 1.41 to 1.79). Recommends 1.75 (RP
  emphasis) or 1.50 (SP emphasis) for walk and wait.
- **Hot climate (verified):** the 2026 meta-analysis tested whether walk multipliers are higher in
  countries "undisputably" high-temperature: "The incremental effect was not remotely significant."
  Against this, the Riyadh SP model (Youssef et al. 2021) gives walk -0.18/min vs Metro IVT -0.029/min,
  a walk/IVT ratio of **6.2** (our computation from eq. 11; the paper does not mention climate). Treat
  6.2 as an upper bound from one small SP sample, not a climate effect.
- **Recommendation:** wait **2.0x IVT** (range 1.5 to 2.5); walk **2.0x IVT** (range 1.5 to 3.0),
  with a high-heat sensitivity case at 3.0 (Riyadh SP suggests possibly higher). A Loop station
  access walk is the variable to sweep.

## 3. Value of time, Saudi Arabia (SAR/h)

- **Repo today:** A-pol-042 = SAR 40/h, range 20 to 60, "about half the mean Saudi hourly wage
  (convention)", status *assumed*. A-loop-011 reuses it and states "no published Saudi value of time".
- **Published Saudi VOT:** Alotaibi, O. (2017), *Potential demand for public transport in Riyadh
  City, Saudi Arabia*, PhD thesis, Cardiff University, https://orca.cardiff.ac.uk/id/eprint/106339.
  The abstract (via catalogue records) says it derives the first value-of-travel-time-savings
  estimates for Riyadh. **Could not verify the numbers** (repository returned 403; full text
  restricted).
- **Implied from Youssef et al. (2021) (our computation, verified inputs):** Metro 0.029/0.26 x 60 =
  **SAR 6.7/h**; car 0.022/0.6 (fuel cost) x 60 = **SAR 2.2/h**. Very low; SP fare range was SAR 5
  to 12 and fuel SAR 1 to 3, so treat as a lower bound, not a central value.
- **Wage base (verified, Argaam reporting GASTAT Labour Market Statistics Q2 2025,
  https://www.argaam.com/en/article/articledetail/id/1847820):** mean monthly wage Saudis SAR 11,034,
  expatriates SAR 3,933; 18.2M employed, 4.1M Saudi. At 173.3 h/month: Saudis SAR 63.7/h,
  expatriates SAR 22.7/h, employment-weighted SAR 31.9/h. (A Q4 2025 Saudi figure of SAR 11,103 was
  seen in a search summary only: secondary, not fetched.)
- **GDP base (verified, World Bank WDI via FRED PCAGDPSAA646NWDB):** 2025 GDP per capita US$34,537
  = SAR 129,500 (at 3.75), SAR 62/h over 2,080 h.
- **Convention (verified, not Saudi):** NCHRP 716 Table 4.9 implied HBW VOT US$1.58 to 9.43/h (model
  units, old price levels; not transferable as money). Abrantes & Wardman (2011): VOT income
  elasticity 0.9.
- **Recommendation:** keep SAR 40/h as a *Saudi-national commuter* value (63% of the hourly wage),
  but segment if the population carries nationality: Saudi **SAR 30 to 40/h**, expatriate **SAR 10 to
  15/h** (about 50% of wage). Single-value central **SAR 30/h**, range **SAR 7 to 64/h** (SP lower
  bound to full wage). Status stays *assumed*; cite wage + convention, not a Saudi VOT study.

## 4. Alternative-specific constant (new mode vs car)

- **NCHRP 716 (verified):** constants "are not considered transferable, and their values are
  determined during mode choice model calibration".
- **Ben-Akiva, M., Morikawa, T. (2002), "Comparing ridership attraction of rail and bus", *Transport
  Policy* 9(2), 107-116 (secondary: abstract as summarised by search of IDEAS/TRID; not fetched):** no rail preference once service
  attributes are equal; a rail bias is "not justified" vs high-quality express bus.
- **FTA STOPS (secondary: search summary of FTA "What's New in STOPS 1.50" and an NCDOT practitioner deck):** a fixed-guideway "visibility factor"
  scales mode-specific constants (0 to 1; BRT about 0.1 to 0.25 in practice). The commonly cited cap
  of 15 minutes of "non-included attribute" credit per trip appears only in a consultant document
  (Santa Ana); **could not verify** it in FTA text.
- **Riyadh SP (verified, Youssef 2021):** car ASC -3.47 plus age, income and car-ownership terms;
  at the sample means the net car-minus-Metro constant is about -1.17 utils (our computation), i.e.
  respondents *favoured* the hypothetical Metro. SP hypothetical bias; not usable as an RP constant.
  The paper cites the Riyadh Development Authority for "more than 92% of daily trips are made by
  private cars".
- **Gulf metro ASCs (Riyadh, Dubai, Doha RP models):** **could not verify** any published value.
  Dubai logit studies exist (UAEU, 2014, 430 respondents) but no constant was seen.
- **Loop-specific ASC:** none published. No Loop mode-choice study found.
- **Recommendation:** Loop ASC relative to car **-10 min IVT-equivalent** (= -0.25 utils at -0.025),
  range **-30 to 0 min**, swept as a scenario parameter; label *assumption*. Rationale: car share
  >90% and no transit habit argue for a penalty; Ben-Akiva & Morikawa argue against a positive
  "new guideway" bonus beyond measured attributes.

## 5. Fares

| Service | Fare | Source and status |
|---|---|---|
| Riyadh Metro + buses (Darb) | SAR 4 per 2-hour pass (unlimited rides); first class SAR 10; 3 days SAR 20; 7 days SAR 40; 30 days SAR 140 | Argaam, 28 Nov 2024, https://www.argaam.com/en/article/articledetail/id/1772486 (verified, news report); unchanged per Platinumlist 2026 guide (secondary) |
| Jeddah city bus (SAPTCO for Metro Jeddah Co.) | SAR 3.45 incl. VAT per ride, no free transfer | Jeddah Transport Company page https://www.jedtc.com.sa/page/Current_Bus_Service (seen in search summary; direct fetch blocked by a bot wall); Fodor's forum (undated). **Secondary; could not verify current.** SAPTCO page (https://saptco.com.sa/en/qr-jeddah-bus): 6 routes, 76 buses, 72 stations, no fare listed |
| Dubai Metro | nol Silver AED 3 / 5 / 7.5 (1 / 2 / >2 zones); Red ticket AED 4 / 6 / 8.5; Gold double | RTA nol Fares page https://www.rta.ae/wps/portal/rta/ae/public-transport/Nol-Fares (verified; page undated) |
| LVCC Loop (5 convention-centre stations + Fontainebleau) | Free | Las Vegas Advisor, 1 Jun 2026, https://www.lasvegasadvisor.com/question/vegas-loop-stations-fares/ (secondary; vegasloop.com fetched but showed no fares) |
| Vegas Loop paid stations (Resorts World, Encore, Westgate) | US$4.25 one way, US$7 round trip; airport extension US$12 (planned) | Same as above (secondary). Older reports: US$4.50 day pass (2024), US$1.50 single (2021-22) |

- **Recommendation:** Loop fare scenarios **SAR 0 / 4 / 10** (free like LVCC; Riyadh Metro parity;
  premium ~ US$2.7, below Vegas paid US$4.25 = SAR 16). Central **SAR 4**.

## 6. Car costs, parking search, ride-hail

- **Gasoline 91 (verified, Aramco retail fuels, "Prices for the month of October 2026",
  https://www.aramco.com/en/what-we-do/energy-products/retail-fuels):** SAR 2.18/L; 95 = SAR 2.33/L;
  diesel SAR 1.79/L.
- **Fuel consumption (secondary):** SASO / Saudi Energy Efficiency Center statements (2014 to 2020)
  give a fleet baseline of about 12 km/L; SASO page lists passenger cars 10.3 km/L. ICCT (2014) CAFE
  update: https://theicct.org/wp-content/uploads/2021/06/ICCTupdate_KSA-CAFE-proposal_20141218.pdf.
  **Could not verify** a current measured fleet average.
  Recommendation: **10 km/L** (range 8 to 14) -> fuel cost **SAR 0.22/km** (range 0.16 to 0.27).
- **Parking search (verified):** Shoup, D.C. (2006), "Cruising for parking", *Transport Policy*
  13(6), 479-486: 16 studies 1927-2001, average search 8.1 min (range 3.5 to 14), cruising share of
  congested downtown traffic 8 to 74% (mean 30%). Later evidence is lower: Shoup (2011) UCTC working
  paper, Manhattan Upper West Side 3.1 min (verified, RePEc abstract); German GPS study about 1.5 min,
  1 min 53 s in large-city cores (JTLU, secondary). Search-time multiplier 1.60x IVT (Wardman et al.
  2026, verified). **Jeddah: could not verify** any parking-search study.
  Recommendation: car egress penalty **3 min** search (range 0 to 8) weighted 1.6x IVT, applied only
  in dense zones (Al-Balad, Corniche, Tahlia); 0 elsewhere (assumption).
- **Ride-hail fares, Jeddah (verified, Uber Saudi blog, 19 Mar 2023, effective 20 Mar 2023,
  https://www.uber.com/en-SA/blog/changes-to-recommended-fares-on-uber-in-ksa-2023/):** UberX peak
  (Sun-Thu 07:00-19:00) base SAR 6.20 + 1.36/km + 0.43/min, minimum SAR 12; other hours 5.80 + 1.31/km
  + 0.38/min, minimum 12. "Recommended" fares; may be stale (2023). **Careem Jeddah: could not
  verify.** No TGA fare rule found.
- **Ride-hail pickup wait:** **could not verify** any Saudi figure. Literature model estimate 3 to 6 min
  pickup drive (arXiv 1902.01076, secondary); Dubai anecdotes 3 to 5 min.
  Recommendation: **5 min** (range 3 to 10), weighted as wait time (2.0x).

## Not stored, not used

Commercial traffic APIs (Google, TomTom, HERE) were not consulted. Downloaded PDFs were read in a
scratch directory outside the repo and are not committed.
