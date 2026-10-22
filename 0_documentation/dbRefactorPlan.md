# Database and source refactor plan

Agreed 2026-10-21 (Al + Claude). Status: steps 1-12 done. LIVE migrated on 2026-10-21 at 23:04 UTC. Steps 13-15 remain; step 15's clean-up is due about two weeks after the migration. The step 9 questions are all settled. Decisions A-D are settled. LIVE still uses `ingestionDBs/` with the old file names, so `dbPaths.py` falls back to that folder and maps each new name to its old one until step 12.

## Conventions

- **Folder:** `databases/`, replacing `ingestionDBs/`.
- **`ingestion<Source>.db`:** one per external source, holding that source's raw data.
  - `ingestionSpaceTrack.db`, `ingestionCelesTrak.db`, `ingestionSatNOGS.db`, `ingestionGCAT.db`, `ingestionNews.db`, `ingestionGroundSegment.db`, `ingestionSkyCatalogue.db`.
  - Each is written only by its own ingest script and read only by the publish steps.
- **`site<Type>.db`:** what the website reads, one per type of data.
  - `siteOrbital.db`, `siteNews.db`, `siteSky.db`, `siteGroundSegment.db`.
  - Each is written only by its own publish step and swapped in atomically. The website opens them read-only.
- **`inbox<Name>.db`:** what the website writes to: `inboxBugReports.db`.
- **Source priority:** Space-Track (NORAD) is the primary orbital source; the source closest to NORAD wins.
- **Protection against locks and corruption** comes from one writer per database, plus whole-file atomic swaps (`os.replace`) of the site files.
- **Ingestion vs publish.** Ingestion fetches from a source and stores what it said: upserts into that source's `ingestion…` DB, so it is incremental. Publishing turns the latest ingested data into what the website shows. One publish of a site file:
  1. Read its ingestion DBs, read-only.
  2. Build `site<Type>.db.tmp` beside the live file.
  3. Check it: integrity and sanity.
  4. Keep the live file as `.prev`, then `os.replace` the `.tmp` into place.
  5. `server.py` notices the change and reconnects.

  If the check fails, nothing is swapped and the website keeps serving the previous version.
- **Site files are rebuilt from scratch on every publish, not patched.**
  - They are small: `siteOrbital.db` is about 22 MB; the rest are under 1 MB.
  - Stats and the source merge depend on all objects anyway.
  - A rebuild gives the same output for the same inputs, and the next run corrects any bad one.
  - Decayed or dropped objects disappear without any deletion logic.
  - Schema changes need no migrations.

  Revisit only if the step 9 timing on GoDaddy is slow or the data grows about tenfold. The fallback is copy-the-live-file-then-patch for `siteOrbital.db` alone.

## Decisions

- **A. DECIDED 2026-10-21: our own group rules, with CelesTrak definitive when available.** The groups (`active`, `stations`, `starlink`) are derived by our own documented rules, and any available CelesTrak group list overrides them for the objects it covers. Precedence per object:
  1. **CelesTrak:** membership from the latest successful CelesTrak fetch of that group.
     - Applies to objects launched before that fetch.
     - At step 6, settle how old a fetch may be and still count as "available" (suggest 14 days).
  2. **Recent-launch rule:** a payload launched in the last **3 months** is active unless proven otherwise, e.g. a later CelesTrak fetch leaves it out, or it has a decay date.
  3. **Our own rules:**
     - `active` = on orbit and no GCAT operations-end date (`gcatPayloads.tOp`). This matched CelesTrak for 97% of on-orbit payloads on the August DEV data.
     - `starlink` = SpaceX-owned (GCAT owner codes) or named `STARLINK*`.
     - `stations` = ISS and CSS modules plus crewed and cargo vehicles from GCAT payload classes. Check the GCAT codes first.

  A comment in the code next to the rules explains this precedence and the 3-month assumption.

  **Extended 2026-10-21 to the link-budget constellations.**
  - **Why.** `enrichEirp.py` takes a payload's downlink band, EIRP and receive gain from its constellation, matched by CelesTrak group. On LIVE's current data that gives 12,924 of 18,936 payloads constellation-grade figures. LIVE's groups have been frozen since August, so newer launches fall back to class estimates or "unknown".
  - **What changes.** Every group `CONSTELLATION_EIRP` uses gets its own rule, with the same precedence as above: CelesTrak's list when available, otherwise ours.
  - **Groups covered:** starlink, oneweb, kuiper, iridium-NEXT, globalstar, orbcomm, gps-ops, glo-ops, galileo, beidou, sbas, gnss, planet, ses, intelsat, eutelsat, telesat, qianfan, hulianwang, sar, spire, argos, sarsat.
  - **How each rule works:**
    - **Operator constellations:** a name pattern (`ONEWEB*`, `KUIPER*`, `IRIDIUM*` and so on), the GCAT owner code, or both.
    - **Function groups:** GCAT payload class, category or programme. These are sar, argos, sarsat, sbas and gnss.
    - Each rule is written and checked at step 9 against today's CelesTrak lists, reporting the agreement like the 97% figure for `active`.
    - A rule that can't reach a sensible agreement is listed in the plan, not used silently.
  - **Coverage of the recent-launch rule:** it applies only to `active`. Constellation membership doesn't expire.
