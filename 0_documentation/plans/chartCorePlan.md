# Chart core: one chart helper for LAUNCHES, ON-ORBIT and WEATHER

Status: 25 Oct 2026 (sections 10 to 18 record the weather charts; start at 16 to 18 for what is left). Phase 1 (helper built, LAUNCHES migrated) done and checked by Al. Phase 2 (ON-ORBIT migrated) done structurally, awaiting Al's visual test (section 8). Phase 3 not started.

## 1. Why

The same chart code exists three times: `C:\Users\User\DEV\LCARS-FAS\assets\launchesPanel.js` (frame, axes, line, dual-axis, stacked area and bar), `C:\Users\User\DEV\LCARS-FAS\assets\onOrbitPanel.js` (a second frame `orbitFrameHtml`, a second escape `orbitEscape`, a second nice-step `orbitNiceStep`, its own axes and stacked-column SVG, a bars-and-line SVG, the pie) and a few lines in `usagePanel.js`. The space-weather charts (`spaceWeatherChartsPlan.md`) need all of it and more. One copy, tested once.

## 2. Survey (what each file holds)

LAUNCHES (`launchesPanel.js`, before: 37,362 bytes):
- `niceAxisStep`, `LCARS_CHART_HEIGHT`, `LCARS_CHART_MARGIN`, `launchesChartWidth` (reads `#launches-charts`), `escapeChartText`, `chartFrameHtml`, `yearTickStep`, `chartAxesSvg`, `stackRows`;
- `stackedAreaChartHtml`, `stackedBarChartHtml`, `dualAxisLineChartHtml`, `lineChartHtml` (this one repeated its own frame and axes);
- domain code that stays: filters, year inputs, colour and label tables, `drawLaunches*`, `launchChartSlot`, data loading, resize.

ON-ORBIT (`onOrbitPanel.js`, 88,557 bytes), all untouched in phase 1:
- HTML charts: `orbitBarChartHtml` (log bars), `orbitPieChartHtml`, `orbitRankedColumnChartHtml`, `orbitColumnChartHtml` (log histograms) with `logAxisTop` and `logAxisPercent`;
- SVG charts: `orbitFrameHtml` (= `chartFrameHtml`), `orbitEscape` (= `escapeChartText`), `orbitNiceStep` (= `niceAxisStep`, default ticks 5 not 6), `orbitStackedColumnsSvg` (categorical stacked columns, linear or log), `orbitBarsAndLineSvg` (bars plus a right-hand line), `orbitSlotWidth`, `orbitFormat`;
- single-use, to stay: the altitude-against-inclination bubble scatter, the GEO belt arc, the country/owner tree (`orbitTreeHtml`), the regime table.

USAGE (`usagePanel.js`): `usageWeekGraph`, a 13-line bar SVG with two date labels in a 220 x 64 box, inline colours from `lcarsColour`. Different enough (no axes, no frame, no tooltips beyond `<title>`) that it stays; it takes `escapeChartText` from the core in phase 2 in place of its private `usageEscape` only if Al wants it.

## 3. What goes in `assets/chartCore.js`

Naming: camelCase, functions return strings, one config object per chart, `width` and `height` passed in.

| In the core | From |
|---|---|
| `chartWidth(container, min)`, `escapeChartText`, `niceAxisStep`, `chartLinearAxis(max, ticks)` -> `{step, max}`, `yearTickStep`, `chartStackRows` | LAUNCHES (`launchesChartWidth` became `chartWidth`) |
| `chartFrameHtml` (title bar, total + tooltip, legend, body), `chartSvgHtml` (the `<svg>` wrapper), `chartAxesSvg` | LAUNCHES, with ON-ORBIT's `orbitFrameHtml` (optional `yTitle`, empty legend omitted) folded in |
| `lineChartHtml`, `dualAxisLineChartHtml`, `stackedAreaChartHtml`, `stackedBarChartHtml` | LAUNCHES (line chart now uses the shared frame and axes) |
| `pieChartHtml({title, totalText, totalTooltip, slices})` | ON-ORBIT `orbitPieChartHtml` (positional arguments became a config object) |

Phase 2 adds (from ON-ORBIT): `logBarChartHtml`, `rankedColumnChartHtml`, `columnHistogramHtml` (the three HTML log charts and `logAxisTop`/`logAxisPercent`), `stackedColumnsSvg` (categorical) and `barsAndLineSvg`. Phase 3 adds what the weather charts need: a time axis (UTC), log axes with class bands (A B C M X; S1 to S5), step and bar marks, hatching for forecast, threshold lines, small multiples sharing one time axis. All three keep the CSS classes of `classic.css`.

Stays in the panels: colours and labels for their data, titles and tooltips (the words), filters and year ranges, data loading, slots, resize handling.

## 4. Markup and CSS

Unchanged: `.orbit-chart`, `.orbit-chart-header`, `.orbit-chart-total-tip`, `.lcars-chart-legend*`, `.lcars-chart-swatch`, `.lcars-line-*`, `.lcars-dual-line*`, `.lcars-area-band`, `.lcars-hover-strip`, `.lcars-bar`, `.orbit-pie*`. `classic.css` needs no change in phase 1.

## 5. Load order

`lcars.js` opens a section with `await loadScriptOnce(...)`. Phase 1: `openLaunchesSection()` loads `assets/chartCore.js` then `assets/launchesPanel.js`. Phase 2: `openOnOrbitSection()` the same. Phase 3: `openWeatherSection()` loads `chartCore.js` with the weather panel. The core is a plain script (global functions, like the panels); `loadScriptOnce` ignores a second request, so each section can ask for it. Nothing is added to `index.html`; first-load cost is zero (4,945 bytes gzipped on first use of LAUNCHES, ON-ORBIT or WEATHER).

## 6. Before and after

Structural (done by Scotty, repeatable): `python -m pytest -q 0_tests/test_chartCompare.py` runs `node 0_tests/chartCompare.js`, which loads the saved old files (`0_tests/fixtures/chartsBefore/`) and the new ones in two sandboxes and compares every LAUNCHES chart's HTML for 97 scenarios (4 widths x spacex x outcome x 6 year ranges, plus empty data), and the old pie against the new one. It also runs `node --check` on every `assets/*.js`. Phase 2 extends it to the ON-ORBIT charts.

Visual (Al): LAUNCHES, each chart against the live site, at two window widths; ON-ORBIT in phase 2; hard refresh first (disable the cache in DevTools: panel scripts load lazily and `chartCore.js` is new).

## 7. Phases

1. Helper built; LAUNCHES migrated and checked. **Done.**
2. ON-ORBIT migrated (including the pie); single-use charts left in `onOrbitPanel.js`. **Done structurally 24 Oct 2026; waiting for Al's visual check (section 8).**
3. The helper extended for the space-weather charts.

## 8. Phase 2 result (24 Oct 2026)

