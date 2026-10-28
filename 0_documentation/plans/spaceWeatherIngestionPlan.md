# Space weather: ingestion and archiving plan (v2)

Status: draft, 24 Oct 2026; decisions of 24 Oct 2026 folded in (Kyoto AE dropped, 90-day delete retention, 90-day first backfill). Built on DEV by 24 Oct 2026 (not deployed): SWPC, GFZ and DONKI ingestion, the daily prune, the `weather` publish, the `/api/weather/*` endpoints, OVATION and D-RAP. **TEC built the same day** (CODE and GloTEC: `ingestionTEC.py`, `ingestionTEC.db`, jobs `tecCode` and `tecGlotec`; section 2a), **not built:** `archiveHistory` and the Space-Track `gpHistory`, the frontend. This replaces the outline of the same date. Source facts are from `enterpriseCrewOutput/spock_spaceWeatherReport_2026-10-22.md` (feeds checked 22 Oct 2026). Architecture follows `dbRefactorPlan.md`.

## 1. Principles

- **Ingest everything once, in one pattern**, so code, tables and tests are consistent.
- **One ingestion database per source** (`ingestion<Source>.db`); **one site database per kind of data** (`siteWeather.db`). Visitors never touch an ingestion database.
- **Decision C:** publish only after a run that changed something; a failed run publishes nothing; stale sources show in the freshness table and never block.
- **Cron per source** through `scripts/runIngestion.py`, under the shared writers' lock. Standard library only, Python 3.9.
- **Be kind to other people's servers.** Before any source goes in, its load is compared with a human's (section 3). Fetch once and store; never re-download what we hold; tests use recorded fixtures only; human-paced requests; when in doubt, ask Al.
- **All dates and times in UTC.**
- **Space-Track's terms** (read 24 Oct 2026): no transfer of data "including the analysis of data" without approval; Basic Services gives blanket approval for TLEs, OMMs and the SATCAT with citation; analyses published need citation; nothing on commercial use or on ownership of derived work. We cite "NORAD satellite catalogue (via Space-Track)". The raw archive stays private. Before any consulting use of the drag work, ask Space-Track in writing.

## 2. Sources, databases and scripts

| Source | Database | Ingestion script | Jobs | Feeds |
|---|---|---|---|---|
| NOAA SWPC | `ingestionSWPC.db` | `ingestionSWPC.py` | `swpcFast`, `swpcSlow` | F10.7, L1 field and plasma, GOES X-ray, protons and flares, radio flux and events, Kp, Dst copy, NOAA scales, forecasts, D-RAP, OVATION, hemispheric power |
| CODE (University of Bern) and NOAA GloTEC | `ingestionTEC.db` | `ingestionTEC.py` | `tecCode`, `tecGlotec` | Total electron content maps; see section 2a |
| GFZ Potsdam | `ingestionGFZ.db` | `ingestionGFZ.py` | `gfz` | Kp, ap/Ap, Hp30/Hp60, observed and adjusted F10.7, sunspot number |
| NASA DONKI | `ingestionDONKI.db` | `ingestionDONKI.py` | `donki` | CME, HSS, GST, SEP, FLR events |
| Space-Track | existing `ingestionSpaceTrack.db` | existing script, new `gpHistory` table | existing `spaceTrackFull` | B*, ṅ, altitudes per object per day |

**2a. TEC (total electron content), built 24 Oct 2026**

