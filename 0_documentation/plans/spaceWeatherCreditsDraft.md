# Space weather: draft credits to add

Status: draft, 24 Oct 2026. Nothing has been added to the site. The live credits are in `C:\Users\User\DEV\LCARS-FAS\assets\acknowledgments.html`, in three tables: **CREDITS** (Name, Contribution, URL; alphabetical by name), **DATA SRCES** (Source, What it provides, Licence type, Refreshed, URL) and **METHOD**. Wording is taken from the licences and citation requests Scotty and Spock found; items marked **[verify]** were not read from the source's own page and should be checked before publishing. Terms are stated as the sources give them.

## 1. What the page has today, and the gaps

Present: CelesTrak, Space-Track, GCAT, SatNOGS, NASA ("DONKI space-weather event data"), geojs.io and others. The NASA row and the DONKI row describe DONKI as "geomagnetic storm events" only; they need widening. Missing entirely: NOAA SWPC (the largest source of the new section), GFZ Potsdam, CODE (Bern), Oulu, SILSO, the NASA/ESA solar imagery already shown on SUN NOW, the World Data Center Kyoto (Dst), the Newell coupling function, and DB-IP (a pending credit from the visit counter).

## 2. New rows for the CREDITS table (Name, Contribution, URL)

In alphabetical position among the existing names.

| Name | Contribution | URL |
|---|---|---|
| Astronomical Institute, University of Bern (CODE) | Global ionosphere maps of total electron content, observed (rapid) and predicted 1 to 5 days ahead. Dach, R., S. Schaer, D. Arnold, E. Brockmann, M. Kalarus, C. Kobel, M. Lasser, P. Stebler, A. Jaeggi (2026). CODE rapid product series for the IGS. Astronomical Institute, University of Bern. DOI 10.48620/97772. **[verify]** which series the predictions belong to; the ultra-rapid series has DOI 10.48620/97774. | aiub.unibe.ch/download/CODE |
| ESA and NASA SOHO | Coronagraph images (LASCO) of coronal mass ejections, shown on SUN NOW | sohowww.nascom.nasa.gov |
| GFZ Helmholtz Centre for Geosciences, Potsdam | The official geomagnetic indices Kp, ap, Ap, Hp30 and Hp60 (Geomagnetic Observatory Niemegk), with observed and adjusted F10.7 and the international sunspot number. Matzka, J., Stolle, C., Yamazaki, Y., Bronkalla, O. and Morschhauser, A. (2021). The geomagnetic Kp index and derived indices of geomagnetic activity. Space Weather, doi:10.1029/2020SW002641. CC BY 4.0. | kp.gfz.de |
| NASA (Solar Dynamics Observatory) | Images of the Sun (AIA and HMI instruments) shown on SUN NOW; credit "NASA/SDO and the AIA / HMI science teams" | sdo.gsfc.nasa.gov |
| NASA Community Coordinated Modeling Center | DONKI: the database of coronal mass ejections, flares, solar energetic particle events, high-speed streams and geomagnetic storms (replaces the current "NASA" row; see section 3) | ccmc.gsfc.nasa.gov/donki |
| NOAA Space Weather Prediction Center | Real-time solar wind and magnetic field from the L1 spacecraft; GOES X-ray and proton fluxes; the NOAA space weather scales; Kp estimates and forecasts; the 3-day forecast and 27-day outlook; F10.7 radio flux; the OVATION Prime auroral model; D-RAP absorption maps; GloTEC total electron content; and the solar images on SUN NOW. US Government work (public domain); credit requested. | swpc.noaa.gov |
| P. T. Newell and colleagues | The solar wind and magnetosphere coupling function used for the driving indicator. Newell, P. T., T. Sotirelis, K. Liou, C.-I. Meng and F. J. Rich (2007). A nearly universal solar wind-magnetosphere coupling function inferred from 10 magnetospheric state variables. J. Geophys. Res., 112, A01206, doi:10.1029/2006JA012015. **[verify]** the citation details. | doi.org/10.1029/2006JA012015 |
| Oulu cosmic ray station, Sodankyla Geophysical Observatory, University of Oulu | Neutron monitor count rates (Oulu, and the Antarctic Dome C station served from the same site) for the galactic cosmic ray view. The operators ask users to acknowledge their website and the Sodankyla Geophysical Observatory. Research, educational and public non-commercial use. **[verify]** the operators of the Dome C stations. | cosmicrays.oulu.fi |
| SILSO, Royal Observatory of Belgium | The international sunspot number (monthly record since 1749): "WDC-SILSO, Royal Observatory of Belgium, Brussels", CC BY-NC 4.0, DOI 10.24414/qnza-ac80 **[verify]** | sidc.be/SILSO |
| World Data Center for Geomagnetism, Kyoto | The Dst index of the ring current (real-time quick-look values, supplied through NOAA SWPC and revised later by Kyoto) **[verify]** the credit form | wdc.kugi.kyoto-u.ac.jp |
| DB-IP | IP geolocation data (IP to City Lite, CC BY 4.0) used to count visits by city. Required credit: "IP Geolocation by DB-IP". Not space weather; the visit counter's pending credit. | db-ip.com |