**Moved into `chartCore.js`:** `logAxisTop`, `logAxisPercent`, `logAxisTicks`; `logBarChartHtml` (was `orbitBarChartHtml`); `rankedColumnChartHtml` (was `orbitRankedColumnChartHtml`); `columnHistogramHtml` (was `orbitColumnChartHtml`; the `°` in the bucket tooltip became a `unit` option); `logColumnsHtml` (the axis/grid/plot skeleton the last two had each written out); `barsAndLineSvg` (was `orbitBarsAndLineSvg`); `chartRightTicksSvg` (right-hand axis numbers, now also used by `dualAxisLineChartHtml`). `chartAxesSvg` gained an optional `margin` and `xTicks` and a float tolerance on its last y tick; `chartSvgHtml` omits `aria-label` when given no title. `pieChartHtml` replaces the private `orbitPieChartHtml` (4 call sites).

**Deleted from `onOrbitPanel.js`:** `orbitEscape`, `orbitNiceStep`, `orbitFrameHtml` (its 15 call sites now call `chartFrameHtml({..., svg: ...})`, escaping is `escapeChartText`, steps `niceAxisStep(x, 5)`), the five chart functions above, `logAxisTop`/`logAxisPercent`.

**Left in place:** `orbitStackedColumnsSvg` (about ten charts use it; it was not in this phase's scope, so it is the obvious next candidate, as `stackedColumnsSvg`), the bubble scatter, the GEO belt arc (a call to `orbitStackedColumnsSvg`), the payloads-by-year stacked area, the country/owner tree, the share-by-country bars, `orbitSlotWidth`, `ORBIT_SVG_MARGIN`, filters, data code. `classic.css`: no change (four comments there still name the old function names).

**Load order:** `openOnOrbitSection()` in `lcars.js` loads `assets/chartCore.js`, then `assets/onOrbitPanel.js`. That is the only place `onOrbitPanel.js` is loaded.

**Bytes** (raw / gzip -9):

| File | Before | After |
|---|---|---|
| `assets/onOrbitPanel.js` | 88,557 / 19,898 | 76,750 / 17,470 (-11,807 / -2,428) |
| `assets/chartCore.js` | about 17,900 / 4,945 | 26,675 / 7,124 (+8,800 / +2,179) |
| both together | about 106,400 / 24,843 | 103,425 / 24,594 (about -3,000 / -249) |

The saving is small in bytes: the point is one copy of the frame, axes, escape and log-chart code. A visitor who opens LAUNCHES and then ON-ORBIT downloads `chartCore.js` once.

**Comparison** (`node 0_tests/chartCompareOnOrbit.js`, run by `test_chartCompare.py`): the old panel (`0_tests/fixtures/chartsBefore/onOrbitPanel.js`) and the new one run in two sandboxes on the same data. All 27 charts' real `render` functions, 5 data shapes (real-shaped, one row, long/awkward labels, no totals, empty) x SpaceX with/without x two status/kind pairs x slot widths 320, 700 and 1400 (60 scenarios, 1,620 strings), plus the migrated helpers called directly on edge inputs, the old frame against the new one, the old stacked columns against the repointed ones, and the step function. Result: 511 identical, 1,085 whitespace-only, 48 escaping-only, 96 reordered, 0 different. A deliberate break in `chartCore.js` (a renamed CSS class) is caught.

**Intended differences (all listed by the check):**
1. Whitespace and indentation inside the markup (the shared frame lays the source out differently). No effect on the page.
2. Escaping (mission pie, 48 strings): the total's hover text was written raw into `title="..."`; the shared frame escapes it (`signals & EW` becomes `signals &amp; EW`). The browser shows the same text. The same applies to any total tooltip with `&`, `<` or `"` on the three charts that were unescaped (pie, histogram, and bars when given one).
3. Order (debris history, bars and line, 48 strings): the shared axis code writes the x ticks before the bars, the old code wrote each tick then that year's bar. The same elements; ticks lie below the bars, nothing overlaps.
4. Not visible but different: the bars-and-line chart still has no `aria-label` (kept as it was; adding one is a one-line improvement).

### 8a. Addendum: `stackedColumnsSvg` moved (24 Oct 2026, after Al's visual check of the first part: fine)

`orbitStackedColumnsSvg` is now `stackedColumnsSvg` in `chartCore.js` (same arguments), built on `logAxisTop`, `logAxisTicks`, `chartLinearAxis` and `chartSvgHtml`; its 10 call sites in `onOrbitPanel.js` were renamed and the private copy deleted. It used no private helper of its own (`ORBIT_SVG_MARGIN` stays in the panel: the bubble scatter and payloads-by-year use it; the core has its own copy of the same four numbers). `classic.css`: no change.

Bytes (raw / gzip -9), now against the originals: `onOrbitPanel.js` 88,557 / 19,898 -> 73,290 / 16,586 (-15,267 / -3,312); `chartCore.js` about 17,900 / 4,945 -> 30,560 / 7,960 (+12,660 / +3,015); together about -2,600 raw / -297 gzipped. (Step 1 of phase 2 had left them at 76,750 / 17,470 and 26,675 / 7,124.)

Comparison: `chartCompareOnOrbit.js` now totals 391 identical, 1,205 whitespace-only, 48 escaping-only, 96 reordered, 0 different. The 10 charts using it go through their real `render` functions over all data shapes (real-shaped, one row, long labels, no totals, empty), SpaceX on/off, two status/kind pairs, three widths; 24 direct calls cover linear and log, 1, 2 and 36 categories, centred and edge labels at two widths. The only difference is whitespace/indentation inside the `<svg>` (the shared wrapper lays it out differently); no `aria-label` is added, as before.

## 9. Al's check list for ON-ORBIT (against the live site)

Charts using `stackedColumnsSvg` (check these first): LOCN active by regime, inclination by orbit type, altitude (log), GEO belt, age; DEBRIS catalogue by object type, altitude by object type (stacked), debris by inclination (log); COMMS band by mission, band by orbit type. Look at: stack order and colours, legend, y numbers (linear steps, or 1/10/100 on the log ones, with a stub for a count of 1), x labels under the bar middles (regimes, bands, ages) or at the bar edges (degrees, km, longitude), axis title at the right, hover a bar for its figures.

Hard refresh first: DevTools open, Network tab, Disable cache ticked, reload. The panels load lazily, so click ON-ORBIT after the reload. Then for each chart below compare with the live site: title bar text and total; bars or columns (length, colour, order, muted "Other"); axes and numbers; hover tooltips (bar, total); and the filter buttons (ACT-ONLY / ACT +DEAD, SAT ONLY / ALL S-CRFT / ALL-OBJ, EX SPACEX) which redraw every chart.

| Group | Chart | Look at |
|---|---|---|
| LOCN | regime pie | slices and legend counts and percentages; hover the total (tooltip about objects with no perigee/apogee, only if any) |
| LOCN | inclination histogram | log y labels 1, 10, 100 ...; empty buckets blank; x ticks every 15 degrees; hover a column ("15-30°: n") and the total |
| LOCN | active by regime, inclination by regime, altitude, altitude vs inclination (untouched bubble), GEO belt, age | same frame (title, yTitle, legend, total tooltip) and unchanged columns: a check that the frame swap broke nothing |
| COMMERCIAL | sector pie, mission pie | slices; hover the total (mission: "signals & EW" reads normally) |
| COMMERCIAL | nationality, manufacturers, satellite buses | horizontal log bars, exact count past each bar, log ticks 1, 10, 100 ..., axis title at the right, muted "Other" |
| COMMERCIAL | owners | 40 bars + Other, log y axis and gridlines, count above each bar, percentage up inside the bar, names turned 90 degrees, hover a bar and its name, hover the total |
| COMMERCIAL | sector by country, payloads by year, country/owner tree | frame only (title, legend, tooltip) |
| DEBRIS | catalogue by type, altitude by object type, debris by inclination | frame only |
| DEBRIS | debris history (bars and line) | bars (left axis), amber line (right axis), right-hand numbers, x ticks at 1960, 1970 ..., hover a year |
| DEBRIS | rocket bodies by country / by launch vehicle, debris by origin | horizontal log bars as above |
| COMMS | downlink band pie | slices; `Ku`/`Ka` keep lower case; hover the total |
| COMMS | band by mission, band by orbit type | frame only |

Also with the browser console open: no red errors on any group (LOCN, COMMERCIAL, DEBRIS, COMMS), and the LAUNCHES section still draws (it shares `chartCore.js`).

## 10. Phase 3, stage 3a: the time-chart code and the first WEATHER chart (24 Oct 2026)

**Where the code lives.** The time-series part is a separate file, `assets/chartTime.js` (18,468 bytes, 6,042 gzipped), not an addition to `chartCore.js` (unchanged, 30,560 / 7,960), so LAUNCHES and ON-ORBIT do not carry it. It uses `escapeChartText` and `chartSvgHtml` from the core. The chart specific to the data is `assets/weatherCharts.js` (11,906 / 4,668; K1 so far). Load order, lazy, in `weatherPanel.js`: `chartCore.js`, `chartTime.js`, `weatherCharts.js`, the first time SOL DRVR is opened; SUN NOW's first load is unchanged. `lcars.js` is unchanged.

**What `chartTime.js` offers.** `timePanelsSvg` (panels stacked on one shared UTC time axis, each with a left and right axis: linear, log with decade ticks, inverted, class letters A to X or S1 to S5 in faint bands, threshold lines; marks: line, signed area with zero line, bars, shaded bands; gaps drawn as gaps (`gapMs`, or a missing value); forecast part dashed and hatched (`forecastFrom`); vertical event markers through every panel, hollow for "reported, not confirmed"; hover text for any time), `chartTipFrameHtml` (the pill with the detailed tooltip, legend and credit line), `chartSectionBarHtml` (the full-width NOW / PREDICTIVE bar). Helpers: `chartTimeTicks`, `chartTimeLabel`, `chartTimeText`, `chartRuns`, `chartValueScale`, `chartAxisTicks`, `chartSignedAreas`, `chartNearest`.

**CSS.** `classic.css`: the SUN NOW pill and tooltip rules now also match `.chart-pill` / `.chart-tip` (selectors extended, rules unchanged); new block "WEATHER time charts" (`.chart-tip` width, `.chart-section-bar`, `.chart-zero`, `.chart-threshold`, `.chart-forecast-line`, `.chart-shade`, `.chart-class-band`, `.chart-event`, `.chart-credit` and others).

**K1.** `l1SolarWindHtml` (SOL DRVR, NOW band): A speed (left, solid) and density (right, dashed); B Bz as a signed area (warm southward) with Bt as a line; C the convection field E = v x Bs (mV/m) and the Newell function from the stored `derivedNewell`, on paired fixed scales, with E at or above 5 mV/m shaded (provisional, Spock to confirm). Scales move only in fixed steps (ladders), never to fit the data. Gaps of up to 3 minutes are joined, longer ones are left. The tooltip names NOAA SOLAR-1 at L1 (about 1.5 million km, about 5 light-seconds), explains that the warning time is the travel time of the wind (about 60 minutes at 400 km/s, 30 at 800), writes out both formulas with limits, and cites SWPC and Newell et al. 2007.

**Tests.** `0_tests/chartTimeTest.js` (run by `test_chartCompare.py`): 65 assertions (tick times and labels, gaps, log and inverted scales, the signed area split exactly at the zero crossing, forecast hatching, markers and escaping, K1 content and edge cases) plus a golden string, `0_tests/fixtures/chartTimeGolden.txt` (`node 0_tests/chartTimeTest.js --update` after an intended change).

## 11. Stage 3c, SOL DRVR remainder (25 Oct 2026)

SOL DRVR now has every chart of the plan's section 4, both bands; the "still to come" and "planned" lists are gone.

| Band | Pill | Component | Series and events (requests, gzipped bytes now) |
|---|---|---|---|
| NOW | L1 SOLAR WIND | K1 (stage 3a) | five series, about 33 KB for one day of data, about 100 KB when three days are held |
| NOW | FLARES AND PARTICLES | K2 | `goesXrayLong` 17.2 KB (rounded to 4 figures), `goesProtonGE10MeV` 3.0 KB and `...100MeV` 2.9 KB (3 figures), events `flare` 1.7 KB, `sepGroup`, `sEvent` |
| NOW | FLARE RECORD (beside K2) | daily maximum bars | `derivedFlareMaxDay` 0.6 KB |
| NOW | THE SUN'S LONG VIEW | F10.7, 81-day mean, sunspot number | `gfzF107Obs` 2.0, `derivedF107A81` 3.0, `gfzSunspotNumber` 1.8 KB (all with quality) |
| NOW | THE SOLAR CYCLE (beside it) | monthly sunspot number, 25 years | `silsoMonthlyMean` 1.6 KB (new range `25y`) |
| PREDICTIVE | CMES ON THE WAY | K6 | events `cmeShown`, `ipsEarth`, `hssL1`, `hssRecurrence` (about 1.1 KB), `derivedCmeOtherPerDay` |
| PREDICTIVE | THE OUTLOOK | K5 | `swpcForecastF107`, `swpcForecastAp`, `gfzAp` (0.8 KB), plus the long view's F10.7 |

All but K1 are fetched when the slot comes within 400 px of the screen, not on opening the view. About 38 KB gzipped for the new charts at today's data.

**Additive server changes** (`server.py`, tests in `0_tests/test_serverWeather.py`): `/api/weather/series` takes `quality=1` (adds `q`, the quality text of each sample: burst?, provisional, forecast included), `sig=N` (values rounded to N significant figures; used for the X-ray and proton series, 41 KB to 17 KB and 8.5 KB to 3 KB) and the range `25y`. Nothing in publishing or ingestion changed.

**Chart code added to `chartTime.js`:** calendar ticks (months, years), mark types `dots` (hollow rings, tips), `spans` (thick bars from time to time at a value), bars with colour by value, labels and tips, `noHatch`; the hover strips are drawn under the marks and only strips and marks that carry a tooltip take the pointer (`.chart-time-body`, `.chart-hit`). `classic.css`: `.chart-row` (two charts side by side, one above the other under 1100 px), `.chart-time-body`, `.chart-hit`, `.chart-bar-label`, `.chart-span`.

**Decisions made, for the Captain to confirm** (see the stage report): K5 stacks F10.7 and Ap in two panels (rule 1: a second axis only for the same process); Ap bars come from the 45-day forecast product; the +-10 hour arrival error bar; STEREO-A recurrence shown; cycle-start months hard-coded.

## 12. Stage 3c, ERTH NOW (25 Oct 2026)

ERTH NOW is built to the plan's section 5, with the storm strip first under the scales. New file `assets/weatherEarth.js` (35,092 bytes, 10,832 gzipped), loaded after `weatherCharts.js` only when ERTH NOW is first opened; it holds the shared components K3, K4, K7 and K8 so AURORAE and LEO DRAG can reuse them. `chartTime.js` and `chartCore.js` are unchanged; `weatherCharts.js` gained only a `title`/`credit` option on the K6 timeline (reused as WHAT IS ARRIVING). `classic.css`: tiles, scale tiles and the forecast-chance bars. No server or publishing change.

| Band | Pill | Component | Requests (gzipped) |
|---|---|---|---|
| strip | EARTH RIGHT NOW | latest R, S, G, Kp so far, F10.7, Bz, wind speed | `/api/weather/now` 1.6 KB |
| NOW | NOAA SCALES | K8, level now and 24-hour maximum | three series, 0.4 KB |
| NOW | THE STORM IN ORDER | X-ray, protons, wind, Bz, Kp with Dst on one axis; CME launch, predicted arrival and shock markers; next 12 h hatched | `goesXrayLong` 17.0 (sig 4), `goesProtonGE10MeV` 3.0 (sig 3), `l1WindSpeed` 3.8 (sig 3), `l1MagBzGSM` 5.9, `l1MagBt` 5.2, `gfzKp` 0.2, `swpcKp` 0.3, `swpcDst` 0.3, CME and shock events 0.4 |
| NOW | GEOMAGNETIC ACTIVITY | K3, Kp bars with inverted Dst, 7 days | 1.0 KB |
| NOW | KP: SWPC AND GFZ (beside it) | paired bars, 24 h | shares the Kp requests |
| NOW | AURORAL POWER | K4, north and south | 0.8 KB |
| PREDICTIVE | THREE-DAY FORECAST | K7, Kp grid | 0.2 KB |
| PREDICTIVE | FORECAST CHANCES (beside it) | flare and proton chances, highest G level | 0.5 KB |
| PREDICTIVE | WHAT IS ARRIVING | K6 under its own title, link to SOL DRVR | CME events 1.1 KB |

Everything but the strip fetches as it nears the screen. About 42 KB gzipped in all, 36 KB of it the storm strip.

Tests: `0_tests/chartTimeTest.js` now 140 assertions (gLevelOf, each ERTH NOW chart on synthetic data, and every chart with the site holding nothing).

## 13. Stage 3e, GCR (25 Oct 2026)

New file `assets/weatherGcr.js` (loaded after `weatherCharts.js` and `chartTime.js` when GCR is first opened; `weatherEarth.js` is not needed). Two charts in the NOW band and a PREDICTIVE bar that says there is nothing to forecast and links to CMES ON THE WAY in SOL DRVR.

- **COSMIC RAYS NOW** (30 days): a tile row (Oulu now in per cent of its reference, "Forbush decrease?" flag, Dome C with "data to <date>" and its age) above a chart of Oulu and Dome C as steps one hour wide (hourly rows are stamped at the START of the hour: plan note 17), each in per cent of its own reference: `% = 100 x (I / Iref - 1)`, Iref 6177 (Oulu, cycles 20 to 24) and 1081 (Dome C, Nov 2019), the constants of `scripts/ingestionGCR.py`. Markers: shocks seen at Earth (`ipsEarth`) and storm onsets of G1 or more (`storm`). Dome C is never shifted; its last hour is stated in the legend and the tile. The Forbush flag is this site's rule: latest 3-hour mean at Oulu at least 2 percentage points below the highest hourly value of the previous 5 days.
- **THE SOLAR CYCLE** (25 years): Oulu monthly as per cent of 6177 on an inverted left axis (monthly thin, SILSO 13-month smoothing bold) against the 13-month sunspot number (right axis, dashed); cycle 24 and 25 starts marked; Dome C monthly from Nov 2019 as a lavender line, with hollow rings for partial months ("partial month from <date>") and heavily corrected months (those before Nov 2019 are not drawn).
- Moved: `weatherAgo`, `weatherTile`, `weatherNow` from `weatherEarth.js` to `weatherCharts.js` (shared by tile-style charts). Options added: `title`/`tipExtra` on `k2Html`, `title` on `outlookHtml`, `kpGridHtml` and `forecastProbabilitiesHtml` (+ `noG`).
- Requests (gzipped): `gcrOuluCorrected` 3.1 KB, `gcrDomcCorrected` 2.7 KB (30 days), `ipsEarth` 0.8, `storm` 0.3, `gcrOuluMonthlyCorrected` 1.6, `silsoMonthlyMean` 1.6, `gcrDomcMonthlyCorrected` 0.8: about 10.9 KB.
- Tests: `0_tests/chartTimeTest.js` (percent, hour semantics, the smoothing weights, both charts on synthetic and, in a scratch run, real data, and with the site holding nothing).

## 14. Stage 3d, HF COMMS (25 Oct 2026)

New file `assets/weatherHf.js` (loaded with `weatherEarth.js`). Charts built from K1 to K8 and the D-RAP numbers, no maps.

| Band | Pill | Component |
|---|---|---|
| NOW | FLARE FADE-OUT AND RADIATION | K2 (`k2Html` with a new `title` and `tipExtra` option): X-ray with R lines, protons with the S1 line, plus an HF paragraph (D-layer absorption, polar cap absorption) in the tooltip |
| NOW | ABSORPTION NOW | the D-RAP highest affected frequency (series `drapMax`, `drapMaxLat`, `drapMaxLon` from `/api/weather/now`) as a tile and one line; below 5 MHz: "No significant HF absorption (highest affected frequency x MHz, below 5 MHz, the bottom of the HF band 3 to 30 MHz)" (Spock, note 8); from 5 MHz it reports value and place and says the map is not built |
| NOW | AVIATION BOARD | four lamps: HF absorption (D-RAP: under 5 MHz green, 5 to 15 amber, 15+ red), polar cap absorption (S level 0 / 1-2 / 3+), flare fade-out (R level 0 / 1-2 / 3+), GNSS TEC (grey, waiting). Marked "indicative, not an official advisory". Thresholds provisional |
| PREDICTIVE | RADIO OUTLOOK | the K8 chances (R1-R2, R3+, S1+; `forecastProbabilitiesHtml` with `noG`) beside DRIVING SIGNAL: the last hour of the solar wind (speed, Bz, E = v Bs / 1000), `l1StripHtml` |

**Left out of HF COMMS, and why:** the D-RAP world map (a map); foF2 and D-RAP at the visitor's location, "YOUR PATH" (foF2 needs the TEC / ionosonde ingestion, and D-RAP is held only as the latest global map, not as a time series); the GNSS TEC lamp (needs TEC; shown grey).
Requests (gzipped): the K2 set 25.1 KB (shared with SOL DRVR), `swpcForecast3day*` 0.7 KB, `l1WindSpeed` and `l1MagBzGSM` 6h 0.2 KB; `/api/weather/now` 1.6 KB.

## 15. Stage 3g, LEO DRAG (25 Oct 2026)

New file `assets/weatherDrag.js` (loaded with `weatherEarth.js`).

| Band | Pill | Component |
|---|---|---|
| NOW | THE ATMOSPHERE BREATHES | two stacked panels, 90 days: F10.7 daily dots (hollow burst days) with the 81-day mean (dashed where it includes the forecast), and the daily maximum Kp bars with the G colours. The drag index panel is NOT built |
| NOW | WHO IS EXPOSED | active payloads by mean altitude, 10 km bands from 150 to 700 km, SpaceX stacked on the others, VLEO (below 450 km) shaded, from the catalogue already held for ON-ORBIT |
| PREDICTIVE | WHAT DRAG DOES NEXT, THE KP FORECAST | K5 (`outlookHtml`, new `title` option) beside K7 (`kpGridHtml`, `title` option) |

**Additive server change:** `/api/on-orbit/chart?name=exposure` (rows `{band, spacex, n}`; fixed filter: active payloads, mean altitude 150 to 700 km; the ON-ORBIT buttons do not apply). Test in `0_tests/test_server.py`.

**Waiting, and why:** the FAS drag index (three altitude bands against a 27-day baseline) and the decay-rate-against-altitude chart (scale height) both need the Space-Track element-set history table (`gpHistory`), which is not built; PASS TIMING belongs to GS OPS.
Requests (gzipped): `gfzF107Obs` 90d 0.6 KB, `derivedF107A81` 90d 1.0 KB, `gfzKp` 90d 2.5 KB, `exposure` 0.4 KB, plus the K5 and K7 requests of SOL DRVR and ERTH NOW.

## 16. Still not built (after stage 3g)

AURORAE (globe and polar maps, K9; the visitor's required Kp, K7 variant; the 27-day recurrence) and SAT COMMS (TEC maps, K10; needs the TEC ingesters), and what needs a TEC series: foF2, YOUR PATH, the GNSS TEC lamp. (The D-RAP map was built afterwards: section 17; the map component is `weatherMap.js`.) Shared components to reuse, by file: `chartCore.js` (frames, axes, pies, log charts), `chartTime.js` (time panels, tooltips, section bars), `weatherCharts.js` (fetch helpers, K1, K2, K5, K6, tiles), `weatherEarth.js` (K3, K4, K7, K8, storm strip), `weatherGcr.js`, `weatherHf.js`, `weatherDrag.js`. Each view is drawn by a `render<View>View()` in `weatherPanel.js`; tests are in `0_tests/chartTimeTest.js` (run by `test_chartCompare.py`) with fake fetches and a fixed clock.

## 17. The first map: D-RAP in HF COMMS and the reusable map component (25 Oct 2026)

New file `assets/weatherMap.js` (14,571 bytes, 4,867 gzipped), loaded with `weatherHf.js` only when HF COMM is opened (`weatherPanel.js` `renderHfView`). New outline file `assets/weatherCoast.json` (32,131 bytes, 11,691 gzipped), fetched the first time a map is drawn, never on first load. Built offline by `0_tools/buildWeatherCoast.py` from the country boundaries the site already ships (`assets/leaflet/world.json`, Douglas-Peucker 0.25 degree, whole tenths of a degree, delta-coded); rerun it to regenerate (a test fails if the saved file differs from a fresh build). It holds country outlines, not a coast-only line (shared borders are drawn once per country).

**Map component API (for AURORAE and SAT COMMS).** `weatherMapSvg({id, width, view, layers, coast, terminatorMs, markers, hoverText, title})` returns the markup of one equirectangular map plus a readout line under it.
- `id` unique per map on the page; `width` as the other charts (the SVG scales to its slot with CSS, so a resize needs no redraw); `view` `{lonMin, lonMax, latMin, latMax}`, default the world.
- `layers`: `[{values, latMax, latStep, lonMin, lonStep, colourAt(v)}]`, a grid whose rows run from `latMax` by `latStep` and columns from `lonMin` by `lonStep` (cell centres; the shape of the stored `drapGlobal` map, and of OVATION and the TEC maps with `rows` renamed to `values`). `colourAt` returns a colour or null. Equal neighbours in a row become one rectangle (flare D-RAP: about 590 rectangles).
- `coast`: `await weatherCoastRings()` (cached; empty if the file cannot be had). `terminatorMs`: shades the night side for that time (computed in `weatherSubsolarPoint` and `weatherTerminator`, no fetch). `markers`: `[{lat, lon, label, color}]`. `hoverText(lat, lon)`: the readout text on pointer move or touch (inline `onpointermove`, found by `WEATHER_MAP_REGISTRY[id]`).
- Helpers: `weatherMapLegend(levels)` for the `legend` of `chartTipFrameHtml`, `weatherGridValueAt(grid, lat, lon)` (nearest cell, wraps longitude, same rule as `aurora_at` in `server.py`), `weatherMapData(name)` (`/api/weather/map?name=`, cached per view opening), `weatherMapFrame` (the projection: `x(lon)`, `y(lat)`, `lon(px)`, `lat(py)`).
- Not in it, on purpose: other projections. AURORAE's globe and polar maps need an orthographic or polar frame: replace `weatherMapFrame` (give it the same four functions) and the layers, coast, night and marker code follow, except that rectangles become cells that must be projected (draw them as paths). Raster tiles would also be faster for TEC's 5-degree grid than rectangles; neither was needed here.

**ABSORPTION NOW** (`assets/weatherHf.js`: `loadAbsorption`, `hfAbsorptionHtml`, `hfShowMap`): the tile and the one-line verdict as before; the map is drawn when `drapMax` is 5 MHz or more, or the proton message (carried in the quality text of `drapMax`) is not "Normal Proton Background" (Spock's note 8), or the visitor follows "Show the map anyway" (which fetches it, once; "Put the map away" hides it). Colour bands: 1 to 5, 5 to 10, 10 to 15, 15 to 20, 20 to 30 MHz and over, nothing below 1 MHz; the 5 and 15 MHz edges are the lamp thresholds. The ring marks the maximum (not drawn on a proton-only map); with a location set, a YOU ring and an "AT YOUR LOCATION" tile. Night is shaded from the map's own valid time. Layout: ABSORPTION NOW is now full width above the AVIATION BOARD. No server change: `/api/weather/map?name=drapGlobal` already served it (16.6 KB raw, 925 bytes gzipped on a quiet day).

**GNSS TEC lamp.** `siteWeather.db` has a `tecMaps` table but it holds 0 rows on DEV, and there is no `ingestionTEC.db`; the fixtures are samples only. So the lamp stays grey, now worded "no TEC maps held yet". When maps are held, drive it from the GloTEC anomaly (the lamp rule is Spock's to set).

**YOUR PATH: blocked.** It needs foF2 (from GloTEC `nmf2` via `tec-at`/`tec-series`, empty until the TEC ingester has run) and a D-RAP time series at the visitor's place (only the latest global map is stored; a series would need `publishSite.py` to keep `drapAt` or the map per hour). Not built.

**Other.** The resize handler in `weatherPanel.js` redrew only SOL DRVR; it now redraws any WEATHER view (the SVG charts have a fixed width, so they were left at the old size in the other views).

**Tests.** `0_tests/chartTimeTest.js` 187 assertions in all, of which the map and D-RAP card account for about 20: the point under the Sun at three known moments, every point of the day-night line 90 degrees from it, grid lookup and wrap, colour bands, the proton message, the antimeridian pen lift, quiet (no map or outline fetched), show/put away, a flare map (rectangle count, key, tooltip, hover), a location marker, a proton event, and everything with the site holding nothing. `0_tests/test_buildWeatherCoast.py` (the saved outline equals a fresh build; under 60 KB). Real data was run through the loaders in a scratch run (the DEV map is quiet: 0.9 MHz at most; a synthetic flare pattern on the real grid gave 589 rectangles, 119 KB of markup in the DOM). Nothing seen by eye.

## 18. LEO DRAG: nothing more can honestly be finished (25 Oct 2026)

Re-read against the plan: THE ATMOSPHERE BREATHES (two of its three panels), WHO IS EXPOSED and WHAT DRAG DOES NEXT are built. The drag index and the decay-rate chart need element-set history; `ingestionSpaceTrack.db` and `siteOrbital.db` hold one element set per object (one `epoch`), so no decay can be measured from them. `bstar` and `meanMotionDot` are in them, but they are fitted terms of one set, not a measured decay (SGP4 ignores `meanMotionDot`), so a BSTAR-against-altitude scatter would be a different, weaker chart; offered to the Captain and Spock as a possibility, not built. `gpHistory` is neither built nor approved; Space-Track not contacted.

## 19. SAT COMMS, the GNSS lamp and YOUR PATH (25 Oct 2026, after the TEC ingesters were run by hand on DEV)

New files, all lazy: `assets/weatherTec.js` (17,655 bytes, 6,250 gzipped; shared TEC code) and `assets/weatherSat.js` (28,843 / 9,307; the SAT COMMS cards). `weatherMap.js` grew to 15,817 / 5,281 and `weatherHf.js` to 25,550 / 9,020. SAT COMM loads `chartCore, chartTime, weatherCharts, weatherEarth, weatherMap, weatherTec, weatherSat`; HF COMM loads `weatherEarth, weatherMap, weatherTec, weatherHf`. First load is unchanged.

**Server (one additive endpoint; restart the dev server):** `/api/weather/tec-summary` (`handle_weather_tec_summary`, `tec_summary_of` in `server.py`): the newest STORED GloTEC map as `{validUtc, cellsCounted, anomalyThirdFraction, anomalyLargestFraction, tecMaxObserved: {tec, lat, lon, flag}}`. It never asks NOAA. Tests in `0_tests/test_serverTEC.py` (47 pass). Nothing in ingestion or publishing changed.

**Data held on DEV (25 Oct, 10:55 UTC):** CODE observed 23 Oct 00:00 to 25 Oct 00:00 (49 maps), the 1-day prediction for 25 Oct (plus 26 Oct 00:00), the 2-day for 26 Oct, the 5-day for 29 Oct (the days between are not held), one GloTEC map. So the prediction days offered are today, +1, +2 and +4 (the plan's +5 does not exist in the files CODE publishes here: the 5-day file covers the fifth day, 29 Oct). A day with fewer than 6 maps (a file's closing midnight) is not offered.

**SAT COMMS cards** (`renderSatView` in `weatherPanel.js`; each fetches as it nears the screen):

| Band | Pill | What |
|---|---|---|
| NOW | TEC NOW | map (CODE default; buttons CODE/GLOTEC and ABSOLUTE/ANOMALY; anomaly implies GloTEC, CODE implies absolute), tiles beside it for the visitor (TEC, L-band delay, Faraday at 145.8 and 437 MHz) |
| NOW | EFFECT BY BAND | table VHF 145.8, UHF 437, L 1575.42, S 2200, X 8200, Ku 12000, Ka 26000 MHz: Faraday rotation, one-way delay, S4 relative to L-band (weak scatter, f^-1.5); the DEFS example (20 TECU, 50 uT) when no location |
| NOW | TEC AT YOUR LOCATION | TEC for 24 h (CODE solid, then dashed and hatched where predicted, join marked, GloTEC dots, hollow = no observations) with Kp bars beneath |
| PREDICTIVE | TEC FORECAST | CODE prediction map; day buttons and an hour slider (UTC) |
| PREDICTIVE | TEC FORECAST AT YOUR LOCATION | observed tail (2 days) plus predictions, now and join marked, Kp observed and forecast (hatched) beneath |
| PREDICTIVE | STORM RISK | lamp from the 3-day Kp forecast: under 4 green, 4 to 5 amber, 5 or more red "DISTURBED TEC LIKELY" (provisional) |

**Rules followed.** GloTEC anomaly: Spock's wording (confirmed and inferred parts marked in the tooltip); cells with quality flag 0 hatched grey and not coloured; the hover text gives "coverage q of 5" and says the value is the model's estimate where it is 0. CODE and GloTEC share an axis only in the location charts, with the caveat (95.7 against 68.0 TECU on 24 Oct) in the tooltip and the join marked. CODE credit with the DOI. Spacecraft named with light-seconds (GNSS about 20,200 km, 0.07 light-seconds; COSMIC-2 about 550 km, 0.002).

**Requests (gzipped, over the wire):** `tec-index` 0.4 KB; `tec-code` one hourly map 6.9 KB (on demand: each day or hour button fetches one more); `tec-latest` about 22.5 KB (only when GLOTEC or ANOMALY is pressed; the server asks NOAA at most every 30 minutes, so this is the one place a visitor can cause a NOAA request); `tec-at` 0.45 KB; `tec-series` 0.9 KB (the server unpacks all 125 maps for it, 0.06 s, cached per pair of cells); `tec-summary` 0.17 KB; plus the outline (11.7 KB, once) and Kp. First view of SAT COMM: about 30 KB of map data plus 12 KB outline plus 20 KB of scripts. A possible later saving: the map needs 3 of GloTEC's 5 lists (`tec`, `anom`, `q`); a `fields` parameter on `tec-latest` would cut about 35%. Not done.

**Map component additions** (API in section 17): layer `latFirst` (alias of `latMax`; step positive going north, as GloTEC), `stretchPoles` (the first and last rows run out to the poles; CODE stops at 87.5), `colourAt` receives null for a missing value, and a shared hatch pattern `url(#weather-map-hatch)` for "no observations". Shared by SAT COMMS and HF COMMS in `weatherTec.js`: the fetchers (`tecIndex`, `tecCodeRecord`, `tecLatestRecord`, `tecAt`, `tecSeriesAt`, `tecSummary`; null on failure, and a failure is not remembered), `tecMapLayers`, `tecMapHover`, the palettes, `tecHere`, the physics (`tecDelayM`, `tecFaradayDeg`, `tecAlongFieldMicroT`, `tecFoF2FromTec`, `tecSlabKm`) and `tecLamp`.

**GNSS lamp (HF COMMS AVIATION BOARD): a provisional rule, for the Captain and Spock to confirm.** The worse of two tests on the newest stored GloTEC map; grey if none or over 6 hours old. (1) The third-largest |anomaly| / (the cell's own 30-day median) among cells with quality flag 3 or more and a median of at least 10 TECU: 60% amber, 100% red. (2) ICAO's absolute thresholds (on the DEFS page): highest observed TEC 125 TECU amber, 175 red. Why: GloTEC's anomaly has no official threshold; a ratio to the cell's own median is comparable between equator and pole; the third-largest rather than the largest means one odd cell cannot light the lamp; the 60% edge sits above what a quiet day gave on 25 Oct (45%: the equatorial crests are lopsided even in calm conditions, Spock's note of 24 Oct), so a quiet day stays green; flag-0 cells are model values and are left out; ICAO's numbers are the only published ones. Today it reads green: "3rd-largest anomaly 45% of median; highest observed TEC 70 TECU".

**YOUR PATH (HF COMMS, between ABSORPTION NOW and the AVIATION BOARD).** One MHz axis, 48 h back to 24 h ahead: foF2 from GloTEC (dots; NmF2 via 8.98 sqrt(NmF2)); foF2 inferred from CODE's hourly TEC (line, dashed and hatched where the TEC is a prediction) with NmF2 = TEC / slab thickness, the thickness being the median of GloTEC's own TEC/NmF2 pairs at the place (300 km if none, clamped to 150 to 600 km); and the D-RAP value at the place as ONE ring at now, from the latest map (`drapGlobal`). Tiles: foF2 GloTEC, foF2 inferred, MUF(3000) about 3 x foF2 (DEFS; indicative, within about 20%), D-RAP now. A sentence under the chart and the tooltip list what is missing: **no D-RAP time series at the place (only the latest global map is stored; a series needs `publishSite.py` to keep D-RAP at chosen places, or the map each hour: the Captain's decision), GloTEC history only as long as the 3-hourly collection has run, and no measured foF2 (no ionosonde data)**. The slab thickness varies by a factor of about 1.5 between day and night, so the inferred line is good to 15 to 20%: it is labelled INFERRED.

**Tests** (`0_tests/chartTimeTest.js`, now 238 assertions): the arithmetic against DEFS' own numbers (636, 71, 2.8, 0.2 degrees), foF2 and the slab, the lamp rule edge by edge, palettes and layers, the hatch, the hover text, every card on synthetic data with fake fetches (CODE by default, no `tec-latest` until the button, GloTEC on pressing it, GloTEC failing, day buttons only for days with maps, the slider, the join and now markers, with and without a location), the board lamp, YOUR PATH, and every new card with the site holding no TEC (with and without a location). A scratch run put the real DEV maps (from the in-process server, never NOAA) through all the loaders: no undefined or NaN, 452 rectangles for a CODE map, 833 for the GloTEC anomaly (461 of them hatched). Nothing seen by eye.

## 20. Still not built (after section 19; superseded by section 23)

AURORAE (K9 globe and polar maps need another projection frame; the visitor's required Kp; the 27-day recurrence). A D-RAP history at the visitor's place (YOUR PATH). Measured foF2. The FAS drag index and decay-rate chart (`gpHistory`, not approved). PASS TIMING (GS OPS). `checkLiveDeployment.py` does not yet list the weather chart files.

## 21. AURORAE (stage 3b, 25 Oct 2026)

New file `assets/weatherAurora.js` (36,765 bytes, 11,927 gzipped), loaded with `weatherEarth.js` and `weatherMap.js` the first time AURORAE is opened (`renderAuroraView` in `weatherPanel.js`); first load is unchanged. No ingestion, publishing or database change; no new endpoint (the oval is `/api/weather/map?name=ovation`, 139 KB raw, 3.4 KB gzipped on 25 Oct, up to about 70 KB in a storm; the series are the existing ones). `aurora-at` is not needed by the page: the aurora index at the visitor's place is read from the map already held.

| Band | Pill | What |
|---|---|---|
| NOW | THE OVAL | K9: the OVATION oval on a polar map or a globe; night shaded from the map's own valid time (two tones: Sun below 0 and below -12 degrees); filled bands of the aurora index (5 to 9 dim, 10 and over full), thin contours at 5, 10, 20, 40, 60, the index-10 edge solid white, the index-5 edge dashed; hover readout (index, Sun altitude); beside it, for each hemisphere, peak, equatorward edge, hemispheric power and Spock's wording |
| NOW | YOUR SKY TONIGHT | needs a location: Sun and Moon altitude for 24 h (dark hours shaded), aurora index here, Sun and Moon now, geomagnetic latitude, Kp now against Kp needed here, the oval edge on the visitor's meridian |
| NOW | ACTIVITY | K4 north and south power (left axis) with Kp bars (right axis; one process, so a second axis is allowed) |
| PREDICTIVE | THE NEXT HOUR | the last hour of the solar wind (the K1 strip, moved into `weatherCharts.js` as `l1StripSvg`) with the countdown from the 1.5 million km and the latest speed |
| PREDICTIVE | THE NEXT NIGHTS: KP FORECAST | K7 with the visitor's required Kp outlined (dashed ice) |
| PREDICTIVE | 27-DAY RECURRENCE | daily Ap, last 30 days solid; the same record 27 days earlier moved forward, dashed and hatched from now; the correlation of the last 30 days with the 27 before them in the credit |
| PREDICTIVE | EARTH-DIRECTED CMES | K6 with `earthOnly` (only CMEs with an Earth arrival forecast) |

**View buttons (moved by the Captain's order, 25 Oct).** GLOBE, N POLE and S POLE are in THE OVAL card, under the per-hemisphere text in the column beside the map (`ovalHtml`, class `aurora-view-switch`), not in the control area: the control area keeps its ten view buttons in every view (`weatherViewButtons()`, as before; `weatherControlButtons` and the `aurora-views` group are gone). They sit in the same grid cell as the text, so when the map and the text stack under 1100 px they stay under the text. They use the SAT COMMS switch buttons (`.weather-switch`), the chosen one in LCARS white (`aria-pressed`). Pressing one calls `auroraSetView(view)`, which redraws the card (the pill tag changes too). Until one is pressed the view is the visitor's hemisphere (`AURORA_CONTROL.view = 'auto'`), N POLE without a location. The globe turns by dragging (`weatherMapDragStart`, document-level listeners; a redraw takes about 55 ms).

**The single map.** The plan's NOW / +30 to 90 MIN switch is not built, because OVATION gives one map: its "forecast time" is 30 to 90 minutes after its observation time (25 Oct: observed 18:57, valid 20:11). The tooltip and the credit say so, and THE NEXT HOUR shows the valid time. Nothing shows the oval at a different time.

**Spock's edge rule is applied in the browser, and it was checked against the ingester**: `auroraHemisphere` (peak with its tie-break, edge only where the oval reaches it at 10 or more longitudes, the reach and the middle of its longest run, for the index-10 and index-5 tiers) was run on the real DEV map and gave exactly the stored samples `ovationMax*`, `ovationEdge*`, `...Lon`, `...Cover` and the `...Faint*` ones for both hemispheres (a scratch run; pytest cannot hold the live database). The words (note 7 of the display notes): edge exists: "Aurora possible overhead poleward of X, low on the horizon from about X-5, if the sky is dark"; only the faint tier: "Faint aurora only. Cameras may catch it, the eye probably not, poleward of X near longitude Y, if the sky is dark"; neither: "No visible aurora expected. The oval peaks at index M near L (forecast for HH:MM UTC)". The weather `now` samples are not used for the edges: `/api/weather/now` returns the newest non-missing value of each series, which for an edge that has just vanished would be an old one.

**Kp needed** (`requiredKpAt`, `weatherEarth.js`): NOAA's Space Weather Scales rule of thumb for the geomagnetic latitude at which aurora is commonly seen: Kp 5 60 degrees, 6 55, 7 50, 8 45, 9 40; 4 taken as 65; 3 or less as 67 and poleward; interpolated between; more than Kp 9 below 40 degrees. Geomagnetic latitude is the tilted-dipole pole (80.7 N, 72.7 W; about 2020), `geomagneticLat`, moved from `weatherTec.js` into `weatherEarth.js` with `weatherPlace()` and `satNeedLocation`. **ERTH NOW's forecast grid and AURORAE's now outline the blocks whose forecast Kp reaches the visitor's required Kp** (`kpGridHtml` option `requiredKp`; dashed ice inner rectangle, legend entry, sentence in the credit, and the cell's hover text; none without a location). This closes the item deferred from ERTH NOW.

**Sun and Moon** are computed in the browser (`auroraSunAltitude` from `weatherSubsolarPoint`; `auroraMoon`: the truncated series of the Astronomical Almanac, position to about half a degree, altitude to about a degree with parallax left out, phase to a per cent). Tested against the new Moon of 10 Oct and the full Moon of 26 Oct 2026, and the waxing sign.

**Map component additions** (`weatherMap.js`, now 32,549 / 9,324): `weatherProjection({kind: 'north' | 'south' | 'globe', size, centreLat, centreLon, rotateLon, latLimit})` with `project` and `invert` (azimuthal equidistant about a pole down to `latLimit`, default 30 degrees, longitude `rotateLon` at the bottom; orthographic globe); `weatherSphereSvg({id, size, projection, layers, coast, lines, markers, hoverText, drag, title})`; layers are the same grids as `weatherMapSvg` but drawn as annular sectors, **one path per colour**, so the 65,000-cell oval is a handful of elements (cells on the far side of the globe are not drawn); `weatherContours(grid, level)` (marching squares, columns wrap, closed rings round the pole); `weatherSpherePath` (the pen is lifted wherever a point is out of sight). The hover handler and the registry work for both kinds. Use for SAT COMMS or anything polar the same way: build a projection, give `weatherSphereSvg` layers.

**Cost.** Markup in the DOM (not over the wire): 261 KB north polar, 229 KB south, 334 KB globe, about 60 ms to build; most of it the outline (63 KB), the night cells and the contours. Over the wire: the map (3.4 KB gzipped), the outline (11.7 KB once), `gfzAp` 90 days 0.5 KB, Kp and power series, and for THE NEXT HOUR the two 6-hour series (0.2 KB).

**Tests** (`0_tests/chartTimeTest.js`, 299 assertions): projection round trips for all three kinds, the pole in the middle, east anticlockwise in the north and clockwise in the south, the far side of the globe hidden; contours (closed line half way between cells, the wrapping ring, none); the sector fill (one path per colour, nothing outside the disc for every kind); Sun, Moon and phase; Kp needed and geomagnetic latitude; the hemisphere numbers and wording on a synthetic map including the tie-break and the "fewer than 10 longitudes" rule; every card on synthetic data; the buttons (view changes, globe draggable, drag turns it west when pulled right and stops at 85 degrees); the three view buttons under the text beside the map (position in the markup, default, redraw on press) and the control area keeping exactly its ten buttons (in a sandbox holding `weatherPanel.js`); the recurrence correlation (1.0 for a record that repeats, none for scrambled, nothing for under 10 pairs); Earth-directed CMEs; the Kp outline; and every card with the site holding nothing, with and without a location (south and north).

**No place is named** anywhere in AURORAE (a test searches the card and the source). The DEFS page still has examples in Iceland, which are Spock's.

## 22. `tec-latest?fields=`, and the live-deployment checker (25 Oct 2026)

**`fields` on `/api/weather/tec-latest`** (`server.py`, additive; restart the dev server): `fields=tec,anom,q` (any of `tec, anom, nmf2, hmf2, q`, comma-separated, in any order) returns the record with only those lists, the other keys (times, grid) kept, packed once per map and field set and given its own ETag; an unknown name is a 400 and NOAA is not asked. Without it the answer is unchanged. `weatherTec.js` `tecLatestRecord` now asks for `tec,anom,q`: the real stored map is 22,544 bytes gzipped whole and 13,496 trimmed, 40% smaller. Tests in `0_tests/test_serverTEC.py` (51 pass).

**`0_tools/checkLiveDeployment.py`** now lists the WEATHER panel and its chart files among the assets it compares with the working copy (`weatherPanel.js`, `chartTime.js`, `weatherCharts.js`, `weatherEarth.js`, `weatherGcr.js`, `weatherHf.js`, `weatherDrag.js`, `weatherMap.js`, `weatherCoast.json`, `weatherTec.js`, `weatherSat.js`, `weatherAurora.js`); `chartCore.js`, the other panels and `index.html` were there. A new test (`0_tests/test_checkLiveDeployment.py`) fails if a `weather*.js` or `chart*.js` file in `assets\` is missing from the list. It was NOT run against LIVE. Note that the checker will report these files missing on LIVE until the site is deployed, and the weather API paths are not in its API list for the same reason.

## 23. Still not built (after section 22)

The FAS drag index, the decay-rate chart and a BSTAR scatter (`gpHistory`, not approved); a D-RAP history at the visitor's place (YOUR PATH); measured foF2; cron, deployment and monitoring (the Captain's decisions). Every view in the plan now exists on DEV.
