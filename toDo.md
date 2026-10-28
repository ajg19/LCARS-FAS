# TO DO — LCARS-FAS

Reverse chronological — newest first. Completed items are marked **DONE**. Items with no recorded date are grouped at the bottom rather than guessed at.

## 2026-10-28 — EO panel: draw every source the right way (image overlays first)

Not every EO source makes a picture. Of the 54 sources in `enterpriseCrewOutput/uhura_eoConsolidatedApiTable_2026-10-25.xlsx`, 21 produce imagery that can be laid on the Leaflet map as tiles; the rest give numbers (gas columns, heights along a track, profiles through the atmosphere) that need a different display. Column S of that workbook ("Suggested visualisation") records a suggested display for each source, and `0_tools/buildEoOptions.py` carries its class word into `EO_SOURCES` as `visualisation`. Google Earth Engine is out of this exercise (a platform, not a dataset). We are doing the image overlays first. **Done 28 Oct (Al to check by eye):** choosing any other source, then SELECT or TGT FOCUS, prints NOT YET AVAILABLE in the middle of the map and clears the old outlines and chip.

| Class | Sources | Display |
|---|---|---|
| IMAGE OVERLAY | 21 | Picture tiles on the map. Next step: nine Element 84 tiles (3 x 3) for the chosen source, then the other overlay sources one at a time |
| GRID MAP | 14 | One quantity (gas column, soil moisture, rain rate) as a colour-scaled overlay |
| TRACK PLOT | 5 | Value along the orbit, with the ground track on the map |
| PROFILE PLOT | 5 | Value against height (sounders, radio occultation) |
| CURTAIN PLOT | 3 | Vertical slice along the track (CALIPSO, EarthCARE, GPM radar) |
| POINT MARKERS | 3 | Fires, lightning, GEDI footprints |
| VECTOR FIELD | 1 | Wind arrows (ASCAT) |
| GRID MAP + ELEVATION PROFILE | 1 | Copernicus DEM |
| EXCLUDED | 1 | Google Earth Engine |

**Also done 28 Oct (Al to check by eye):** two new settings under the filters, MAX CLOUD COVER (10, 25 default, 50%) and MAX LOOKBACK (24 hrs, 1 week, 1 month, 3 months default, 1 year); SATELLITE moved to the bottom of the left column; rows closer together; the current Sentinel-2 search uses both settings. Errors (NOT YET AVAILABLE, NO CLEAR SCENE, IMAGE FETCH FAILED) show mid-map in red, LCARS style, 3x the button text. Cloud is judged on the whole scene for now; the 3 x 3 block check is part of the generic algorithm.

**Also done 28 Oct (Al to check by eye):** the 3 x 3 block is gone. The TGT LOCN form has an AREA selector (5, 10 default, 25, 50, 100 km square); TGT FOCUS outlines that square, fits the map to it and downloads enough Sentinel-2 (Element 84) to cover it as one image, read from coarser overviews for the big areas (at most 1250 pixels across). RESOLUTION now only filters the SOURCE table, as "this fine or better"; four sources with no stated resolution drop out when it is set (COSMIC-2 x2, Sentinel-3 altimeter, Swarm). An area past the scene edge shows the part with data.

**Bug found and fixed 28 Oct (browser test):** the imagery was downloaded and placed correctly but hidden: the country shapes (opaque, z-index 200) were painted over it. It now has its own map pane above them, and the amber outline sits above the picture. Confirmed in the built-in browser at 10 km over London (4.6 s).

**To do:**
1. Measure the first real downloads (bytes, requests, seconds in the IMAGERY block) for each AREA; join neighbouring scenes for areas that cross a scene edge; judge cloud over the area itself, not the whole scene.
2. Per-source fetch code for the other 20 image-overlay sources (many need accounts or other APIs).
3. Later: the non-image classes, starting with the simplest (GRID MAP, TRACK PLOT).

## 2026-10-24 — Space weather: build, deploy and charts

Plans: `0_documentation/plans/spaceWeatherIngestionPlan.md`, `spaceWeatherChartsPlan.md` (decisions in sections 13 to 15, display notes in 14), `chartCorePlan.md`, `spaceWeatherCreditsDraft.md`. Spock's reports are in `enterpriseCrewOutput/`. Everything built is on DEV only; nothing is deployed and nothing is committed (Al decides). Standing rules: ask Al before delegating to any agent and always before Spock; human-pace requests to other people's servers; Al does the visual checks.