The existing Don Cross row (Astronomy Engine) should add that it also computes darkness and the Moon for the AURORAE view. No new row.

## 3. Changes to existing rows

| Row | Change |
|---|---|
| CREDITS: NASA | Replace "DONKI space-weather event data" by a pointer to the new CCMC row, or widen it to "DONKI (flares, coronal mass ejections, solar energetic particles, high-speed streams and geomagnetic storms) via NASA CCMC". |
| DATA SRCES: NASA DONKI | Widen "Geomagnetic storm events" to all six event types; refreshed hourly (last 7 days) rather than "on request"; add the 90-day history. |

## 4. New rows for the DATA SRCES table (Source, What it provides, Licence type, Refreshed, URL)

| Source | What it provides | Licence type | Refreshed | URL |
|---|---|---|---|---|
| NOAA SWPC, solar wind and particles | L1 magnetic field and plasma (1-minute), GOES X-ray flux and flares, GOES proton flux, radio flux and events, hemispheric power | US Government work (public domain), credit NOAA SWPC | Every 15 minutes (fast feeds) and hourly | swpc.noaa.gov |
| NOAA SWPC, indices and forecasts | Kp (observed, estimated, predicted), Dst (quick-look), F10.7, the NOAA space weather scales, the 3-day forecast, the 27-day outlook and the 45-day forecast | US Government work (public domain) | Every 15 minutes and hourly | swpc.noaa.gov |
| NOAA SWPC, OVATION Prime | Global map of auroral energy flux (both hemispheres) with its forecast time | US Government work (public domain) | Hourly | swpc.noaa.gov |
| NOAA SWPC, D-RAP | Global map of HF radio absorption (highest affected frequency) | US Government work (public domain) | Hourly | swpc.noaa.gov |
| NOAA SWPC, GloTEC | Global total electron content map with anomaly and F2-layer peak, 7 days kept | US Government work (public domain) **[verify]** on SWPC's own site | Every 3 hours, and on request | swpc.noaa.gov |
| GFZ Potsdam | Kp, ap, Ap, Hp30, Hp60, F10.7 and sunspot number (definitive after weeks to months, nowcast until then) | CC BY 4.0 (sunspot numbers CC BY-NC 4.0) | Hourly; 400 days kept | kp.gfz.de |
| NASA CCMC DONKI | Coronal mass ejections, flares, solar energetic particle events, high-speed streams, interplanetary shocks and geomagnetic storms | US Government work (public domain) | Hourly (last 7 days); 90-day history | ccmc.gsfc.nasa.gov/donki |
| CODE global ionosphere maps | Total electron content, observed (previous day) and 1, 2 and 5-day predictions | Citation requested; no licence text found **[verify]** | Daily | aiub.unibe.ch/download/CODE |
| Oulu neutron monitors | Cosmic ray count rates (Oulu; Antarctic Dome C), pressure-corrected; monthly record since 1964 | Research, educational and public non-commercial use, with acknowledgement | Hourly | cosmicrays.oulu.fi |
| SILSO | Monthly international sunspot number since 1749 | CC BY-NC 4.0 | Monthly | sidc.be/SILSO |
| SUN NOW images | Live pictures of the Sun from NASA SDO and ESA/NASA SOHO, fetched by the visitor's browser from NASA and NOAA each time the page is opened (nothing stored) | US Government and ESA/NASA imagery, credited beneath each image | On request (cached for 30 minutes) | sdo.gsfc.nasa.gov |
| DB-IP | IP to city lookup for the visit counter (no address stored) | CC BY 4.0 | Static (rebuilt occasionally) | db-ip.com |

## 5. METHOD page additions

- **Space weather pipeline:** one sentence: the space weather data are fetched by scheduled scripts into their own databases and published into a single site file; the 1-minute solar wind and X-ray series are kept for 90 days.
- **Derived quantities:** the Newell coupling function and the simple driving product are computed by FAS from the stored L1 data; the oval's equatorward edge is derived by FAS from the OVATION map. The tooltip on each chart carries the formula.
- **Models:** OVATION, D-RAP, GloTEC and the CODE predictions are model output, not observations, and are labelled as such.

## 6. Per-chart credit lines (small text beneath each chart)

Short forms, to match the SUN NOW credits:

