# Regression Report: Database and Source Refactor, 2026-10-22 11:30 UTC

**Scope:** steps 1–12 of `0_documentation/dbRefactorPlan.md`, from the step 2 baseline to LIVE's first scheduled runs after migration.
**Result:** ✔ PASS. Every API endpoint still answers as before; every difference in content is intended and explained below.
**Test suite:** `pytest 0_tests`: 352 passed, 1 skipped (fcntl locking, Linux-only), 0 failed.

## Method

- **Tool:** `0_tools/apiSnapshot.py` calls `server.py`'s WSGI application in-process. It saves the JSON of **359 endpoint/filter combinations**: every GET route, all ON-ORBIT charts × status × kind × SpaceX filters, launches × SpaceX × outcome, and sample objects. A second command compares two snapshots by status code and content hash.
- **Baseline** (`baseline-2026-10-21`, step 2): taken on DEV after loading LIVE's databases of 2026-10-21, before any refactor change.
- **Expected to differ:**
  - Snapshots are kept under `0_testReports/apiSnapshots/` (gitignored, regenerable).
  - Three endpoints depend on the clock: `/api/status`, `/api/sky/satellites`, and the GEO-belt charts, whose longitudes are propagated to the time the stats were built. They are marked "time-dependent, expected".
  - A repeat baseline differed only in `/api/status`.
- **Unchanged reference point:** `/api/sky/object?noradID=44713` (a Starlink not in the data) returns 404 in every snapshot.

## Results by step

| Step | What changed | Compared with baseline | Verdict |
|---|---|---|---|
| 3 | Shared `dbPaths.py` / `common.py`; all scripts and `server.py` switched to them | 358 of 359 identical; 1 time-dependent | No behaviour change ✔ |
| 4 | Folder `ingestionDBs/` → `databases/` | 358 / 359 | ✔ |
| 8 | Database files renamed to `ingestion<Source>.db`; reference builders | 358 / 359 | ✔ |
| 9 | `publishSite.py` builds site files (not yet read by the server); derived scripts refactored and re-run | 345 / 359; the 14 are all time-dependent (12 GEO-belt, status, sky satellites) | ✔ |
| 10 | Server reads the `site<Type>.db` files | 21 identical; the 338 orbital endpoints differ as intended (below); **no status code changed** | ✔ intended |
| 10 | Legacy fallback (site files moved aside, i.e. LIVE before migration) | 345 / 359; the 14 are time-dependent | Old layout still served ✔ |
| 12 | Rehearsal on a copy of the app with LIVE's databases: migrate | Against its own pre-migration snapshot: 21 identical, orbital endpoints differ as at step 10, no status change | ✔ |
| 12 | Rehearsal: rollback | 358 / 359 against pre-migration; 1 time-dependent | Exact restore ✔ |

The 21 endpoints identical after step 10 are those whose data the refactor doesn't touch: news (2), launches (16), ground segment (1), sky catalogue (1), and the 404 reference object (1).

## Intended differences in the orbital data

DEV, served from the site files with CelesTrak available, compared with the pre-refactor pipeline's output copied from LIVE on 2026-10-21.

| Measure | Before | After | Why |
|---|---|---|---|
| Objects | 33,516 | 32,884 | **Dropped:** 532 SatNOGS-only rows (mostly duplicates under SatNOGS's 9xxxx placeholder numbers), 134 stale CelesTrak rows from August, and 105 objects outside Space-Track's current catalogue (element sets over 30 days old). **Added:** 139 objects, 49 of them with 6-digit catalogue numbers |
| Element sets | — | Newer for 26,902, same for 5,632 | Space-Track (NORAD) is now the only orbit source. 211 appeared "older", but every one is the same element set with an epoch rounded differently (all under 1 s; the old copy came partly via TLE text) |
| Example: ISS | Perigee 415.181, apogee 424.359 km | 415.09 / 424.37 km | Newer element set |
| `active` group | 16,103 | 16,765 | LIVE's CelesTrak lists were frozen in August; DEV fetched fresh lists |
| `starlink` group | 10,989 | 11,121 | Same reason |
| EIRP tier, payloads in orbit (filing / estimated / unknown) | 12,924 / 1,815 / 4,197 | 12,928 / 1,874 / 4,102 | Fresher groups |
| Satellites with SatNOGS frequencies | 1,677 (384 on 9xxxx duplicates) | 1,433 (0 on duplicates) | Transmitters linked to the real NORAD object (follow ID, then designator, then own number). **Fixes a bug:** real objects had been missing their frequencies |
| ON-ORBIT objects | 33,186 | 32,776 | Follows the object set |
| Brightness rows | 21,144 | 21,115 | Follows the object set |
| EST. SIZE (radar figure) | 12,690 objects | 13,164 | CelesTrak figures kept for good once known; the 12,690 already held matched CelesTrak's current catalogue exactly |

**Without CelesTrak, as on LIVE today:**
- Groups come from our own rules: 15 groups, `active` 15,622.
- The ten groups whose rules agreed poorly with CelesTrak are absent until CelesTrak is back. As a result, the ADD OBJ group filter offers 15 groups instead of 47.
- The link budget's class tier falls back to GCAT. Unknown payloads in orbit drop from 4,102 to 1,261.

**Freshness table:**
- Labels read "NORAD via Space-Track".
- There is a new "Satellite groups" row, blank until CelesTrak runs.
- "Downlink EIRP" now dates from the latest publish.

## LIVE (https://gaps2024.com/LCARS-FAS)

**Deploy (2026-10-21):**
- The dry run showed 34 files updated and 0 deleted.
- After the deploy, every endpoint tried returned 200 on the old layout, through the legacy fallback.
- The bug #8 fix (`gsOpsPanel.js`, `lcars.js`) matched local.

**Migration (2026-10-21, 23:04 UTC):**
- `migrateLive.py --apply` finished in about 1 minute.
- Backup: `~/dbBackup-20261021-230444`.
- All 14 endpoints tried returned 200, the Passenger log was clean, and the freshness table showed the new jobs.

**First scheduled runs:**

| Job | Server time (UTC−7) | Result |
|---|---|---|
| News | 2026-10-21, every 30 min from 16:30 | Published when articles arrived (16:30, 18:00); "nothing to publish" otherwise |
| Space-Track | 2026-10-22 00:00 | Recent pass, 20,441 changed → `siteOrbital.db` published |
| SatNOGS | 2026-10-22 00:30 | 1,240 changes → published |
| Writers' lock | 2026-10-22 00:00 | The 00:00 news run waited ~50 s for the Space-Track publish, then ran |

## Not covered

- **Visual and interactive checks:** done by Al in the browser on DEV (step 10) and LIVE (before the migration). The GRD-TRACK footprint size question was Mercator projection, not a defect.
- **Not yet observed on LIVE:**
  - CelesTrak's first scheduled run, which should log "skipped -- disabled" while `CELESTRAK_ENABLED=0`.
  - GCAT's first weekly run (Sunday 03:00 server time).
  - A full 23-hour cycle of the daily Space-Track full pass.
- **Scripts without tests of their own:**
  - Retired at step 15: `ingestOrbitalData.py`, `ingestSatcat.py`, `ingestSatnogsRf.py`, `runPipeline.sh`, `migrateNewsDates.py`.
  - Checked by identical rebuilds instead: `ingestionGroundSegment.py`, `buildSkyCatalogue.py`.