- **B. DECIDED 2026-10-21: one site database per type of data.** One shared file only pays off for data that is joined or must stay mutually consistent, and that applies only within the orbital data. The site files are:

  | File | Contents | Size* |
  |---|---|---|
  | `siteOrbital.db` | Merged `orbital_objects`, groups, GCAT (only the tables and columns the site reads: `gcatLaunches`, `gcatOrgs`, trimmed `gcatObjects`), `gcatBrightness`, ON-ORBIT/LAUNCHES stats tables | ~22 MB |
  | `siteNews.db` | `articles`, `articleTopics`, `newsTopicCounts` | 0.2 MB |
  | `siteSky.db` | Stars, constellations, constellation lines, Milky Way, deep-sky objects | 0.4 MB |
  | `siteGroundSegment.db` | `ground_segment_assets` | 0.1 MB |

  \*Measured from the August DEV data, before indexes. `gcatLaunches` (4.6 MB) may shrink further by trimming columns.

  The landing-page freshness table is built from each site file's own copy of its sources' run history.

  Not in any site file:
  - the raw ingestion data;
  - the GCAT tables used only for building (`gcatPayloads`, `gcatParents`, `gcatDecays`, `gcatDebrisYears`, `gcatFiles`);
  - bug reports.
- **C. DECIDED 2026-10-21: publish after ingestion, from the last good data.**
  - **C1, trigger.** Each ingestion run that changed something ends by publishing every site file built from that source. The map from site files to sources is in `dbPaths.py`.
    - Space-Track, SatNOGS, CelesTrak or GCAT republish `siteOrbital.db`.
    - News republishes `siteNews.db`.
    - The ground-segment and sky builds republish their own files.

    A run that changed nothing publishes nothing.
  - **C2, failed or stale source.** Publish anyway, using each source's last good data.
    - A failed or stale source shows as such in the landing-page freshness table.
    - It never blocks the publish, so CelesTrak being blocked on LIVE never holds up orbital updates.
    - Data that looks wrong is still refused by the sanity checks.
- **D. DECIDED 2026-10-21: reference DBs are built on the laptop and carried by the deploy.**
  - `ingestionGroundSegment.db` (from `grndSgmntAssets_master.xlsx`) and `ingestionSkyCatalogue.db` (from XHIP and the d3-celestial data) have no online feed.
  - They are built locally, committed to git, and uploaded by `deployToGoDaddy.sh`. Every other file in `databases/` stays excluded from git and from the deploy.
  - On LIVE, the deploy (or the migration script) then publishes `siteGroundSegment.db` and `siteSky.db`.
  - The server never needs the xlsx, the star catalogues or openpyxl.
  - The ground-segment builder moves into the repo as `scripts/ingestionGroundSegment.py`, from `DEV/LCARS/rschGrdSgmt/build_ground_segment_db.py`.

## Steps

### Groundwork (no behaviour change)

1. **Bring DEV up to date.** Pull read-only copies of LIVE's databases to DEV, and keep a dated backup of each.
2. **Baseline.** Capture JSON from every API endpoint on the refreshed DEV data, for regression comparison.
3. **Shared modules.**
   - `scripts/dbPaths.py`: every DB path and name, plus the map from each site file to the ingestion DBs it is built from.
   - `scripts/common.py`: the `.env` loader, `http_get` (User-Agent and timeout), and one Space-Track client (single login, timeouts, logout).

   Point all scripts, `server.py` and `bugs.py` at them; remove the duplicated code.
4. **Rename the folder.** `ingestionDBs/` becomes `databases/`; update `.gitignore`, the excludes in `deployToGoDaddy.sh`, and the tests.

### One ingestion database per source