**DONE on DEV (24 Oct)**
- Ingesters, all with tests: SWPC, GFZ, DONKI, GCR (Oulu and Dome C), SILSO, TEC (CODE daily 09:15 UTC; GloTEC 3-hourly, 7 days kept); publish into `siteWeather.db`; weather API endpoints incl. `aurora-at`, `tec-*`; database diagrams in `0_documentation/databases/`.
- Spock's data fixes: Newell coupling, OVATION oval edge, F10.7 burst flags and cleaned series, centred 81-day mean, neutron monitor stamps, GloTEC anomaly and quality flag documented.
- GFZ backfill to 400 days; a slow 500-day backfill of the missing stretch ran overnight from 24 Oct 21:53 UTC (8 requests; log `gfzSlowBackfill.log` in the session scratchpad).
- Chart helper refactor: `assets/chartCore.js` now serves LAUNCHES and ON-ORBIT (incl. pie and stacked columns); Al checked both visually: fine.
- Credits, DATA SRCES, METHOD, USAGE and the ABOUT texts updated in `assets/acknowledgments.html` and `assets/lcars.js`.
- Bug #11 fix (scroll to top in `showSection()`), bar colours Option A, SUN NOW spacing: applied, Al to confirm by eye.

**IN PROGRESS**
1. **Space-weather charts, in stages** (Scotty, the one familiar with the helper; Al checks each stage by eye and says when to go on):
   - 3a: extend `chartCore.js` (UTC time axis, log axes, gaps, hatched forecasts, event markers, stacked panels, signed areas, inverted second axis, detailed tooltips) and build the first chart, K1 L1 solar wind, on SOL DRVR.
   - 3b AURORAE (globe, N POLE, S POLE buttons on the right; contoured OVATION oval); 3c rest of SOL DRVR and ERTH NOW (storm strip as the primary chart); 3d HF COMMS; 3e GCR; 3f SAT COMMS (TEC; CODE default, button for GloTEC; anomaly greyed where observed is false); 3g LEO DRAG (waits for item 3 below).
   - Rules: pill-bar titles for NOW and PREDICTIVE, detailed tooltip on every chart, spacecraft named with location and light-seconds, forecasts hatched or dashed.

**OPEN (waiting for Al)**
2. Verify the overnight GFZ backfill. It finished (all 8 requests succeeded, log `gfzSlowBackfill.log` in the session scratchpad). Still to check: 500 days held, no gaps, and the centred 81-day F10.7 mean covers the whole 13 months. Not yet assigned; ask Al who does it (Scotty is the natural choice).
3. Space-Track history table (`gpHistory`) and archive: awaiting go-ahead; the drag index and decay-rate charts wait for it.
4. Cron jobs and deployment (parked by Al on 24 Oct, not dropped): DRY_RUN, deploy, run the SWPC jobs once by hand on LIVE, decide how the history reaches LIVE, install nine cron lines (`swpcFast`, `swpcSlow`, `swpcMaps`, `swpcPrune`, `gfz`, `donki`, `gcr`, `gcrMonthly`, `silso`) plus the TEC ones (`tecCode`, `tecGlotec`), then `checkLiveDeployment.py`. Needs the phone hotspot.
5. Cron monitoring and alerts (parked): server-side watchdog by email plus an external dead-man's switch.
6. Credits to verify: SOLAR-1 as the active L1 spacecraft, CODE terms and prediction DOI, the SWPC public-domain statement, Kyoto credit form for Dst, the Newell citation, SILSO DOI; Space-Track citation for the drag index when built.
7. Al's checks by eye: bug #11 on EO, bar colours, SUN NOW spacing, ABOUT control-area text fit.
8. Smaller: DOMB (second Dome C station) not stored by choice; two unanswered Scotty questions on TEC (NmF2 step 1e10; the observed-to-forecast join rule) stand as engineering judgement; GloTEC `quality_flag` meaning documented but display wording still to write.
9. ~~Kill the stray dev server (PID 10216)~~ done by Al, 25 Oct. Restart the dev server after any `server.py` change.

### AURORAE TO-DO (package)
Built on DEV 25 Oct: `assets/weatherAurora.js`; `weatherMap.js` gained polar/globe projections and contours; `tec-latest` takes `fields` (40% smaller); `checkLiveDeployment.py` lists the weather assets (it will report them missing on LIVE until deployed). `chartCorePlan.md` sections 21-23. Every view in the charts plan now exists on DEV. Structurally checked only.

