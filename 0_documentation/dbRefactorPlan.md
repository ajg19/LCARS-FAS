# Database and source refactor plan

Agreed 2026-10-21 (Al + Claude). Status: steps 1-7 done on DEV (2026-10-21); step 8 next. Decisions A-D are settled. LIVE still uses `ingestionDBs/`, so `dbPaths.py` falls back to that name until step 12.

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
  - The ground-segment builder moves into the repo as `scripts/ingestGroundSegment.py`, from `DEV/LCARS/rschGrdSgmt/build_ground_segment_db.py`.

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
     - At most one pass per `CELESTRAK_GROUPS_INTERVAL_HOURS`, default 168, counted from the last attempt.
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

8. **Renames and reference builders.**
   - `gcat.db` becomes `ingestionGCAT.db`; `gcatBrightness` moves out.
   - `space_news.db` becomes `ingestionNews.db`. Its snake_case columns stay unless Al says otherwise.
   - Ground segment (decision D):
     - Move `DEV/LCARS/rschGrdSgmt/build_ground_segment_db.py` into the repo as `scripts/ingestGroundSegment.py`, using `dbPaths.py` and openpyxl. Read the master xlsx in place and never modify it.
     - Rebuild `ingestionGroundSegment.db`, then check it against the existing `groundSegmentAssets.db` (312 rows).
   - Sky catalogue: point `buildSkyCatalogue.py` at `ingestionSkyCatalogue.db` and rebuild.
   - `.gitignore`: ignore `databases/*` except those two reference DBs.

### Publish steps

9. **`scripts/publishSite.py <type>`.** It builds `site<Type>.db.tmp` from the ingestion DBs that type depends on, ATTACHed read-only.
   - **Orbital:**
     1. Merge `orbital_objects`:
        - elements from Space-Track only (CelesTrak supplies none, per decision A; SatNOGS none, per step 7);
        - drop elements older than a maximum age (to agree);
        - exclude decayed objects;
        - normalise epochs to one format and object types to codes.
     2. Build the groups using the decision A precedence. The explanatory comment sits next to these rules.
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

### Website

10. **`server.py`.**
    - Opens each site file read-only and reconnects when that file's inode or mtime changes. A long-lived connection would otherwise keep reading the old file after `os.replace`.
    - The bug-report endpoint writes to `inboxBugReports.db`; `bugs.py import-reports` reads from there.

### Scheduling, deployment and switching LIVE over

11. **Cron.** Rewrite `runPipeline.sh` and `setupCron.sh`.
    - Each ingestion runs on its own schedule, and one failing doesn't block the others.
    - Each ingestion that changed something calls `publishSite.py` for the site files that depend on it (decision C1).
    - All writers share one `flock`.
12. **LIVE migration.** A one-off script, run with `DRY_RUN` first:
    1. Take the lock.
    2. Back up every DB.
    3. Rename the folder and files; bug reports become `inboxBugReports.db`.
    4. Run a full ingestion, then publish every type.
    5. Restart Passenger and install the new cron.

    Before the migration, change `deployToGoDaddy.sh` so it uploads `databases/ingestionGroundSegment.db` and `databases/ingestionSkyCatalogue.db` and excludes everything else in `databases/`. After any deploy that changes either file, it publishes the matching site file on the server (decision D).

### Checking it, and tidying up

13. **Tests and regression.**
    - Tests: merge rules, group precedence, the atomic swap and the publish refusal, reconnect after a swap, and the source clients against recorded responses.
    - Regression: compare every endpoint with the step 2 baseline and explain each difference.
14. **Documentation.** Docstrings, `0_documentation`, freshness-table source labels (data-driven, "NORAD via Space-Track"), the bug log and fasLog.
15. **Clean-up.** After about two weeks on LIVE, remove the old DBs, the `.prev` files and the old scripts.

All decisions are settled; steps 1-15 can proceed in order.