5. **Space-Track.** DONE 2026-10-21: `scripts/ingestionSpaceTrack.py` writes `ingestionSpaceTrack.db` (table `gp`), with tests in `0_tests/test_ingestionSpaceTrack.py`.
   - **Full pass (daily):** Space-Track's recommended current-catalogue query (not decayed, epoch within 30 days), plus decays from the last 30 days. It sets `lastSeenFull`, and objects that leave the catalogue count as changes.
   - **Recent pass (otherwise):** `EPOCH>now-2`. On 2026-10-21 that returned about 30k of the 32.8k objects.
   - **Storage:** all GP fields except the TLE lines, in camelCase columns, plus `fetchedAt`.
   - **Updates:** an element set only replaces a stored row if its epoch is newer, or if the epoch is the same and the metadata has changed. A repeated record is not counted as a change.
   - **Failures:** failed runs are recorded as failed.
   - **First DEV run:** 32,776 catalogue objects plus 108 recent decays, about 7 s, 12.5 MB. Space-Track's elements were newer than `orbitalObjects.db`'s for 26,839 objects, equal for 5,906 and never older.
   - **Deferred to step 11:** removing the Space-Track code from `ingestOrbitalData.py` and `ingestSatcat.py`. LIVE depends on it until the new pipeline takes over.
6. **CelesTrak.** DONE 2026-10-21: `scripts/ingestionCelesTrak.py` writes `ingestionCelesTrak.db`, with tests in `0_tests/test_ingestionCelesTrak.py`.
   - **What it fetches:** membership of all 47 groups (they feed the ADD OBJ group filter), as CSV, keeping only the NORAD ID and name. No elements.
   - **Tables:**
     - `groupMembers` (groupName, noradID, objectName). Each successful fetch replaces that group's membership in one transaction.
     - `groupFetches` (lastAttempt, lastSuccess, members, note) per group. The publish step uses `lastSuccess` to decide whether CelesTrak counts as available (decision A).
   - **Etiquette:**
     - `CELESTRAK_ENABLED=0` means no requests.
     - At most one pass per `CELESTRAK_GROUPS_INTERVAL_HOURS`, counted from the last attempt. The default is 72 h, and cron starts it every 3 days (decided 2026-10-21, at step 11; it was 168 h).
     - 3 s between groups, and a pass stops at the first connection failure.
     - A "not updated" reply counts as a skip, not an error.
   - **Changes and failures:** memberships added or removed count as changes (decision C1). A pass in which no group succeeds is recorded as failed. A group that fails keeps its previous membership.
   - **First DEV run** (3 groups only): active 16,765, stations 21, starlink 11,121. Compared with LIVE's frozen August lists, 851 objects became active and 189 stopped being active.

7. **SatNOGS.** DONE 2026-10-21, revised the same day: `scripts/ingestionSatNOGS.py` writes `ingestionSatNOGS.db`, with tests in `0_tests/test_ingestionSatNOGS.py` and fixtures in `0_tests/fixtures/`.
   - **No orbits from SatNOGS (decided 2026-10-21).**
     - SatNOGS serves only TLEs, never OMM, and doesn't support Alpha-5. This was checked on the web on 2026-10-21: its API has no OMM endpoint, and release 1.76 still has no Alpha-5.
     - Since NORAD's 5-digit catalogue numbers ran out in July 2026, new satellites appear in SatNOGS under its own placeholder numbers (98xxx/99xxx), mostly carrying Space-Track's elements re-encoded.
     - 1,572 of its 1,736 TLEs are copies of Space-Track's.
     - Orbits therefore come from Space-Track only.
   - **`tle` table: an ID crosswalk only.** One row per SatNOGS number, holding:
     - the catalogue number and international designator from the TLE line;
     - name, source, epoch, the raw lines, and `lastSeen`.

     No elements are decoded. A row is replaced only by a later epoch, or by the same epoch with a changed TLE, source or name. Rows that leave the feed count as changes.
   - **Why keep the TLE feed.** For satellites launched since July, neither `norad_follow_id` nor SatNOGS's satellites endpoint links a placeholder to NORAD's object, but the designator in the TLE line does. For example, SatNOGS 98193 (JACK-007) carries 2026-229K.
   - **`transmitters` table:** every record, keyed by uuid and replaced wholesale.
   - **Moves to step 9:** picking each satellite's main downlink and uplink (`choose_rf` in `ingestSatnogsRf.py`).
   - **Failures:** each feed fails independently and keeps its last good table, and the run is recorded as failed.
   - **DEV run:** 1,736 crosswalk rows (1,707 with a designator) and 5,121 transmitters for 2,691 satellites.
     - **Linked to a Space-Track object:** 1,307 via the designator, 192 via `norad_follow_id`, 3 via their own ID.
     - **Unlinked, 1,189:** 792 re-entered, 344 not in GCAT (placeholders never catalogued) and a few deep-space. Only 19 that GCAT lists as in orbit remain unlinked.
   - **Deferred to step 11:** removing the SatNOGS code from `ingestOrbitalData.py` and retiring `ingestSatnogsRf.py`.