| Chart family | Credit line |
|---|---|
| L1, X-ray, protons, Kp forecast, scales, hemispheric power | NOAA SWPC |
| Kp, Hp, F10.7, sunspot number (GFZ) | GFZ Potsdam (Matzka et al. 2021) |
| CMEs, flares, SEPs, streams | NASA CCMC DONKI |
| Oval map | NOAA SWPC OVATION Prime (model) |
| HF absorption map | NOAA SWPC D-RAP (model) |
| TEC (default) | CODE, University of Bern (Dach et al. 2026) |
| TEC (button) | NOAA SWPC GloTEC |
| Neutron monitors | Oulu cosmic ray station, Sodankyla Geophysical Observatory |
| Solar cycle | WDC-SILSO, Royal Observatory of Belgium |
| Coupling indicator | Newell et al. (2007), computed by FAS |

## 7. Items to check before publishing

1. CODE's licence: no text was found; the citation is requested, and the DOI for the prediction series is uncertain.
2. The SWPC and NOAA public-domain statement: confirmed only second-hand; check SWPC's own disclaimer page.
3. The Dome C station operators and the correct credit.
4. Kyoto's credit form for the Dst quick-look values.
5. The Newell citation details.
6. SILSO's DOI and the exact credit text on its citation page.
7. ~~Whether to credit the spacecraft by name?~~ **Decided 24 Oct 2026 (policy):** yes; name each spacecraft and give its location and distance from Earth in light-seconds (section 8).
8. The Space-Track citation for the drag index, when built: "NORAD satellite catalogue (via Space-Track)", with their terms.

Also unchanged: link-only references (Vedurstofa Islands for cloud, DLR for ROTI) are links, not data credits, and can go on the relevant view if wanted.

## 8. Spacecraft naming policy: name, location, distance in light-seconds

Policy (Al, 24 Oct 2026): wherever data come from a spacecraft, FAS names it, says where it is, and gives its distance from Earth in light-seconds (c = 299,792 km/s). The wording goes in the chart tooltip, the credit line and, where useful, the DATA SRCES table. Distances below are computed from orbit radii and are approximate; items marked **[verify]** need checking against the operator's current page before publishing (spacecraft change, and some orbits vary).

| Spacecraft | Used for | Where | Distance from Earth |
|---|---|---|---|
| NOAA SOLAR-1 (formerly SWFO-L1) **[verify]** | Real-time solar wind and magnetic field (the L1 solar wind charts); the active source on the day of the check | Sun-Earth Lagrange point L1, sunward of Earth | about 1.5 million km, **about 5 light-seconds** |
| Other L1 spacecraft (ACE, DSCOVR, SOHO) **[verify which are active]** | Back-up solar wind; SOHO/LASCO coronagraph images | Near L1 (halo or Lissajous orbits) | about 1.5 million km, about 5 light-seconds |
| GOES-18 (primary) and GOES-19 | X-ray flux, flares and proton flux; SUVI solar images **[verify]** | Geostationary orbit, 35,786 km altitude | 42,164 km from Earth's centre, **about 0.14 light-seconds** |
| SDO (Solar Dynamics Observatory) | AIA and HMI images of the Sun on SUN NOW | Geosynchronous orbit (inclined, near 36,000 km) | about 0.14 light-seconds |
| STEREO-A | High-speed stream observations (kept off the Earth timeline); far-side images if used | Orbit around the Sun, ahead of Earth (Spock: 55 to 65 degrees ahead) | Varies with the year, from a fraction of an AU upward; give the current value computed at display time **[verify]** |
| DMSP and POES/MetOp satellites **[verify]** | The particle measurements behind OVATION and hemispheric power | Low Earth polar orbits, about 850 km | about 0.003 light-seconds |
| GNSS satellites and the ground station network | The data behind GloTEC and the CODE ionosphere maps (signal delays) | Medium Earth orbit, about 20,200 km altitude (GPS), plus ground receivers | about 0.07 to 0.09 light-seconds for the satellites (radius about 26,600 km) |
| Neutron monitors (Oulu; Dome C) | Cosmic ray count rates | Ground stations (Oulu, Finland; Concordia Station, Antarctica) | at Earth: 0 |

Notes for the writer:
- The L1 distance is the reason for the warning time: the solar wind at 400 km/s takes about an hour to cover 1.5 million km, but the measurement reaches Earth in 5 seconds. The tooltip says this once, at the first L1 chart, and refers back to it elsewhere.
- Dome C credit text (from Scotty): "obtained due to support of the French-Italian Concordia Station (IPEV program n903 and PNRA Project LTCPAA PNRA14_00091)".
- The sun images (SDO, SOHO) already carry credits beneath each image; add the spacecraft location line to their tooltips.