- `tecCode`, daily (cron 09:15 UTC): CODE's four IONEX files (rapid for the previous day; the 1, 2 and 5-day predictions), each 25 hourly maps of 71 x 73 cells, from `https://www.aiub.unibe.ch/download/CODE/` (redirects to a public S3 bucket). A file's date is the day its maps cover; CODE issues all four at about 08:00 to 08:15 UTC, so an earlier run finds nothing (HTTP 404, noted, not a failure). One GET per file, only for files not already held (`sourceFiles`), 2 to 5 s apart; the rapid file of two days back is also tried if missing. No directory listing (the base URL has none).
- `tecGlotec`, every 3 hours (cron `10 */3`): the newest map named in the directory listing `products/glotec/geojson_2d_urt/` (the index JSON is not used); one listing (38 KB) and, if the map is not held, one 2.4 MB file; the computed name (now - 30 min, at a :x5 minute, one step back on a 404) if the listing fails.
- `ingestionTEC.db`: `tecMaps` (source, product, issuedUtc, validUtc, kind, `gz` = the compact map as gzipped JSON), `sourceFiles`, and the shared `samples` (global maximum TEC and where: `codeTecMax*` for the observed maps, `glotecTecMax*`), `ingestionRuns`. Maps are deleted 7 days after their valid time. About 7 MB in all: a CODE map is 7.3 KB, a GloTEC map 22 KB, 168 + 3 x 168 CODE maps and 56 GloTEC maps.
- Published into `siteWeather.db` (`tecMaps`, copied whole; the summary series with the other samples). Served by `/api/weather/tec-latest` (newest GloTEC, refreshed from NOAA on demand at most once in 30 minutes, one fetch at a time, memory only), `tec-code` (one CODE map: kind, day, hour), `tec-index`, `tec-at` (TEC and foF2 at a place) and `tec-series` (7 days at a place). foF2 = 8.98 sqrt(NmF2) is indicative.
- GloTEC fields (Spock, 24 Oct 2026; source https://spaceweather.gov/products/glotec): **confirmed** - `anomaly` is the deviation of TEC from its 30-day median; `quality_flag` is the mean number of F-region observations per vertical profile, rounded up, capped at 5 (0 = none: the TEC relaxes to IRI-2016 climatology driven by F10.7, so the anomaly there is the model's seasonal and F10.7 response, not observed weather; 72% of cells; 5 = dense, 14%; it measures coverage, not error size). **Inferred (about 95%)** - the anomaly is in TECU, the median is per cell at the same time of day over the preceding 30 days, sign = current minus median. Unknown: whether today is in the 30 days, the time matching, gap handling. The API says so: `tec-at` and `tec-series` carry `observed` (flag above 0), `anomalyReliable` and the unit labelled inferred; in `tec-latest` the `q` list carries the flag (the front end greys the anomaly where q is 0).
- Load: CODE about 0.75 MB a day (4 files of 0.2 to 0.33 MB); GloTEC 8 x (2.4 MB + 38 KB) = about 20 MB a day, as budgeted in section 3.

**Ancillary scripts and files**

| Item | Where | Purpose |
|---|---|---|
| `scripts/archiveHistory.py` | server, cron monthly | Rolls rows older than the live window out of an ingestion database into a compressed archive file |
| `scripts/restoreArchive.py` | server or laptop | Loads one archive month into a scratch database for analysis; never into a live one |
| `0_tools/pullArchives.py` | laptop, run by hand | Copies new archive files from the server (over SSH, paced) with checksums |
| `databases/archive/` | server | `<source>_<series>_YYYYMM.db.gz` plus `manifest.json` (file, row count, date range, SHA-256) |
| `scripts/spaceWeatherSamples.py` | server | Shared helper: the `samples` and `events` tables, upsert, retention, aggregates |

New constants in `dbPaths.py`: `SWPC_DB`, `GFZ_DB`, `DONKI_DB`, `SITE_WEATHER_DB`, `ARCHIVE_DIR`.

**Kyoto AE is dropped (decided 24 Oct 2026):** real-time AE is plots only, and the provisional files are "not for redistribution"; the substitutes are L1 Bz and speed, SWPC 1-minute Kp, hemispheric power and OVATION. (Dst, which SWPC republishes, stays.)

Link-only, not ingested: DLR (ROTI), Veðurstofa (cloud and aurora), ionosondes (MUF). Density models (NRLMSIS, JB2008) are code, not data: a later phase.

## 3. Load budget (to be agreed before building)

Per day, estimated from the sizes Spock measured (gzipped). A person with SWPC's dashboard open and refreshing is the human comparison; I estimate that at roughly 10 to 30 MB a day, which is unverified.

| Job | Cadence | Per run | Per day | Note |
|---|---|---|---|---|
| `swpcFast` (scales, 1-min Kp, protons, X-ray, hemispheric power) | 15 min | ~50 KB | ~5 MB | small feeds only |
| `swpcSlow` (L1 field and plasma 242 KB, F10.7, forecasts, radio flux, Dst, Kp) | hourly | ~370 KB | ~9 MB | 24-h files overlap and upsert, so nothing is lost |
| GloTEC maps (`tecGlotec`) | every 3 h | 2.5 MB each, sent uncompressed | ~20 MB | heaviest item; every 6 h would halve it |
| CODE maps (`tecCode`) | daily | 4 files, 0.2 to 0.33 MB | ~0.75 MB | built; one GET per file not already held |
| `gfz` | hourly | ~3 KB | ~70 KB | tiny |
| `donki` | hourly, last 7 days | ~55 KB | ~1.3 MB | |
| `swpcMaps` (OVATION 150 KB, D-RAP 42 KB, both gzipped) | hourly | ~200 KB | ~5 MB | separate job so `swpcSlow` is unchanged |
| `swpcPrune` | daily | no requests | 0 | deletes 1-minute rows older than 90 days |
| Space-Track | existing passes | no extra requests | 0 | history is written from the daily full pass |

Total from SWPC is about 35 MB a day, which is about a person's dashboard left open all day. Decision for Al: accept this, or lengthen the cadences (L1 shows a 1-hour warning, so hourly adds up to an hour of delay for that panel).

## 4. One ingestion pattern

Each script is shaped like `ingestionSatNOGS.py`: `openDb(path)`, `store…(db, records)`, `runIngestion(db, fetch)`, `main()`.

- **Storage:** a long table `samples(series, tsUtc, value, quality)`, unique on (series, tsUtc), written by upsert, so a re-run is harmless. DONKI also gets `events` (type, startUtc, id, JSON).
- **Runs are recorded** with `trackRun`; the change count is new or changed samples.
- **Validate before storing:** check each feed's shape and reject the whole feed on a surprise (2026 changed several), recording a failed run. Handle known quirks: keep only L1 rows flagged `active`; separate the interleaved GOES channels; allow gaps (8% and 27% of L1 minutes missing).
- **Backfill:** `--backfill DAYS` on first run (GFZ and DONKI have archives; SWPC feeds hold 6 hours to 7 days). Done once, slowly. **Decided 24 Oct 2026: the first live run is `--backfill 90` for both GFZ and DONKI.** Not yet run.
- **Retention** (live windows): L1 and GOES 1-minute for 90 days (`LIVE_DAYS`), then the rows are deleted (no hourly means, no archive; `pruneOldOneMinute`, run daily by the `swpcPrune` job under the writers' lock); Kp (both `swpcKp` and `gfzKp`), ap, F10.7, sunspot number, Dst, DONKI events and the 5-minute protons kept in full; OVATION and D-RAP are stored as location-free summaries (per hemisphere: the maximum, where it is, and for OVATION the equatorward edge of the oval; hemispheric power comes from its own feed) plus the latest FULL global map, integer-coded. **Nothing is specific to one place** (decided 24 Oct 2026: auroral predictions and maps for anywhere on the planet): the value at any latitude and longitude is a lookup in the stored map (`/api/weather/aurora-at?lat=&lon=`). Map sizes: OVATION 181 x 360 integers, about 134 KB as JSON and about 3 KB gzipped on a quiet day (about 70 KB gzipped for pure random noise, the worst case); D-RAP 90 x 90 tenths of MHz, about 17 KB and about 1 KB gzipped. Panels fetch a map lazily (`/api/weather/map?name=ovation` or `drapGlobal`), never on first load.
- **Space-Track `gpHistory`:** `WITHOUT ROWID`, keyed (noradID, day), epoch as an integer, with B*, ṅ, mean motion, perigee and apogee; objects with mean altitude below 600 km (about 14,400 today, about 55 bytes per row, about 0.8 MB a day).

## 5. Archiving

| Data | Live window | Then | Permanent |
|---|---|---|---|
| `gpHistory` (per object per day) | 90 days (about 70 MB) | monthly archive, `spaceTrack_gpHistory_YYYYMM.db.gz` (about 24 MB raw, I expect 8 to 12 MB gzipped; untested) | daily aggregates by 20 km altitude band and Starlink against others: median B*, decay rate, drag index (about 1 MB a year); an events table (re-entries, altitude raises) |
| L1 and GOES 1-minute | 90 days | deleted, not archived | nothing |
| Everything else | in full | no archive | |

**Size of the 1-minute window at steady state.** Estimated from a scratch database filled with synthetic rows of the real series, units and quality labels (90 days; L1: 7 series with 85% of minutes present; X-ray: 2 series, every minute): L1 about 43 MB (769,000 rows), GOES X-ray about 17.5 MB (259,000 rows), about 60 MB together. This is a measurement of the table layout, not of a replayed live feed (the recorded fixtures are trimmed); real values may differ by some per cent.

How the monthly job works (`archiveHistory.py`, for `gpHistory` only, cron on the 1st, through `runIngestion`, under the writers' lock):

1. Select rows older than the window for one series.
2. Write them to a temporary SQLite file, `VACUUM INTO`, gzip it, write its SHA-256 and row count to `manifest.json`.
3. Verify by reading the archive back and comparing the row count.
4. Only then delete those rows from the live database, in one transaction, and record the run.
5. A failed or unverified archive deletes nothing.

Copy-off (`0_tools/pullArchives.py`, run from the laptop over the phone hotspot): reads the server manifest, downloads only files not yet held, one at a time with random gaps, checks each checksum, and never deletes anything on the server. Server archives are removed only by hand, once copies are confirmed. Losing the server's archive would force a re-download from Space-Track, so the off-server copy is part of the design.

Restore (`restoreArchive.py`): decompress one month into a scratch database, for recomputing a drag index definition or plotting an old object.

## 6. Publish

- New site file `siteWeather.db`, built by `publishSite.publish('weather')` from the ingestion databases: build a temporary file, check it, swap atomically, keep `.prev`.
- Holds downsampled series (recent at native resolution, 90 days hourly, longer daily), the latest global maps (OVATION at 1 degree, D-RAP at 4 x 2 degrees; GloTEC is trimmed to a 22 KB compact grid, its raw map is 2.5 MB; both TEC sources are kept 7 days in `tecMaps`), and derived series: F10.7A, storm flags, the drag index, decay rates.
- Checks before the swap: not empty, every series has recent data, none shorter than before.
- `runIngestion.SOURCES` gains the four new sources feeding `('weather',)`; Space-Track gains `weather` as a second site file.

## 7. Server and freshness table

- `site_db('weather')`, `SITE_FILES` and `LEGACY_FILES` in `server.py`.
- Endpoints `/api/weather/now`, `/api/weather/series?name=…&range=…`, `/api/weather/events?type=…&days=…`, `/api/weather/map?name=…` (compact arrays, gzip, ETag, cache headers) and `/api/weather/aurora-at?lat=…&lon=…` (aurora index and D-RAP absorption at any place, nearest cell, from the stored maps).
- `STATUS_SOURCES` rows with static labels: Space weather (NOAA SWPC), GFZ, DONKI, drag history, and the archive job.

## 8. Cron (via `setupCron.sh`)

| Job | Schedule |
|---|---|
| `swpcFast` | every 15 min |
| `swpcSlow` | hourly |
| `swpcMaps` | hourly (:25) |
| `gfz`, `donki` | hourly |
| `swpcPrune` | daily (04:50) |
| `archiveHistory` | 1st of each month |

Whether GoDaddy cron allows every-5-minute runs is unverified; 15 minutes avoids the question.

## 9. Tests and checks

- `0_tests/test_ingestion{SWPC,GFZ,DONKI}.py` against recorded fixtures in `0_tests/fixtures/`, no network.
- `test_archiveHistory.py`: archive, verify, delete in order; a failed verify deletes nothing; restore round trip. `test_pullArchives.py`: checksum and resume, with the SSH step stubbed.
- `test_publishSite` and `test_server` additions; `checkLiveDeployment.py` gains the weather endpoints and archive freshness; `testHarness.py` gains WEATHER rows (spine) and ingestion and archive rows (backend); `apiSnapshot.py` baseline before the frontend work.

## 10. Order of work

1. `dbPaths`, `spaceWeatherSamples.py` and its tests.
2. Space-Track `gpHistory` first among the data steps: every day without it is history lost.
3. `ingestionSWPC`, `ingestionGFZ`, `ingestionDONKI`, each with its tests.
4. `archiveHistory`, `restoreArchive`, `pullArchives`, with tests.
5. `publishSite` weather build and derived series; `runIngestion` and `setupCron.sh` entries; `server.py` endpoints and status rows.
6. Local run on DEV against the real feeds, paced and within the load budget.
7. Deploy: dry run first; install cron on LIVE; first runs backfill; verify over SSH (phone hotspot) and with `checkLiveDeployment.py`.
8. Frontend views (separate plan), docs (design, test plan, install guide, TOOLS_README), glossary additions (SWPC, DONKI).

## 11. Decisions needed

1. **Load budget:** accept about 35 MB a day from SWPC, or lengthen the cadences (section 3)? GloTEC every 3 h or 6 h?
2. **Space-Track:** ask in writing before consulting use; confirm the 90-day window and the below-600 km set.
3. **Licences:** Dst (Kyoto, republished by SWPC) is non-commercial and sunspot numbers CC BY-NC. Acceptable, given the open question on promoting consulting?
4. **GFZ against SWPC:** both give Kp and F10.7. Keep GFZ for the official values and Hp30, or drop it?
5. **Archives:** where to keep the off-server copy (laptop, Drive, both), and how long to keep the server's copies.
6. **Disk:** check the GoDaddy quota against about 100 MB in year one plus archives (about 100 to 150 MB a year, compressed).
7. **Models:** defer NRLMSIS and JB2008 to a second phase?