*Al's decisions*
- GLOBE / N POLE / S POLE now sit under the text beside the oval map (Al's order, 25 Oct); the control area keeps its ten buttons.
- One OVATION map, no "now / +30 to 90 minutes" switch (OVATION's valid time is already 30-90 minutes ahead).
- 27-day recurrence shown as Ap, not Kp.
- Provisional choices: Kp-needed table from NOAA's scales (Kp 4 = 65 deg, Kp 3 or less = 67 deg), oval colour bands, Sun below -12 deg as "dark".

*Factual checks (Spock, only if Al approves; batch)*
- Kp-needed rule and dipole pole for geomagnetic latitude; "low on the horizon from about X - 5 deg" rule of thumb.
- Contour levels (5, 10, 20, 40, 60), bands, index-5 dashed as "camera only".
- 27-day Ap recurrence and its correlation as "how much repeats".
- -12 deg dark limit for faint aurora; Moon accuracy (about 1 deg, parallax omitted).
- DEFS page still carries Spock's Iceland examples (the AURORAE view itself names no place).

*Al's visual checks:* AURORAE (13-point list in Scotty's report), SAT COMM (GLOTEC/ANOMALY still work, lighter download), ERTH NOW forecast grid outline, HF COMM, LEO DRAG, SOL DRVR unchanged.

### SAT COMMS, TEC lamp and YOUR PATH TO-DO (package)
Built on DEV 25 Oct after the TEC ingesters were run by hand (125 tecMaps rows): `assets/weatherSat.js`, `weatherTec.js`, changes to `weatherHf.js`, `weatherMap.js`; `server.py` gained `/api/weather/tec-summary`. `chartCorePlan.md` sections 19-20. Structurally checked only.

*Al's decisions*
- Approve or change the provisional GNSS lamp rule: worse of (a) third-largest |anomaly|/30-day median, amber 60%, red 100%, flag>=3 and median>=10 TECU, and (b) highest observed TEC 125 / 175 TECU; grey if map over 6 h old.
- D-RAP at chosen places as a time series (a `publishSite.py`/ingestion change)? Until then YOUR PATH has only the "now" ring.
- Add a `fields` option to `tec-latest` (cuts about 35% off the GloTEC download)?
- Button labels (CODE (BERN), NOAA GLOTEC, ABSOLUTE, ANOMALY, TODAY, +1 DAY) and "+4 DAYS" instead of "+5 DAYS" (CODE's 5-day file covers day 5 only).
- Pressing GLOTEC or ANOMALY makes the server fetch from NOAA, at most every 30 minutes (the approved design).

*Factual checks (Spock, only if Al approves; batch)*
- Lamp thresholds; ICAO TEC pair 125/175 for a GNSS lamp.
- Dipole-model B-parallel for the Faraday figures (Reykjavik about 47 uT vs 50 in DEFS).
- Inferred foF2 (constant equivalent slab thickness calibrated against GloTEC, 300 km fallback): defensible? stated uncertainty?
- MUF(3000) about 3 x foF2 within 20%.
- Band table frequencies (S 2.2, X 8.2, Ku 12, Ka 26 GHz) and S4 proportional to f^-1.5 relative to L-band.
- STORM RISK cut at Kp 4 and 5; anomaly band set (+/-2, 5, 10 TECU).

*Not built:* AURORAE; D-RAP history at a place; measured foF2; drag index and decay-rate chart (gpHistory).

### GCR, HF COMMS and LEO DRAG TO-DO (package)
Built on DEV 25 Oct (stages 3e, 3d, 3g), structurally checked only: `assets/weatherGcr.js`, `weatherHf.js`, `weatherDrag.js`; `server.py` serves `/api/on-orbit/chart?name=exposure`. `chartCorePlan.md` sections 13-16 record the build; section 16 lists what is not built.

*Not built, and why*
- HF COMMS: YOUR PATH and the GNSS lamp were built 25 Oct once TEC was on DEV (`chartCorePlan.md` section 19); still missing: a D-RAP time series at the visitor's place and any measured foF2. SAT COMMS was built the same day. **D-RAP world map built 25 Oct** (`assets/weatherMap.js`, reusable for AURORAE and SAT COMMS; `chartCorePlan.md` section 17); shown at 5 MHz or more or during a proton event, otherwise on request ("Show the map anyway").
- LEO DRAG: the FAS drag index and decay-rate-against-altitude chart wait for the Space-Track `gpHistory` table (item 3 above); PASS TIMING belongs to GS OPS.
- AURORAE (3b) and SAT COMMS (3f) were built on DEV on 25 Oct (`chartCorePlan.md` sections 19 to 22). Every view in the charts plan now exists; only what waits on data or decisions is left (drag index and decay rate: `gpHistory`; a D-RAP history; measured foF2; cron, deployment, monitoring).

*Al's decisions*
- LEO DRAG window for THE ATMOSPHERE BREATHES: Scotty used 90 days (plan said 30 to 90).
- Accept the AVIATION BOARD lamp thresholds (HF absorption 5 and 15 MHz; PCA S1/S3; flare R1/R3), indicative only.
- Accept the Forbush flag rule (3-hour mean at least 2 percentage points below the 5-day high); it is Scotty's.
- Accept the VLEO shading ceiling of 450 km (from `orbitStats.py`).

*Factual checks (Spock, only if Al approves; batch with the others)*
- GCR: Oulu pressure coefficient about 0.77% per mbar (taken from the Dome C script); Dec 2008 and Dec 2019 cycle minima.
- HF: D-RAP wording (HAF = highest frequency with noticeable absorption); the X-ray term HAF = (10 log10 F + 65)/(cos chi)^0.75; the lamp thresholds; whether the GNSS lamp should later be driven from TEC.
- LEO DRAG: mean altitude understates the exposure of eccentric orbits; model citations (Picone et al. 2002; Bowman et al. 2008, AIAA 2008-6438).

*Al's visual checks:* GCR, HF COMM (now with the D-RAP map: Scotty's list, 25 Oct) and LEO DRAG views (hard-reload with Disable cache; tiles, charts, tooltips, resize, console clean). Scotty also fixed a tooltip bug in the ERTH NOW forecast grid (cells were not hoverable); check that too.

### ERTH NOW TO-DO (package)
ERTH NOW is built on DEV (25 Oct), structurally checked only: tiles, NOAA scales, the storm strip (five rows), K3 geomagnetic activity, Kp SWPC vs GFZ, K4 auroral power, K7 three-day forecast grid, forecast chances, and the CME timeline reused. Code in `assets/weatherEarth.js`.

*Al's decisions*
- Accept wind speed and Bz on their own rows rather than the single "Bz and speed" row the plan sketched (rule 1).
- Add M and X flare markers to the storm strip? (Not added: Al asked for CME launch, arrival and shock only.)
- Accept "Kp so far" shown as ">= x" for the block in progress.
- Accept FORECAST CHANCES showing the highest G level per day derived from the Kp forecast, since NOAA's stored feed gives a level, not a probability.
- The visitor's own Kp outline on the forecast grid is left for AURORAE.

*Factual checks (Spock, only if Al approves; batch with the SOL DRVR ones)*
- Scales feed: is the earlier of the two stored rows the 24-hour maximum and the later the current level (SWPC's "-1" and "0" entries)?
- 3-day forecast issue times (tooltip says about 00:30 and 12:30 UTC, marked [verify]).
- Auroral power wording (NOAA and EUMETSAT polar orbiters at about 850 km), the citation Fuller-Rowell and Evans 1987 (JGR 92, 7606), and the typical values (quiet 10-25 GW, active 50-100, storm several hundred).
- Dst thresholds (-30, -50, -100, -250) and the four observatories (Hermanus, Kakioka, Honolulu, San Juan).
- NOAA counts: about 1,700 G1 storms and about 4 at G5 per cycle; 10-11 May 2024 reached G5.

*Al's visual check of ERTH NOW:* see Scotty's stage report (hard-reload with Disable cache; tiles, scales, storm strip, K3, K4, forecast grid, CME timeline; resize; console clean; other views unchanged).

### SOL DRVR TO-DO (package)
SOL DRVR is built on DEV (stages 3a and 3c, 24-25 Oct); K1, flares and particles, flare record, long view, solar cycle, CMEs on the way and the outlook are all drawn. Scotty checked structurally only. Open items:

*Al's decisions*
- A. **Round K1's `derivedNewell` at publish.** Its long decimals are about 40% of K1's data (about 33 KB gzipped per day, about 100 KB at three days). Rounding saves roughly 20 KB at three days; Scotty already did this for the X-ray and proton series (`sig=4` and `sig=3`), so for K1 it is a one-word change. Al has not decided.
- B. **Confirm the NOW (amber) and PREDICTIVE (violet) pill-bar colours** when checking the page.
- C. **Design choices Scotty raised:** keep the STEREO-A "may return, +/-3 days" strip; accept his wording "Not shown: N other CMEs in the last 7 days (slower, and not predicted to reach Earth)"; accept F10.7 and Ap stacked in two panels instead of Ap as bars on a right-hand axis (rule 1 allows a second axis only for the same process); choose the Ap source: the 45-day forecast product as drawn, or the weekly 27-day outlook (`swpcOutlook27Ap`), which is stored but not drawn.

*Factual checks (Spock, only if Al approves; batch into one call, expensive, ask first)*
- The 5 mV/m "strong driving" shading threshold and the E = v x Bs and Newell formulas with the paired scales (10/40,000, 20/80,000, 50/200,000).
- Cycle starts hard-coded as SILSO smoothed minima: Dec 2008 (cycle 24) and Dec 2019 (cycle 25).
- CME arrival error of about 10 hours, with citation Wold et al. 2018, J. Space Weather Space Clim. 8, A17.
- STEREO-A distance today (the tooltip says "up to about 500 light-seconds", marked [verify]).
- The tooltip's rough guide "a G1 storm is about Ap 40 for the day" (Scotty's own wording).
- The proton floor labelled "GCR" and the tooltip wording on burst days.
- Leaving out the X-ray short channel (contaminated).

*Housekeeping (when deployment is un-parked)*
- Add `chartTime.js`, `weatherCharts.js`, `weatherMap.js`, `weatherTec.js`, `weatherSat.js`, `weatherAurora.js`, `weatherCoast.json` (DONE 25 Oct: the checker lists them; not run against LIVE) (and later chart files) to `0_tools/checkLiveDeployment.py`; it lists the deployed assets but not these.

*Al's visual check of SOL DRVR* (check list in Scotty's stage 3c report): hard-reload with DevTools "Disable cache"; bars and spacing; each chart and tooltip; resize; switch views; console clean; SUN NOW, LAUNCHES and ON-ORBIT unchanged.