8. **Renames and reference builders.** DONE 2026-10-21.
   - **New names on DEV:** `gcat.db` → `ingestionGCAT.db`, `space_news.db` → `ingestionNews.db` (snake_case columns kept), `groundSegmentAssets.db` → `ingestionGroundSegment.db`, `skyCatalogue.db` → `ingestionSkyCatalogue.db`.
   - **LIVE still works.** `dbPaths.LEGACY_NAMES` maps each new name to its old one wherever only `ingestionDBs/` exists, and `0_tests/test_dbPaths.py` covers it. Every path now goes through `dbPath()`, including `server.py`'s.
   - **Ground segment (decision D):** the builder is now `scripts/ingestionGroundSegment.py`.
     - It reads `DEV/LCARS/rschGrdSgmt/grndSgmntAssets_master.xlsx` in place, read-only. The file's checksum was unchanged after the run.
     - It builds into a `.tmp` file and swaps it in.
     - Table and column names are unchanged, since the panel reads them.
     - The rebuilt database matched the old one exactly: 312 rows and the same schema.
   - **Sky catalogue:** `buildSkyCatalogue.py` writes `ingestionSkyCatalogue.db`. The rebuild matched the old file in every content table; only the build timestamp in `skyBuild` differs.
   - **`.gitignore`:** ignores `databases/*` except the two reference DBs, which are now committed.
   - **Deferred to step 9:** moving `gcatBrightness` out of `ingestionGCAT.db`. It is derived data that becomes a publish stage, and until then LIVE's site reads it from the GCAT database.
   - **Checks:** 247 tests pass, and the API matches the step 2 baseline (358 of 359 endpoints; `/api/status` is clock-dependent).

### Publish steps

