# Space weather charts: the WEATHER views

Status: draft 2, 24 Oct 2026. Nothing built. Revises draft 1 by (a) adding a second-axis rule, (b) combining charts and reusing one component across views, and (c) showing each view as it would be displayed. Covers the eight WEATHER views in `C:\Users\User\DEV\LCARS-FAS\assets\weatherPanel.js`: SOL DRVR (`drivers`), ERTH NOW (`earth`), GCR, LEO DRAG, SAT COMMS, HF COMMS and AURORAE. (SUN NOW and DEFS exist.) Data comes from `siteWeather.db` (see `spaceWeatherIngestionPlan.md`), except where marked **new source**. Chart choices follow Spock's report (`enterpriseCrewOutput\spock_spaceWeatherReport_2026-10-22.md`, section 8).

## 1. Rules for every chart

- **Vanilla JS and inline SVG**, one shared helper (axes, time scale, line, step, bar, area and band marks, hatching, markers, tooltips), loaded with the panel. No chart library, no CDN. Each view's data well under 100 KB gzipped, fetched lazily from `/api/weather/series`, `/events` and `/map`.
- **All times UTC.** Charts stacked in one frame share one time axis.
- **A second y-axis is allowed only when** (a) the two series measure the same process, (b) there are at most two series, (c) each axis is labelled and drawn in its line's colour, and (d) the scaling is fixed and honest (no free scaling that manufactures a correlation). Otherwise stack panels on a shared time axis. Examples that pass: Kp with Dst; speed with density; F10.7 with sunspot number; neutron count (axis inverted) with sunspot number. Examples that do not: X-ray with protons (the delay between them is the point: stack); Bz with speed.
- **Log axes only where the physics is logarithmic** (X-ray flux, proton flux), with decades labelled by physical class (A, B, C, M, X; S1 to S5).
- **Observed, estimated and forecast look different**: solid, lighter, hatched or dashed. Gaps are drawn as gaps. No false precision.
- **Colour:** sequential for magnitude, diverging only for signed quantities (Bz, anomalies). LCARS palette via `lcarsColour()`; text at the control-button size.
- **Sections are separated by pill horizontals with titles**, as elsewhere on the site: a full-width pill bar with the section title, in the style of the SUN NOW chart headers (`orbit-chart-header`), with a black gap above. This applies at every level: each view's NOW and PREDICTIVE bands, and the groupings within a band. NOW and PREDICTIVE use the same two LCARS colours in every view, so the reader learns them.
- **Every chart has a pill title with a detailed tooltip, as standard practice** (decided 24 Oct 2026): what it shows, where the data come from and how often they update, units and thresholds, the formula for any derived quantity (written out, with its limits), a short piece of science, and the citation. The tooltip is the place for the detail, so the chart itself stays clean. A small credit line sits beneath each chart.
- **Name the source spacecraft, and say where it is** (policy, decided 24 Oct 2026). Every chart or tile whose data come from a spacecraft names it in its tooltip and credit line, states where it is (for example "at the Sun-Earth Lagrange point L1, sunward of Earth") and gives its distance from Earth in light-seconds (L1: about 5 light-seconds; geostationary GOES: about 0.14). The L1 solar wind charts also say what that distance means: the warning time is the travel time of the wind, not of light. The table of spacecraft is in `spaceWeatherCreditsDraft.md`, section 8.
- **One component, many views.** A chart used in more than one view is built once (section 3) and given its own pill title where it appears.

## 2. Now and predictive

Each view has two bands:

- **NOW: WHAT IS GOING ON.** Measured or nowcast values, the last few hours to 3 days (30 or 90 days for slow series), drawn solid.
- **PREDICTIVE: WHAT IS COMING.** Forecasts and warning signals, drawn hatched or dashed, labelled with the issue time and source.

GCR has no predictive band: nothing open forecasts cosmic rays. It points to the CME arrivals that cause Forbush decreases.

## 3. The shared components

Built once, reused with a different pill title. Data cost is counted once.