Reminders elsewhere: Sybilla contract and SLI, Mon 26 Oct; database refactor step 15 and the Scotty quick wins, 4 Nov; crib sheet to USB.

## 2026-10-09 — News filtering, retention and topic histogram **(DONE locally — not yet deployed)**

On branch `newsFilters`. Filler (entertainment, shopping, daily features, NASA admin) is never stored; `scripts/pruneNews.py` deletes stored filler, duplicate titles and anything older than six months, then VACUUMs; `scripts/tagNews.py` tags articles for the ten news filter buttons and stores per-topic counts for the control-area histogram. All run after every `readNews.py`. Local `space_news.db` cleaned (415 → 337 articles) and tagged; backup at `ingestionDBs/space_news.db.bak` (not to be committed). Documented in the News section of `designAndArchitecture_0.4.docx` (v0.6), plus `testPlan_0.1.docx` and `installationAndStartupGuide_0.1.docx` (both v0.2); pre-change copies in `0_documentation/rollback/*.pre-news-filters.bak`.

Still to do:

- **Deploy**: `DRY_RUN=1 0_tools/deployToGoDaddy.sh` first, then for real; over SSH back up the live `space_news.db`, run `python3 scripts/pruneNews.py --dry-run`, then `pruneNews.py` and `tagNews.py`. Cron needs no change.
- **Commit** the two-half histogram layout (font matching the buttons, gold labels) — the single-histogram axis version is `1838596`.
- ~~**Decide**: requirements vs. buttons~~ **DONE** — `swareRqts_0.2.docx` (v0.3) revised to match the buttons; country-of-origin filtering dropped.
- **Decide**: ORGS still matches funding/earnings terms, so every FINANCE story also appears under ORGS.
- `NASA's PUNCH Sharpens Solar Storm Forecasting` is now untagged (it was space weather only) — add solar missions to DEEP SPACE?
- Button label is `03-GRND SGMT`; Al's ordering list wrote `GRD SGMT` — confirm which.
- ~~`0_tests/test_server.py`: 4 stale `parse_inclination_deg` tests~~ **DONE** — removed (the function and its only caller were deliberately removed from `server.py` in `324de59`); suite now 69/69 passing.
- ~~Node-era text in the docs~~ **DONE** — design doc (tech stack, hosting, supervision, scheduling, script names, LCARS-FAS branding), test plan, install guide and `systemArchitectureDiagram.svg/.png` (also re-embedded in the design doc) now describe the Python / Passenger / cron setup; Claude Opus 5.5 added to the AUTHORS cell of every doc edited. Pre-change copies in `0_documentation/rollback/*.pre-node-era-cleanup.bak`. `funcReqts_0.2.docx` needed no change.