9. **`scripts/publishSite.py <type>`.** It builds `site<Type>.db.tmp` from the ingestion DBs that type depends on, ATTACHed read-only.
   - **Orbital:**
     1. Merge `orbital_objects`:
        - elements from Space-Track only (CelesTrak supplies none, per decision A; SatNOGS none, per step 7);
        - drop elements older than a maximum age (to agree);
        - exclude decayed objects;
        - normalise epochs to one format and object types to codes.
     2. Build the groups using the decision A precedence: `active`, `stations`, `starlink` and every constellation group `enrichEirp.py` uses (decision A, extended). Each rule's agreement with the latest CelesTrak list is printed on every publish, so drift shows up. The explanatory comment sits next to these rules.
     3. Link SatNOGS transmitters to NORAD objects: by `norad_follow_id`, then by the designator from SatNOGS's TLE (matched to Space-Track's `objectID`), then by their own `norad_cat_id`. Pick each satellite's main downlink and uplink (today's `choose_rf`). This fixes a current bug: RF data attached to SatNOGS's duplicate 9xxxx rows instead of the real object.
     4. Run EIRP (`enrichEirp`), brightness (`estimateBrightness`) and ON-ORBIT/LAUNCHES stats (`orbitStats`) as stages.
     5. Copy in the GCAT tables and columns the site reads.
   - **News, Sky, Ground segment:** copy the tables the site reads.
   - **Every type:**
     - Copy in its sources' `ingestionRuns`.
     - Run `PRAGMA integrity_check`.
     - Run a sanity check that refuses to publish if key row counts fall by more than an agreed percentage.
     - Keep `site<Type>.db.prev`, then `os.replace` the new file into place.
   - Time the full orbital rebuild on GoDaddy.

   **DONE 2026-10-21 on DEV.** `scripts/publishSite.py orbital|news|sky|groundSegment|all`. Tests: `0_tests/test_publishSite.py` and `0_tests/test_groupRules.py`.
   - **Group rules:** `scripts/groupRules.py` (decision A, extended).
   - **Radio selection:** moved to `scripts/rfSelection.py`, shared with `ingestSatnogsRf.py` until step 11.
   - **Refactored to be importable:**
     - `enrichEirp.py` no longer touches a database on import.
     - `estimateBrightness.py` takes the orbital path as a parameter.
     - `orbitStats.refreshAll()` takes file paths.

     All three still run as before on their own, as LIVE's cron needs.
   - **How the orbital file is built.** The objects are first built in a staging file, because the stats and brightness code attach the orbital table as a separate database. The tables are then copied into the site file with their indexes.
   - **Options:**
     - `--no-celestrak` builds groups from our rules only, as LIVE would while blocked.
     - `--force` overrides the sanity check.
   - **Parameters, confirmed by Al 2026-10-21:**
     - `MAX_ELEMENT_AGE_DAYS` = 30, matching Space-Track's own catalogue query.
     - Recently decayed objects are kept for 30 days, with their decay date.
     - `CELESTRAK_MAX_AGE_DAYS` = 14.
     - `MAX_DROP` = 10%.
   - **First DEV publish:**

     | File | Size | Time |
     |---|---|---|
     | `siteOrbital.db` | 25.3 MB | 21 s |
     | `siteNews.db` | 1.7 MB | under 0.1 s |
     | `siteSky.db` | 0.4 MB | under 0.1 s |
     | `siteGroundSegment.db` | 0.1 MB | under 0.1 s |

   - **Compared with LIVE's current pipeline output** (copied this morning):
     - **Objects:** 32,884 against 33,516.
       - **Not carried over:** 532 SatNOGS-only rows (mostly 9xxxx duplicates), 134 stale CelesTrak rows, and 105 objects outside Space-Track's current catalogue.
       - **New:** 139 objects, 49 of them with 6-digit numbers.
     - **Epochs:** never older. 211 appeared older, but every one is the same element set rounded under 1 s differently.
     - **Groups:** active 16,765 against 16,103, and starlink 11,121 against 10,989. LIVE's lists are frozen in August.
     - **EIRP tiers, payloads in orbit:** filing 12,928, estimated 1,874, unknown 4,102. LIVE has 12,924, 1,815 and 4,197.
     - **SatNOGS frequencies:** 1,433 satellites against 1,677. None now sit on 9xxxx duplicates; LIVE has 384.
     - **Stats:** `onOrbitObjects` 32,776 and brightness 21,115, against 33,186 and 21,144.
   - **The website doesn't read these files yet;** that is step 10. The API still matches the step 2 baseline apart from time-dependent endpoints.
   - **Rule agreement with CelesTrak** (our rules alone against CelesTrak's lists of 2026-10-21; the weak ones were later made CelesTrak-only, see question 1 below):

     | Agreement | Groups |
     |---|---|
     | 95% or more | starlink 98.7, oneweb 98.9, kuiper 99.7, iridium-NEXT 100, beidou 100 |
     | 85–95% | active 92.3, globalstar 86.5, gps-ops 86.1, galileo 90.6, planet 92.0, qianfan 88.3, hulianwang 87.5, eutelsat 86.2, argos 87.1, glo-ops 83.9 |
     | **Weak, listed as decision A requires** | ses 83.1, intelsat 64.3, telesat 61.1, sar 67.0, spire 65.2, sarsat 55.5, gnss 54.5, stations 50.0, orbcomm 48.3, sbas 34.2 |

     The weak ones mostly come from GCAT's broader definitions:
     - gnss counts every NAV payload;
     - sbas, sarsat and sar are function groups;
     - stations misses cubesats released from the ISS;
     - orbcomm includes satellites GCAT hasn't marked as ended.
   - **Questions 1 and 2, DECIDED 2026-10-21:**
     1. **Weak rules: CelesTrak-only until it's back.** stations, orbcomm, sbas, gnss, sarsat, ses, intelsat, telesat, sar and spire have no rule in `groupRules.py`, and are absent while CelesTrak is unavailable. The 14 groups kept are active plus 13 constellations.
     2. **Classification: CelesTrak groups stay the class tier; GCAT is the fallback only when CelesTrak is unavailable.**
        - **Where:** `enrichEirp.gcat_class()`.
        - **Rules, in order:**
          1. GCAT category SS → station.
          2. Mass 30 kg or less → amateur (payload class A) or cubesat.
          3. MET → weather-geo or weather-leo, by orbit.
          4. IMG-R → eo-radar.
          5. IMG or EOSCI → eo-optical.
          6. COM in GEO → military-comms (class D) or comms-geo.
          7. COM elsewhere → comms-leo-narrow.
          8. SCI, AST or TECH → science.

          Anything else stays unknown.
        - **How it's applied:** `publishSite.py` passes these classes to the EIRP stage when no CelesTrak list is available, and prints which tier it used.
        - **DEV, payloads in orbit:**

          | Publish | Constellation (filing) | Estimated | Unknown |
          |---|---|---|---|
          | With CelesTrak | 12,928 | 1,874 | 4,102 |
          | Without CelesTrak (as LIVE today) | 12,762 | 4,881 | 1,261 |
     3. **EST. SIZE, DECIDED 2026-10-21: keep CelesTrak's radar figure for good once known (satellites don't change size).**
        - **Storage:** `ingestionCelesTrak.db` has a `satcatRcs` table. Rows are only ever added or updated, never removed, and a blank never replaces a held figure.
        - **Sources:**
          - Each full CelesTrak pass (every 3 days) ends with one `satcat.csv` request.
          - `ingestionCelesTrak.py --seed-rcs <orbitalObjects.db>` is a one-off import of the figures the old database holds, filling only objects that don't have one yet.
        - **Publish:** `rcsSize` comes from that table; `rcsCategory` keeps Space-Track's SMALL, MEDIUM or LARGE.
        - **DEV results:**
          - The seed added 12,690 figures, and CelesTrak's current `satcat.csv` matched every one of them exactly.
          - `satcat.csv` added 20,241 more (32,931 in all, many for decayed objects).
          - The site now has 13,164 objects with EST. SIZE, against 12,690 on LIVE, with identical values wherever both have one.
          - Only 3,464 of 18,904 payloads in orbit have a figure: CelesTrak leaves RCS blank for most newer satellites, Starlink included.
     4. **Parameters, DECIDED 2026-10-21: kept as chosen.** 30 days maximum element age, 30 days for recent decays, CelesTrak available for 14 days after a fetch, and 10% maximum drop.