| Code | Component | What it shows | Used in |
|---|---|---|---|
| **K1** | L1 solar wind | Panel C (coupling indicator: simple product and Newell function, derived) sits under panels A and B. Panel A: speed (left axis, line) with density (right axis, line). Panel B: Bz as an area, diverging colour (southward shaded warm), with total field Bt as a line, one axis in nT. 3 days. | SOL DRVR, AURORAE (last hour, with arrival countdown), HF COMMS (driving signal) |
| **K2** | Flares and particles | Panel A: X-ray flux (long channel), log axis with A to X bands and R1 to R3 lines, flares of class M or above marked. Panel B: protons above 10 MeV and above 100 MeV, log axis with the S1 line and SEP onsets marked. 3 days, shared time axis. | SOL DRVR, HF COMMS |
| **K3** | Kp and Dst | Kp as bars (left axis 0 to 9, coloured only where G1 to G5 are crossed), Dst as a line on an inverted right axis so a storm points the same way on both. 7 days observed. | ERTH NOW, LEO DRAG, AURORAE (Kp bars alone, with the visitor's required Kp) |
| **K4** | Hemispheric power | North and south lines, one axis (GW), 24 hours. | ERTH NOW, AURORAE |
| **K5** | Solar outlook | 45-day F10.7 forecast (line, left axis) with the 27-day Ap outlook (bars, right axis); the most recent observed F10.7 joined on at the left, forecast hatched. | SOL DRVR, LEO DRAG |
| **K6** | CME timeline | Timeline, 7 days back and 3 forward: each CME at launch (size or colour by speed), predicted Earth arrival as an uncertainty bar, observed shock as a vertical marker; high-speed stream onsets as small marks. | SOL DRVR, ERTH NOW (link), AURORAE (filtered to Earth-directed), GCR (as Forbush markers) |
| **K7** | Kp forecast grid | Rows are days, columns the eight 3-hour blocks, cell colour is forecast Kp; the visitor's required Kp outlined where relevant. 3 days. | ERTH NOW, AURORAE, LEO DRAG |
| **K8** | Scales tiles | R, S and G tiles: level now (0 to 5), 24-hour maximum, three-day forecast probabilities underneath. | ERTH NOW (R and S probabilities reused in HF COMMS) |
| **K9** | Oval map | One map whose view is chosen by three control-area buttons on the right-hand side of the screen: **GLOBE, N POLE, S POLE** (labels to be shortened further if they do not fit the LCARS button style); and a time switch: NOW, +30 to 90 MIN (the model's forecast time). OVATION as filled contour bands with thin contour lines, day/night terminator, the visitor's location marked. | AURORAE |
| **K10** | TEC map | One map with two switches: ABSOLUTE or ANOMALY; and (in PREDICTIVE) NOW, +1 DAY, +2 DAYS, +5 DAYS. Sequential palette for absolute, diverging for anomaly. | SAT COMMS, HF COMMS (foF2 context) |

## 4. SOL DRVR

**NOW**

| Pill | Content |
|---|---|
| L1 SOLAR WIND | K1 |
| FLARES AND PARTICLES | K2; beside it a small 30-day **flare record** (daily bars of the largest class each day, coloured by class, M and X days labelled) |
| THE SUN'S LONG VIEW | **F10.7 with sunspot number**: daily F10.7 dots with the 81-day mean as a line (left axis), daily sunspot number as a thin line (right axis), 13 months. Beside it, the **solar cycle**: monthly sunspot number, about 25 years, current cycle highlighted (**new source** SILSO). |

**PREDICTIVE**

| Pill | Content |
|---|---|
| CMES ON THE WAY | K6 |
| THE OUTLOOK | K5 |

Under K1 sits panel C, the **coupling indicator** (decided 24 Oct 2026: both versions): the simple driving term (solar wind speed times southward Bz) and the **Newell coupling function** dPhi/dt = v^(4/3) * B_T^(2/3) * sin^(8/3)(theta/2), where v is the speed, B_T = sqrt(By^2 + Bz^2) and theta is the clock angle of the field in the y-z plane (Newell et al. 2007), as two lines with fixed, honest scales; periods of strong driving shaded. Both are derived at publish time from the stored L1 data. The tooltip writes out both formulas with their limits and states that they are indicators, not measurements. Spock to confirm the formulas, units and shading thresholds before building.

```
+-- SOLAR DRIVERS -------------------------------------------------------+
| (default text: what the Sun is sending)                                |
|                                                                        |
| [ NOW: WHAT IS GOING ON ================================== NOW ]      |
|                                                                        |
| [ L1 SOLAR WIND ==================================== 3 DAYS ]         |
|  speed/density  ~~~~~~/\~~~~~~~~~~/\~~~~~   (two axes, two colours)    |
|  Bz / Bt        ______/\________/\_______   (area; south shaded)       |
|                                                                        |
| [ FLARES AND PARTICLES ================================= 3 DAYS ]     |
|  X-ray (log)   C--M--X bands   |  flare record, 30 days (bars)         |
|  protons (log) S1 line         |  |  |  ||  |                          |
|                                                                        |
| [ THE SUN'S LONG VIEW ============================== 13 MONTHS ]      |
|  F10.7 dots + 81-day mean + sunspot number | solar cycle, 25 years     |
|                                                                        |
| [ PREDICTIVE: WHAT IS COMING ============================ FORECAST ] |
|                                                                        |
| [ CMES ON THE WAY ================================= 10 DAYS ]        |
|  o---o---O===>  arrival bars, shock markers, stream onsets             |
|                                                                        |
| [ THE OUTLOOK ====================================== 45 DAYS ]        |
|  F10.7 forecast (dashed)  +  27-day Ap outlook (bars, right axis)      |
+------------------------------------------------------------------------+
```

## 5. ERTH NOW

**NOW**

| Pill | Content |
|---|---|
| NOAA SCALES | K8 (levels now and 24-hour maximum) |
| GEOMAGNETIC ACTIVITY | K3; beneath it a small **Kp comparison**: SWPC estimated Kp and GFZ nowcast Kp as paired bars for the last 24 hours (the two series differ while provisional) |
| AURORAL POWER | K4 |
| THE STORM IN ORDER | The main chart: panels stacked on one shared time axis, in causal order: X-ray (K2 panel A), protons (K2 panel B), Bz and speed (K1), Kp with Dst (K3); CME launch, arrival and shock as vertical markers through every row. Built from the same panels as the other views, so no extra data. Observed part only; the forecast edge is hatched. |

**PREDICTIVE**

| Pill | Content |
|---|---|
| THREE-DAY FORECAST | K7, with the K8 forecast probabilities (flare, proton, geomagnetic) as small bars beside it |
| WHAT IS ARRIVING | K6 (link to the full timeline in SOL DRVR) |

```
+-- EARTH NOW -----------------------------------------------------------+
| [ "NOW" HEADER:  R0  S0  G1   Kp 4.3   F10.7 158   Bz -3   450 km/s ]  |
|                                                                        |
| [ NOW: WHAT IS GOING ON ================================== NOW ]      |
|                                                                        |
| [ NOAA SCALES ====================================================== ]|
|  [ R 0 ] [ S 0 ] [ G 1 ]     now / 24 h max / 3-day forecast           |
|                                                                        |
| [ GEOMAGNETIC ACTIVITY ============================== 7 DAYS ]        |
|  Kp bars (left) + Dst line, inverted (right)                           |
|  Kp: SWPC vs GFZ, last 24 h (paired bars)                              |
|                                                                        |
| [ AURORAL POWER ===================================== 24 HOURS ]      |
|  north / south hemispheric power                                       |
|                                                                        |
| [ THE STORM IN ORDER ================================== 3 DAYS ]      |
|  X-ray | protons | Bz + speed | Kp + Dst   (CME markers run through)   |
|                                                                        |
| [ PREDICTIVE: WHAT IS COMING ============================ FORECAST ] |
|                                                                        |
| [ THREE-DAY FORECAST ================================= 3 DAYS ]      |
|  Kp forecast grid  |  flare / proton / storm probabilities (bars)      |
|                                                                        |
| [ WHAT IS ARRIVING ===================================== 10 DAYS ]    |
|  CME timeline (K6)                                                     |
+------------------------------------------------------------------------+
```

## 6. GCR

Two ingesters are needed (**new sources**): Oulu neutron monitor hourly (fetch hourly, about 4 KB a request; a 30-day backfill is 37.6 KB) and the monthly records (Oulu since 1964, 39 KB; SILSO monthly sunspot number, 126 KB, monthly). Fixtures are in `C:\Users\User\DEV\LCARS-FAS\0_tests\fixtures\` (`nmdbOuluHourly30d.csv`, `nmdbOuluMonthly1964.csv`, `silsoMonthly.csv`). Terms: Oulu requires acknowledgement of its site and the Sodankyla Geophysical Observatory; SILSO is CC BY-NC 4.0, credit "WDC-SILSO, Royal Observatory of Belgium, Brussels".

**NOW**

| Pill | Content |
|---|---|
| COSMIC RAYS NOW | A single tile (today's count as per cent of the reference, with a note when in a Forbush decrease) and the **30-day neutron chart**: pressure-corrected hourly count as per cent of the reference, with Forbush decreases visible as dips and DONKI CME shocks and storm onsets (from K6) as vertical markers |
| THE SOLAR CYCLE | **Neutron count with sunspot number**, 25 years, monthly: count on an inverted left axis, sunspot number on the right, fixed scales. One picture of the anticorrelation: cosmic rays are highest at solar minimum. |

The 30-day chart carries two lines: OULU and the Antarctic Dome C station (percent of each station's own reference), so a Forbush decrease is seen at both poles. Dome C's record is short (installed in the 2000s), so the 25-year cycle chart uses OULU only. Both come from the same Oulu server and query form, so the extra load is one more small request per fetch. Parked: stations at mid and low latitudes (different cutoffs) until NMDB is reachable. Not planned: an aircrew dose estimate.

```
+-- GALACTIC COSMIC RAYS ------------------------------------------------+
| (default text: particles from outside; a busy Sun pushes them away)    |
|                                                                        |
| [ NOW: WHAT IS GOING ON ================================== NOW ]      |
|                                                                        |
| [ COSMIC RAYS NOW ================================== 30 DAYS ]        |
|  [ 99.2 % of reference ]   count: ______\__/____\____  (dips = CMEs)   |
|                                                                        |
| [ THE SOLAR CYCLE ================================= 25 YEARS ]       |
|  neutron count (inverted)  and  sunspot number: mirror images          |
|                                                                        |
| (no predictive band: see CME arrivals in SOL DRVR)                     |
+------------------------------------------------------------------------+
```

## 7. LEO DRAG

Charts marked * wait for the Space-Track history table, which is not built. F10.7 and Kp are already stored.

**NOW**

| Pill | Content |
|---|---|
| THE ATMOSPHERE BREATHES | One three-panel chart, 30 to 90 days on a shared time axis: F10.7 (daily), Kp bars (K3 form), and the **FAS drag index\*** (three altitude bands, 400 to 450, 450 to 500 and 500 to 550 km, as ratio to the 27-day baseline). Storms raise drag within about a day. |
| WHERE SATELLITES FLY | Side by side: **decay rate against altitude\*** (scatter, log y, by object class, exponential fit with labelled scale height) and **who is exposed** (histogram of active payloads by mean altitude, 10 km bins, VLEO shaded, from the existing catalogue; needs no history). |

**PREDICTIVE**

| Pill | Content |
|---|---|
| WHAT DRAG DOES NEXT | K5 (F10.7 forecast and Ap outlook) and K7 (the Kp forecast grid) |
| PASS TIMING (LATER) | In GS OPS: along-track error from the element set's age and the drag index, against the chosen antenna's beamwidth; shown only when a storm is active |

```
+-- LEO DRAG ------------------------------------------------------------+
| [ NOW: WHAT IS GOING ON ================================== NOW ]      |
| [ THE ATMOSPHERE BREATHES ========================== 30-90 DAYS ]    |
|  F10.7        ........../''''\.........                                |
|  Kp bars      |  ||  |||||  |                                          |
|  drag index*  3 band lines, ratio to baseline                          |
| [ WHERE SATELLITES FLY ============================== SNAPSHOT ]      |
|  decay rate vs altitude*  |  who is exposed (histogram)                |
| [ PREDICTIVE: WHAT IS COMING ============================ FORECAST ] |
| [ WHAT DRAG DOES NEXT ==================================== 45 DAYS ]  |
|  F10.7 / Ap outlook (K5)  |  Kp forecast grid (K7)                     |
+------------------------------------------------------------------------+
```

## 8. SAT COMMS

Data: GloTEC (live, fetched every 3 hours, compact grid) and CODE (predicted maps, issued once a day; citation required). Scintillation has no open feed, so it is a rule-of-thumb table and a link.

**NOW**

| Pill | Content |
|---|---|
| TEC NOW | K10 with the ABSOLUTE or ANOMALY switch; beside it a tile for the visitor's location: delay in metres at the L-band GNSS frequency and Faraday rotation at 145.8 and 437 MHz |
| EFFECT BY BAND | A table of VHF/UHF, L, S, X, Ku and Ka against Faraday rotation, delay and scintillation, with live numbers for the visitor's location and the formulas in the tooltip |
| TEC AT YOUR LOCATION | TEC line, last 24 hours, nearest cell, with Kp bars beneath (stacked panels) |

**PREDICTIVE**

| Pill | Content |
|---|---|
| TEC FORECAST | K10 with the day switch (+1, +2, +5 days; "model prediction, issued [time]") and, beneath, the visitor's location: observed tail joined to the forecast line for 5 days, forecast hatched |
| STORM RISK | A traffic-light tile from the Kp forecast ("disturbed TEC likely" when forecast Kp reaches 5), indicative only |

```
+-- SAT COMMS -----------------------------------------------------------+
| [ NOW: WHAT IS GOING ON ================================== NOW ]      |
| [ TEC NOW ======================================== 3-HOURLY ]         |
|  [ ABSOLUTE | ANOMALY ]  world map          | your location: 3.1 m     |
|                                             | L-band, 71 deg at 437MHz |
| [ EFFECT BY BAND ==================================== TABLE ]        |
| [ TEC AT YOUR LOCATION ============================== 24 HOURS ]     |
| [ PREDICTIVE: WHAT IS COMING ============================ FORECAST ] |
| [ TEC FORECAST ====================== [NOW|+1D|+2D|+5D] ]            |
|  world map                                  | location line, 5 days    |
| [ STORM RISK ]  [ tile ]                                               |
+------------------------------------------------------------------------+
```

## 9. HF COMMS

**NOW**

| Pill | Content |
|---|---|
| FLARE FADE-OUT AND RADIATION | K2 (X-ray with R-scale lines, protons with the S1 line and polar cap absorption note) |
| ABSORPTION NOW | **D-RAP world map**: highest affected frequency, sequential palette (0 transparent), terminator; "not auroral absorption" in the tooltip |
| YOUR PATH | **foF2 and D-RAP at your location**: both are in MHz, so one axis; 24 to 72 hours; the maximum usable frequency is shown as indicative (within about 20 per cent) |
| AVIATION BOARD | Traffic lights for HF absorption, polar cap absorption, fade-out and GNSS TEC, marked "indicative, not an official advisory" |

**PREDICTIVE**

| Pill | Content |
|---|---|
| RADIO OUTLOOK | The K8 forecast probabilities for R1 to R2 and R3 or more (flares) and for S1 or more (protons), plus the last-hour driving-signal strip (K1) |

```
+-- HF COMMS ------------------------------------------------------------+
| [ NOW: WHAT IS GOING ON ================================== NOW ]      |
| [ FLARE FADE-OUT AND RADIATION ======================== 3 DAYS ]      |
|  X-ray (log) + protons (log)  (K2)                                     |
| [ ABSORPTION NOW ==================================== D-RAP ]        |
|  world map of highest affected frequency                               |
| [ YOUR PATH ======================================= 24-72 HOURS ]     |
|  foF2 and D-RAP at your location (one axis, MHz)                       |
| [ AVIATION BOARD ]  [ lights ]                                         |
| [ PREDICTIVE: WHAT IS COMING ============================ FORECAST ] |
| [ RADIO OUTLOOK ================================== 3 DAYS ]          |
|  flare and proton probabilities  |  L1 driving signal, last hour       |
+------------------------------------------------------------------------+
```

## 10. AURORAE

Everything is global; "your location" is the visitor's own from the shared location form. Darkness and Moon are computed in the browser.

**NOW**

| Pill | Content |
|---|---|
| THE OVAL | K9, its view set by the right-hand control buttons GLOBE, N POLE and S POLE (a hand-written orthographic projection, drag to rotate), beside summary tiles: peak intensity and where it is, equatorward edge, hemispheric power, for each hemisphere |
| YOUR SKY TONIGHT | One timeline over the next 24 hours: darkness band (Sun below 12 degrees), Moon altitude and phase, and the OVATION value at the visitor's location as a tile; beside it the Kp-now bars against the Kp needed at the visitor's magnetic latitude |
| ACTIVITY | K4 with Kp bars, 24 hours (hemispheric power and Kp both measure auroral activity, so a second axis is allowed here) |

**PREDICTIVE**

| Pill | Content |
|---|---|
| THE NEXT HOUR | K1 with the arrival countdown ("arrives in about N minutes"), and K9 on its +30 to 90 minute setting |
| THE NEXT NIGHTS | K7 (with the visitor's required Kp) and the **27-day recurrence** (Kp or Ap now against 27 days earlier, two lines on one axis; needs a month of stored data) and K6 filtered to Earth-directed CMEs |

**The contoured oval.** OVATION values run 0 to 100 on a 1-degree grid. Draw filled bands (faint green through yellow to red) under thin contour lines at about 5, 10, 20, 40 and 60, using marching squares (about 60 to 100 lines), with the seam at longitude 0 handled. About 3 KB gzipped on a quiet day, up to about 70 KB in a storm, fetched lazily. Label it "model, not an observation".

```
+-- AURORAE -------------------------------------------------------------+
| [ NOW: WHAT IS GOING ON ================================== NOW ]      |
| [ THE OVAL ====================================== (see buttons) ]      |
|  rotating globe, contoured oval, terminator, you are here *            |
|                                         | N: peak 62, edge 66 deg      |
|                                         | S: peak 18, edge --          |
| [ YOUR SKY TONIGHT =================================== 24 HOURS ]     |
|  darkness band, Moon  |  OVATION value here: 34  |  Kp 4 vs needed 5   |
| [ ACTIVITY ======================================= 24 HOURS ]        |
|  hemispheric power (N, S) + Kp bars (right axis)                       |
| [ PREDICTIVE: WHAT IS COMING ============================ FORECAST ] |
| [ THE NEXT HOUR ================================== [NOW|+30-90 MIN] ]|
|  oval at forecast time          | L1 strip: arrives in about 41 min     |
| [ THE NEXT NIGHTS =============================== 3 DAYS / 27 DAYS ] |
|  Kp forecast grid | 27-day recurrence | Earth-directed CMEs            |
+------------------------------------------------------------------------+
```

## 11. Data needs and what is already stored

| Need | Source | Status |
|---|---|---|
| L1, X-ray, protons, Kp, Dst, F10.7, forecasts, hemispheric power, scales | SWPC ingestion | Built; DEV database holds 7 days of X-ray and protons, 1 to 2 days of L1; the 3-day L1 chart fills over 3 days of hourly fetching |
| GFZ indices, DONKI events | GFZ, DONKI ingestion | Built; DEV database holds 90 days |
| F10.7 and Kp for the 13-month chart | GFZ `--backfill 400` | Not run; Al's decision |
| Oval, any-place value, D-RAP | OVATION, D-RAP | Built (global grids, `aurora-at` lookup) |
| TEC now | GloTEC compact grid | Ingester not built; a real map is saved as a fixture; directory-listing entry point; every 3 hours |
| TEC forecast | CODE predicted maps | Ingester not built; sample saved; citation required |
| GCR and sunspot records | Oulu, SILSO | Fixtures only; ingesters and tables not built |
| Drag index, decay rate, exposure | Space-Track history table | Not built; awaiting go-ahead |
| Darkness, Moon, geomagnetic latitude | Computed in the browser | A new small script |
| 27-day recurrence | Stored Kp and Ap | Needs about a month of data |

## 12. Build order

1. The chart helper, with a time axis, dual-axis support, hatching and tooltips; tested on **K1**.
2. The shared components in order of reuse: K2, K3, K4, K6, K7, K8, K5.
3. **AURORAE** first (the data is built, and the globe is the showpiece): K9, then the rest.
4. **SOL DRVR** and **ERTH NOW** (mostly assembly of the shared components).
5. **HF COMMS** (D-RAP and X-ray already stored).
6. **SAT COMMS** (waits for the TEC ingesters).
7. **GCR** (waits for the Oulu and SILSO ingesters).
8. **LEO DRAG** last (waits for the Space-Track history table).

Within each view, NOW first, then PREDICTIVE.

## 13. Decisions for Al

1. ~~Which button is selected when AURORAE opens?~~ **Decided 24 Oct 2026:** N POLE or S POLE, according to the visitor's location (the hemisphere they are in). If the location is unknown, N POLE. GLOBE is one button away.
2. ~~Is the storm in order chart the main ERTH NOW chart?~~ **Decided 24 Oct 2026:** yes, it is the primary ERTH NOW chart, placed first under the scales tiles. The separate charts (Kp and Dst over 7 days with the SWPC-versus-GFZ inset, hemispheric power) are kept: duplication is fine because they present the data in a different context.
3. ~~Coupling indicator?~~ **Decided 24 Oct 2026:** both the simple product and the Newell function, as panel C under K1; Spock to confirm formulas and thresholds.
4. ~~Reference neutron monitor?~~ **Decided 24 Oct 2026:** Oulu's own server is the single source, with two stations from it: OULU (Finland, the reference and the 25-year record) and the Antarctic Dome C data (DOMC / DOMB, on the same server), as a southern-hemisphere second line on the 30-day chart. NMDB is not used.
5. ~~Both TEC sources?~~ **Decided 24 Oct 2026:** yes, both. CODE (Bern) is the default map, fetched once a day by cron (observed previous day plus 1, 2 and 5-day forecasts). NOAA GloTEC is reached by a control button that shows the latest, larger and fresher map (server fetch with a 30-minute cache, one fetch at a time, returned as a compact grid). Independently of visitors, the server also fetches GloTEC on a schedule (3-hourly, about 20 MB a day) and stores the compact grid, to keep **7 days of NOAA history** for the trend lines (TEC and foF2 at a place); anything older than 7 days is deleted. The site does not depend on visitor numbers to build the history.
6. ~~GFZ backfill for the 13-month chart?~~ **Decided 24 Oct 2026:** yes, `--backfill 400`, once; 13 months of daily F10.7 must be retained (Scotty running it; the 81-day mean's start-up needs about 80 further days, see his report).
7. ~~Build the GCR and SILSO ingesters?~~ **Decided 24 Oct 2026:** yes (Scotty building).
8. ~~Test an outside source for historical 1-minute L1?~~ **Decided 24 Oct 2026:** no. The L1 history simply accumulates from SWPC's feed; the 3-day chart is complete after three days.

## 14. Data notes from Spock's review (24 Oct 2026)

Spock's verdicts are in `enterpriseCrewOutput/spock_dbDataQuestions_2026-10-24.md`. The code side is done (scripts/weatherDerived.py and the ingesters); what the display needs is stored. One line per item, with what is stored and what Al still decides.

- **1 Protons:** the floor (0.15 to 0.45 pfu) is galactic cosmic rays. Stored: all eight channels. Decide: plot >10 MeV (and optionally >100 MeV) in quiet times, all channels from 1 pfu, hide >1 and >5 MeV; log axis 0.1 to 1e4 with a grey "cosmic-ray background" band.
- **2 X-ray short channel:** stored with quality `GOES-18 contaminated` (electron correction over about half the signal) and, at the 1e-9 processing floor, an extra ` floor`. Decide: draw the short channel only where it is neither contaminated nor floor; leave gaps.
- **3 Bt:** stored as reported (mean of the magnitudes); plot as field strength. The coupling panel uses `derivedNewell` (unit (km/s)^(4/3) nT^(2/3); per minute for 3 days, hourly means from 30 minutes or more for 90 days; for L1, 45 to 70 minutes before Earth).
- **4 Kp:** `noaaScaleG` for "now" (label NOAA); GFZ Kp (`def` over `pre`) for history and the storm list (events `storm`: start, end, maxKp, level, links). Only the latest `swpcKp1m` is published: show at most "this block so far: Kp at least x". G from Kp: G1 4.67 to 5.33, G2 5.67 to 6.33, G3 6.67 to 7.33, G4 7.67 to 8.67, G5 9.
- **5 Ap unit:** `swpcForecastAp` is now `Ap` (NOAA says nT). Decide the label: "Ap (index; x 2 nT is about the disturbance at 50 degrees geomagnetic latitude)".
- **6 F10.7:** chart `swpcF107Daily` (the Noon reading) or GFZ observed, never the three readings. Second review: GFZ's daily value is the single 20 UT reading. A day is flagged `burst?` (quality column, value untouched, observed and adjusted) when it is more than 15% above the mean of the days either side, or (SWPC's three readings) Noon is more than 15% above the larger of Morning and Afternoon; SWPC's own readings are flagged against the MEDIAN of the day's three. The three burst days are 18 Jan, 1 Jul and 2 Sep 2026. `derivedF107ObsClean` replaces flagged days (median of the three readings, else the neighbour mean) and feeds the mean and the drag work. Decide: a hollow marker on flagged days, with "flare radio burst during the 20 UT measurement; not representative of the day".
- **7 OVATION:** samples are stamped at the forecast time (the observation time is in the quality text). Stored per hemisphere: the maximum and where (`ovationMax*`, `...Lat`, `...Lon`), and two edge tiers by Spock's definition with MIN_LONS 10: T = 10 (`ovationEdge<N|S>`, `...Lon`, `...Cover`; naked-eye limit) and T = 5 (`...Faint`, `...FaintLon`, `...FaintCover`; camera only). The map holds the 360 smoothed edge latitudes for both tiers (`edgeN`, `edgeS`, `edgeFaintN`, `edgeFaintS`). Decide the wording: edge exists: "Aurora possible overhead poleward of X degrees (low on the horizon from about X - 5), if the sky is dark"; only the faint tier: "Faint aurora only. Cameras may catch it, the eye probably not, poleward of X near longitude Y, if dark"; neither: "No visible aurora expected. The oval peaks at index M near L degrees (forecast for HH:MM UT)", from `ovationMax*`, never a zero or a blank. Map: index below 5 transparent, 5 to 9 dim, 10 and over full colour; call it "aurora index", not "%".
- **8 D-RAP:** the maximum's location is the tied cell nearest the subsolar point. Decide: show the map only when `drapMax` is 5 MHz or more (C1) or the proton message is not "Normal Proton Background"; otherwise one line: "No significant HF absorption (highest affected frequency x MHz, below the 3 to 30 MHz HF band)".
- **9 Flares:** `derivedFlareMaxDay` (W/m2, quality = class, peak time, satellite) is the daily maximum from SWPC's XRA events of the primary GOES satellite only. DONKI FLR is only for the flare-to-CME links.
- **10 Protons events:** events `sEvent` (start, end, peak, from >10 MeV at 10 pfu, three consecutive values) are the markers; events `sepGroup` are DONKI's SEP records grouped one per event, STEREO-A left out, status `observed` or `forecast`.
- **11 Storms:** the storm list is `storm` (GFZ Kp, runs of 4.67 or more), with DONKI's CME, IPS and HSS links within one block; it has more storms than DONKI's GST list.
- **12 CMEs:** events `cmeShown` (ENLIL arrival, or leading-edge speed of 1000 km/s or more; speed, type S/C/O, half-angle from the leading-edge analysis) and the daily count `derivedCmeOtherPerDay` for "+n other CMEs". Decide the wording of the count line.
- **13 Streams:** `hssL1` (seen by SOLAR-1, ACE, IMAP, DSCOVR or WIND), `ipsEarth` (shocks located at Earth) and `hssRecurrence` (STEREO-A streams that may return about 22 days later, give or take 3). Decide whether to show the recurrence hint.
- **14 L1 gaps:** no interpolation and no filling from other spacecraft. Hourly means need 30 minutes (6 of 12 readings for the 5-minute protons). Decide how gaps are drawn (Spock suggests joining gaps up to 3 minutes). Label "NOAA SOLAR-1, real-time (L1)".
- **15 Dst:** quality `realtime` (Kyoto's quick-look values, later revised). Decide the label: "Dst (Kyoto real-time quick-look, provisional)", credit "WDC for Geomagnetism, Kyoto (via NOAA SWPC)".
- **16 Sunspot number:** `silsoMonthlyMean` (quality definitive or provisional; the definitive record lags about a quarter). Decide: provisional months as hollow markers, the month in progress from GFZ's daily values labelled "estimated"; credit "WDC-SILSO, Royal Observatory of Belgium, Brussels" (CC BY-NC 4.0).
- **17 Neutron monitors (second review):** hourly rows are stamped at the START of the hour (verified from 1-minute data): draw hourly values as steps from hh:00 to hh+1:00, or plot them at hh:30. Cycle chart: Oulu only, monthly, as 100 x (I / 6177 - 1) per cent (6177 cts/min is the mean over solar cycles 20 to 24; constant `OULU_REFERENCE_CTS_MIN` in scripts/ingestionGCR.py), with SILSO's 13-month smoothing; label "Cosmic rays at Oulu (neutron monitor), % relative to the 1964-2019 average". Dome C, if shown, as 100 x (D / 1081 - 1) from Nov 2019 on, with a caption that its swings are about 1.7 times Oulu's. Show "Dome C data to <date>" and never shift the series (about 20 hours behind Oulu is delivery delay); take "now" from Oulu. Stored: the split January 2026 Dome C month is one row on the 1st, quality "partial month from 2026-01-09"; eight 2016-19 Dome C months say "heavily corrected".
- **18 81-day F10.7 mean (second review):** `derivedF107A81` is a CENTRED 81-day mean of the cleaned OBSERVED flux (NRLMSISE-00's F10.7A, JB2008's F81c), for the chart and for drag; it exists only where the whole window exists (at least 75 of the 81 days), so it starts 40 days after the start of the record. The newest 40 days are filled from SWPC's 45-day forecast and the rows say "includes the SWPC 45-day forecast". Decide: draw those dashed and label them "includes forecast", or stop the curve 40 days before the newest data; label the curve "81-day centred mean, observed F10.7 (GFZ)". Needs the 500-day GFZ backfill (at least 436 days) for the 13-month chart: Al's decision.

## 15. TEC decisions, 24 Oct 2026

- **CODE schedule:** the daily CODE job runs at 09:15 UTC (CODE issues its four files between 08:01 and 08:15 UTC; an earlier run would meet 404s). Server time is UTC-7, so the cron line is `15 2 * * *`.
- **CODE and GloTEC on one axis:** allowed, because both are TEC in TECU. The tooltip on any chart that does this must give the caveats: the two products are defined differently (CODE: vertical TEC in a thin shell at 450 km from a spherical-harmonic fit of about 120 stations, on a 2.5 by 5 degree grid, hourly; GloTEC: a data-assimilation model on a different grid, which may include plasmasphere electrons), so a systematic difference between them is expected (on 24 Oct CODE's peak was 95.7 TECU and GloTEC's 68.0), and the joint is drawn with a visible marker. The wording is to be checked against Spock's answer on the GloTEC anomaly and quality flag (`enterpriseCrewOutput\spock_gloTecAnomaly_2026-10-24.md`).
- **Still open:** the NmF2 storage step (1e10) and the observed-to-forecast join rule were Scotty's questions 2 and 4; not sent to Spock; engineering judgement stands unless Al says otherwise.
- **GloTEC anomaly and quality flag (Spock, 24 Oct 2026, `enterpriseCrewOutput\spock_gloTecAnomaly_2026-10-24.md`):** confirmed by NOAA's GloTEC page: the anomaly is the deviation from the 30-day median; `quality_flag` is the mean number of F-region observations per vertical profile, capped at 5; with no observations the TEC relaxes to the IRI-2016 climatology driven by F10.7. Inferred (about 95%): unit TECU; median per cell at the same time of day over the preceding 30 days; sign is current minus median. Flag 0 = no data this cycle (72% of cells in the saved map: Arctic, Siberia, Sahara, South Atlantic, Antarctica); flag 5 = best-observed (14%: Americas, Europe, Japan, Australia). Tooltip, confirmed wording: "Deviation of the total electron content from its 30-day median." Fuller version (inferred words marked): "TEC anomaly: how far the total electron content here is above (+) or below (-) its median at this time of day over the previous 30 days, in TECU." **Decided by Al, 24 Oct 2026:** grey out the anomaly where flag = 0, and say in the tooltip that there it reflects the model's response to season and F10.7, not observed weather.