## 2026-08-13 — Investigate Three.js as a CesiumJS alternative

Spotted on eclipses.bogachev.fr (self-hosted, ~257KB) driving a custom sky/starfield/corona WebGL scene. Noted in `designAndArchitecture_0.4.docx` (Tech Stack / Core Technologies, and the Client-Side Files self-hosted-libraries bullet) as an alternative under consideration for panels needing a custom 3D scene rather than a georeferenced globe — e.g. the star chart, the orbital-mechanics demonstrator — where CesiumJS's much larger footprint (typically several MB, a real bite out of the sub-5MB budget) may not be earning its keep. Not yet adopted; CesiumJS remains the documented plan for anything needing an actual georeferenced globe/terrain/imagery. Worth a real spike/prototype to see how much of Cesium's out-of-the-box functionality would need hand-building on top of Three.js for the panels in question.

## 2026-08-12 — Test + code-review workflow **(DONE)**

Set up on-demand test + code-review workflow. `0_tests/test_server.py`: pytest suite (see `requirements-dev.txt`), WSGI-level smoke tests against `server.py`'s 5 API endpoints + static file serving + pure-logic unit tests, run against the real local DBs, no mocks. `pytest 0_tests -v` to run.

Each run of either workflow writes a timestamped `.md` report: `0_testReports/YYMMDD_HHMMZ_testReport.md` and `0_codeReviews/YYMMDD_HHMMZ_codeReview.md` (UTC). Unlike `push.log`/`reviewLog.txt` before it, these **are** committed + pushed (not gitignored) so they're viewable on GitHub's web UI, rendered as markdown.