### Website

10. **`server.py`.**
    - Opens each site file read-only and reconnects when that file's inode or mtime changes. A long-lived connection would otherwise keep reading the old file after `os.replace`.
    - The bug-report endpoint writes to `inboxBugReports.db`; `bugs.py import-reports` reads from there.

    **DONE 2026-10-21 on DEV.**
    - **`site_db(kind)`** (kind is orbital, news, sky or groundSegment) gives a read-only connection, one per thread. It reopens whenever the site file's inode, mtime or size changes, so each publish is picked up on the next request.
      - `gcat_db()` and `stats_db()` now read `siteOrbital.db`.
      - The sky handlers' own connections and the browser-cache versions (ETag) follow the site files.
    - **On Windows (DEV),** each thread's connections are closed after every request (`release_site_dbs()`). Otherwise an open file would stop `publishSite.py` replacing it while the local server runs. On Linux they stay open.
    - **LIVE before step 12:** a kind whose site file doesn't exist is served from the pre-refactor databases. For orbital, `orbitalObjects.db` is opened with `onOrbitStats.db` and the GCAT database attached, so the same table names resolve. Checked on DEV by moving the site files aside: 345 of 359 endpoints matched the baseline, and the rest are time-dependent. **`master` stays deployable.**
    - **Freshness table:**
      - It reads the site files' combined run history. Each row lists the job names it accepts, newest first, with the old names kept until step 12.
      - Labels now say "NORAD via Space-Track".
      - There is a new "Satellite groups" row (CelesTrak plus our own rules), so a stale CelesTrak shows (decision C2).
      - `publishSite.py` records each publish as a run (`publishOrbital` and so on), which gives "Downlink EIRP" its refresh time.
    - **Bug reports:** `inboxBugReports.db` is mapped to `bugReports.db` on the old layout. `bugs.py` looks for either on LIVE.
    - **Checks:** 281 tests pass (5 new for site databases and status).
    - **API against the step 2 baseline, served from the site files:**
      - Every endpoint still answers as before; no status code changed.
      - 21 endpoints are identical: news, launches, ground segment and the sky catalogue.
      - The orbital endpoints differ as intended: newer element sets, and the groups and counts from step 9.

### Scheduling, deployment and switching LIVE over

11. **Cron.** Rewrite `runPipeline.sh` and `setupCron.sh`.
    - Each ingestion runs on its own schedule, and one failing doesn't block the others.
    - Each ingestion that changed something calls `publishSite.py` for the site files that depend on it (decision C1).
    - All writers share one `flock`.

    **DONE 2026-10-21 on DEV.**
    - **`scripts/runIngestion.py <source>`** (spaceTrack, satnogs, celesTrak, gcat or news). It:
      1. takes the shared writers' lock, `databases/.writers.lock`, waiting up to 15 minutes (fcntl, so Linux only; skipped on Windows);
      2. runs the source's ingestion as its own process;
      3. reads the run that process recorded;
      4. publishes the dependent site files only if that run succeeded with changes.

      A failed or skipped run publishes nothing (C2). A refused publish makes the run exit 1. Tests: `0_tests/test_runIngestion.py`.
    - **`setupCron.sh`** installs the new crontab (server time), and refuses unless `databases/` exists, so it can't start the new pipeline before the migration.

      | Source | Schedule |
      |---|---|
      | news | every 30 min |
      | spaceTrack | every 12 h (the daily full pass is chosen by the script) |
      | satnogs | every 12 h, at :30 |
      | celesTrak | 04:15 on days 1, 4, 7 … of the month, with the script's own 72 h check |
      | gcat | Sunday 03:00 |

      The ground segment and sky have no job (decision D).
    - **CelesTrak cadence decided 2026-10-21:** fetched every 3 days. Cron runs it every 3 days, and `CELESTRAK_GROUPS_INTERVAL_HOURS` now defaults to 72 instead of 168.
    - **`runPipeline.sh`, LIVE's current cron job, is untouched.** A deploy before step 12 changes nothing on LIVE. It and the old scripts go at step 15.
    - **DEV run through the runner:**
      - satnogs: 995 changes, then published orbital.
      - news: 13 new articles, then published news.
      - spaceTrack: recent pass, 20,752 changes, then published orbital.
      - celesTrak: skipped by its 72 h check, so nothing published.

      GCAT was not run live (a ~30 MB weekly download); the tests cover its wiring. 289 tests pass.
    - **Known gap:** a news run that only prunes old articles records 0 changes, so the pruning reaches `siteNews.db` at the next run with new articles.