Naming convention adopted repo-wide: any directory that's dev-only and excluded from the GoDaddy deploy gets a `0_` prefix (sorts to the top in Explorer, visually distinct) — `0_documentation/`, `0_tests/`, `0_testReports/`, `0_codeReviews/`. `documentation/` renamed accordingly. `ingestionDBs/` is **not** prefixed — it's excluded from the deploy *sync* to avoid clobbering the live DBs, but the directory itself is very much meant to exist on the server.

## 2026-08-12 — Post-commit auto-push hook **(DONE)**

`.git/hooks/post-commit` now auto-pushes every commit to origin (AJG - laptop → GitHub `ajg19/LCARS-FAS`) and prints a clear success/failure message. Also logs each result to `.git/hooks/push.log` for a persistent history.

## 2026-08-12 — `nodePersistenceTest.js` result **(DONE)**

Checked via SSH: the process is dead. It ran unsupervised for **~16 hours** (first heartbeat 2026-08-10 09:28:22 UTC, last 2026-08-11 01:31:10 UTC, 963 lines at ~60s intervals, then nothing) before being silently killed — no error in the log, it just stops.

**Answers the original question**: GoDaddy shared hosting does reap long-running background processes not registered with Application Manager/Passenger, somewhere around the 16-hour mark. Anything relying on `nohup ... &`-style background scripts (e.g. ingestion cron jobs) needs to either be short-lived/cron-triggered, or registered as a proper Application Manager app — a bare background process will not survive.

Leftover files (`nodePersistenceTest.js`, `persistenceTest.log`) are still sitting under the old `~/public_html/LCARS-FAM/` on the server (pre-Python-migration path) — not yet cleaned up.

## 2026-08-10 — `nodePersistenceTest.js` started

Started via SSH on GoDaddy 2026-08-10 ~02:28 (unsupervised, no daemon manager, just `nohup node nodePersistenceTest.js &`), writing to `persistenceTest.log` every 60s, to test how long it survives unsupervised. See result above.

---

## (undated) — Deploy script **(DONE)**

Write a script to deploy LCARS-FAS to GoDaddy (automate the scp/tar upload + re-sync we've been doing by hand). **DONE** — `0_tools/deployToGoDaddy.sh`.

## (undated) — Refactor duplicated object-list rendering

Check whether the code that renders the list of selected/plotted objects is duplicated across places (e.g. `renderOrbitalObjectsList` and the ADD OBJ / DEL OBJ results table rendering) and refactor to a single shared place if so.

## (undated) — SHW ALT button label sync check

Check the ON/OFF label stays in sync with whether altitude is actually being displayed under object names (e.g. toggle off then on, and check after GRD TRCK is toggled off/on too).