12. **LIVE migration.** A one-off script, run with `DRY_RUN` first:
    1. Take the lock.
    2. Back up every DB.
    3. Rename the folder and files; bug reports become `inboxBugReports.db`.
    4. Seed the radar figures from LIVE's `orbitalObjects.db` with `ingestionCelesTrak.py --seed-rcs`, before that database is retired (decision 3 under step 9). While CelesTrak blocks LIVE, these figures are LIVE's only source for EST. SIZE.
    5. Run a full ingestion, then publish every type.
    6. Restart Passenger and install the new cron.

    Before the migration, change `deployToGoDaddy.sh` so it uploads `databases/ingestionGroundSegment.db` and `databases/ingestionSkyCatalogue.db` and excludes everything else in `databases/`. After any deploy that changes either file, it publishes the matching site file on the server (decision D).

    **DONE ON LIVE 2026-10-21, 23:04 UTC** (the server clock is UTC−7).
    - **Deploy:** the dry run listed 34 files updated and none deleted. After the real deploy, LIVE ran the new code on the old layout with every endpoint returning 200, and Al checked the site.
    - **`migrateLive.py --apply`:** every check passed, and it finished in about 1 minute.
      - It removed 3 old jobs and installed 5 new ones.
      - The backup is in `~/dbBackup-20261021-230444`, with the crontab saved alongside. Rollback: `scripts/migrateLive.py --rollback ~/dbBackup-20261021-230444 --apply`.
      - It seeded 12,690 radar figures.
      - Space-Track's full pass gave 32,774 objects plus 111 decays, and SatNOGS 1,736 crosswalk rows and 5,121 transmitters. CelesTrak stayed disabled.
      - It published `siteOrbital.db` (24.9 MB, 41 s), `siteNews.db`, `siteSky.db` and `siteGroundSegment.db`.
      - Log: `~/logs/migrateLive-20261021-230443.log`.
    - **Checked after:**
      - Every endpoint tried returned 200, and the Passenger log was clean.
      - The freshness table uses the new jobs.
      - The ISS shows EST. SIZE 399 m².
      - Groups come from our rules, as CelesTrak is blocked, so the ADD OBJ group filter offers 15 groups, down from 47.
      - "Satellite groups" in the freshness table stays empty until CelesTrak runs once.
    - **Old files still on LIVE:** `orbitalObjects.db`, `onOrbitStats.db` and `gcat.db.bak` remain in `databases/` until step 15.

    Written and rehearsed on DEV beforehand:
    - **`scripts/migrateLive.py`** runs on the server and is a dry run unless given `--apply`. In order it:
      1. checks preconditions (old layout present, new absent, SQLite 3.24 or later, `spacetrack.env`, `quick_check` on every DB, disk space, no rename conflicts), and reports whether CelesTrak is enabled;
      2. saves the crontab to the backup folder, removes the LCARS-FAS jobs, and waits up to 30 min for running ones;
      3. backs up every DB with SQLite's backup API to `~/dbBackup-<UTC time>/`, under the old names;
      4. checkpoints the WAL files and renames the folder and files, bug reports included;
      5. restarts the app (the renamed pre-refactor DBs serve until the site files exist);
      6. seeds the radar figures from `orbitalObjects.db`;
      7. runs Space-Track `--full`, SatNOGS and CelesTrak (which does nothing while disabled);
      8. publishes all four site files;
      9. runs `setupCron.sh`.

      Steps 6–9 run as separate processes, because `dbPaths` fixes the layout when it's imported. The lock isn't needed: no other writer can run between step 2 and step 9.
    - **Rollback:** `--rollback <backup> [--apply]` restores the crontab, moves `databases/` to `databases.failed-<time>/`, restores the DBs into `ingestionDBs/` and restarts the app.
    - **Deploy (decision D):**
      - `databases/` stays excluded from the archive and the sync.
      - After the sync, the two reference DBs are uploaded to `.referenceUpload/`, and `scripts/installReferenceDbs.py` swaps in any that changed (after an integrity check, under the writers' lock) and publishes their site files.
      - On a server not yet migrated, it discards the uploads.
      - A `DRY_RUN` uploads nothing.
    - **Rehearsal on DEV:** a copy of the app, with LIVE's DBs from 2026-10-21 under their old names and `CELESTRAK_ENABLED=0` as on LIVE.
      - The dry run passed every check.
      - `--apply` ran end to end in about 1 minute: groups from our rules, the EIRP class tier from GCAT, and 12,621 objects with EST. SIZE.
      - Against its own pre-migration snapshot, no endpoint changed status and 21 were identical. Only the orbital endpoints differed, as at step 10.
      - The reference install put in changed DBs and published them, and left unchanged ones alone.
      - `--rollback --apply` restored the old layout: 358 of 359 endpoints were identical to before, the other being the clock-dependent `/api/status`.
    - **Tests:** `0_tests/test_migrateLive.py`. 300 tests pass.
    - **RUN-BOOK FOR LIVE** (only on Al's go-ahead):
      1. `DRY_RUN=1 ./deployToGoDaddy.sh`, then review what the sync would change or delete.
      2. `./deployToGoDaddy.sh`. LIVE keeps serving the old layout through the legacy fallback, the old cron keeps running, and the reference uploads are discarded.
      3. Check the site.
      4. `ssh` to the server, `cd public_html/LCARS-FAS`, and run `…/3.9/bin/python scripts/migrateLive.py`. That is the dry run: review its checks and plan.
      5. Run the same command with `--apply`. Note the backup folder and rollback command it prints.
      6. Check the site and the freshness table, then `crontab -l` and the first `*_cron.log` files after the next scheduled runs.
      7. If anything is wrong: `python scripts/migrateLive.py --rollback ~/dbBackup-<time> --apply`.

### Checking it, and tidying up

13. **Tests and regression.**
    - Tests: merge rules, group precedence, the atomic swap and the publish refusal, reconnect after a swap, and the source clients against recorded responses.
    - Regression: compare every endpoint with the step 2 baseline and explain each difference.

    **Tests for previously untested scripts still in use, added 2026-10-22** (52 tests; 352 pass in all):
    - **`test_rfSelection.py`** (15): frequency plausibility (20 MHz to 60 GHz), transponder centre and span, preferring confirmed over violating or unconfirmed records, then active, then baud, then newest, and the uplink chosen separately.
    - **`test_estimateBrightness.py`** (15): Starlink generations by bus and launch date, including the date boundaries; `sizeMagnitude` checked against a hand calculation (1 m × 1 m comes out at 7.69); the span cap; and `brightnessRows` rules (station override, Starlink, size, defaults by type, debris and decayed objects excluded).
    - **`test_common.py`** (12): the `.env` loader never overrides the environment; `httpGet` sends a User-Agent and timeout and returns HTTP errors as responses; the Space-Track client covers login, Cookie, logout, bad credentials, a missing cookie, HTTP 401, and a failed logout never failing a run. The real `spacetrack.env` is never read.
    - **`test_readNews.py`** (10): RSS parsing of a sample feed (CDATA, entities, description preferred over `content:encoded`, items without a link skipped, a missing date), date normalisation, and the database set-up and its migration.
    - **Refactor:** `readNews.py` no longer opens the database at import (`openDb()`, and `fetch_all_feeds(db)`). Checked with a real news run through `runIngestion.py` on DEV. Not yet deployed to LIVE, where the previous version keeps working.
    - **Deliberately not tested:**
      - `ingestOrbitalData.py`, `ingestSatcat.py`, `ingestSatnogsRf.py` and `runPipeline.sh`, which are retired at step 15;
      - `migrateNewsDates.py`, a finished one-off and a step 15 candidate;
      - `ingestionGroundSegment.py`, which was checked by an identical rebuild;
      - `buildSkyCatalogue.py`, which is rarely rebuilt and was checked by an identical rebuild.
    - **Still to do for step 13:** one regression note in `0_testReports/` bringing together the API comparisons made at steps 8–12.
14. **Documentation.** Docstrings, `0_documentation`, freshness-table source labels (data-driven, "NORAD via Space-Track"), the bug log and fasLog.
15. **Clean-up.** After about two weeks on LIVE, remove the old DBs, the `.prev` files and the old scripts.

All decisions are settled; steps 1-15 can proceed in order.
