# Maintainability and Portability Plan

Fixes for the weaknesses found in the architecture review of 2026-10-22. Each section is scored:

- **Value**, 1–3: how much the fix helps maintenance, portability or safety (3 = most).
- **Tokens**, 1–3: Claude's likely token spend (1 = under ~20k, 2 = ~20–80k, 3 = over ~80k). These are rough estimates. Long sessions cost more, because each step re-reads the conversation.

Sections run in the suggested order: cheap, valuable fixes first. Nothing here is started without a "make it so". Nothing is committed or pushed without your permission.

| # | Fix | Value | Tokens |
|---|---|:-:|:-:|
| 1 | Dependency list | 3 | 1 |
| 2 | Tidy the project root | 2 | 1 |
| 3 | Retire dead code (plan step 15) | 3 | 1 |
| 4 | Consistent script naming | 2 | 2 |
| 5 | Host settings in one place | 2 | 2 |
| 6 | Alert when a cron job stops | 3 | 2 |
| 7 | Guard against Windows/Linux traps | 2 | 1 |
| 8 | Split `server.py` | 2 | 2 |
| 9 | Browser tests for the frontend | 3 | 3 |
| 10 | Split the large frontend files | 3 | 3 |
| 11 | Documents git can track | 1 | 2 |

---

## 1. Dependency list (Value 3, Tokens 1)

**Problem:** there is no `requirements.txt`. pytest, openpyxl and python-docx are needed but listed nowhere, and their versions aren't pinned.

**Fix:**
1. Add `requirements.txt` for the server. It is empty, since `server.py` and `scripts/` use only the standard library. A comment says so, and it gives the minimum Python version (3.9).
2. Add `requirements-dev.txt` for the laptop: pytest, openpyxl and python-docx, pinned to the versions installed now.
3. Mention both files in `TOOLS_README.md` and the install guide.

**Done when:** `pip install -r requirements-dev.txt` on a fresh machine lets the tests and tools run.

## 2. Tidy the project root (Value 2, Tokens 1)

**Problem:** `bugsDB.xlsx.bak`, `orbital_rocket_families-2.xlsx`, Excel lock files (`~$...`) and `__pycache__` sit in the root.

**Fix:**
1. Ask you where `orbital_rocket_families-2.xlsx` belongs: a research folder, or `0_documentation/`.
2. Check `.gitignore` covers `*.bak`, `~$*` and `__pycache__/`. The last two are already listed; add `*.bak` in general.
3. Make the deploy exclude list match, so nothing of this kind can reach the server.

**Done when:** the root holds only the app (`index.html`, `server.py`, `assets/`, `scripts/`, `databases/`, `setupCron.sh`), the `0_*` folders and config files.

## 3. Retire dead code: plan step 15 (Value 3, Tokens 1)

**Problem:** retired scripts (`ingestOrbitalData.py`, `ingestSatcat.py`, `ingestSatnogsRf.py`, `runPipeline.sh`, `migrateNewsDates.py`) and the legacy fallbacks in `dbPaths.py` and `server.py` stay until step 15. Until then a reader can't tell live code from dead.

**Fix:** as in `dbRefactorPlan.md` step 15, booked in your Outlook for 4 Nov:
1. Confirm LIVE has run the new pipeline cleanly for two weeks.
2. Delete the retired scripts. Remove the legacy fallbacks (`LEGACY_NAMES`, `LEGACY_FILES`, the `ingestionDBs/` entries) and the tests that cover only them.
3. On the server, delete the old databases and the pre-migration backup, after your go-ahead.

**Done when:** `grep -r ingestionDBs` finds nothing outside the plan's history, and the test suite passes.

## 4. Consistent script naming (Value 2, Tokens 2)

**Problem:** `ingest*` and `ingestion*` scripts sit side by side, and snake_case and camelCase functions are mixed.

**Fix:**
1. Rename scripts to one pattern after step 15 has removed the old ones: `ingestGcat.py` becomes `ingestionGCAT.py`, matching its database. `readNews.py` becomes `ingestionNews.py`.
2. Rename public functions to camelCase (`run_eirp_enrichment` → `runEirpEnrichment`, `fetch_all_feeds` → `fetchAllFeeds`, `choose_rf` → `chooseRf`, and so on), updating callers and tests.
3. Update `runIngestion.py`'s `SOURCES`, the cron line, the docs and memory.
4. Run the full tests and an API snapshot comparison: there should be no difference.

**Done when:** every ingestion script is `ingestion<Source>.py` and the tests pass. Deploy needed, since cron calls the scripts.

## 5. Host settings in one place (Value 2, Tokens 2)

**Problem:** the GoDaddy user, host, app path, Python path and SSH key are hard-coded in `deployToGoDaddy.sh`, `setupCron.sh`, `migrateLive.py` and `dbPaths.LIVE_ROOT`. Moving host means editing several files.

**Fix:**
1. Add a `hosting.env` file holding `REMOTE_USER`, `REMOTE_HOST`, `REMOTE_PATH`, `REMOTE_PYTHON`, `SSH_KEY` and `BASE_URL`. Commit a `hosting.env.example`; keep the real one out of git if you prefer.
2. Make the deploy and cron scripts `source` it, and have Python read it through `common.loadProjectEnv`.
3. Make `checkLiveDeployment.py` and the test harness take `BASE_URL` from it.
4. Write a one-page "Moving to another host" section in the install guide: Passenger vs. other WSGI servers, `.htaccess` vs. an nginx equivalent, and the cron lines.

**Done when:** a new host needs one edited file plus the install guide. Verify with a deploy dry run.

## 6. Alert when a cron job stops (Value 3, Tokens 2)

**Problem:** nothing tells you if a source stops refreshing, apart from running the live check by hand.

**Fix:**
1. Add a small server-side job, `scripts/watchFreshness.py`, run by cron every few hours. It applies the same judgement as `checkLiveDeployment.judgeFreshness`, with the logic shared and not copied.
2. When a source is overdue or failing, it emails you through the server's mail (or GoDaddy's SMTP), at most once a day per problem.
3. Add a test with canned freshness rows.

**Done when:** stopping a cron job on DEV produces one alert, and restarting it clears the alert. Deploy needed.

## 7. Guard against Windows/Linux traps (Value 2, Tokens 1)

**Problem:** CRLF line endings broke the deploy script once. File locking and connection release behave differently on Windows.

**Fix:**
1. Add `.gitattributes`: `*.sh text eol=lf`, `*.py text eol=lf`. Git then always writes LF, whatever the editor does.
2. Add a test that fails if any `.sh` file contains CR characters.
3. Collect the platform differences in one short "Windows vs. Linux" note in the install guide.

**Done when:** a script saved with CRLF on Windows still deploys correctly, and the new test passes.

## 8. Split server.py (Value 2, Tokens 2)

**Problem:** 1,400 lines in one file hold routing, SQL, caching and file serving.

**Fix:**
1. Create a `server/` package (or a `routes/` folder beside `server.py`). It gets one module per area, following the spine: `news.py`, `onOrbit.py`, `launches.py`, `orbitalObjects.py`, `sky.py`, `groundSegment.py`, `bugReports.py`, `status.py`. Shared code goes in `siteDb.py`, `static.py` and `http.py`.
2. `server.py` keeps only the WSGI `application` and the route table, so `passenger_wsgi.py` doesn't change.
3. Move the code without changing behaviour. Prove it with the full test suite and an API snapshot comparison: all 359 identical apart from the time-dependent ones.

**Done when:** no module is over about 300 lines, the snapshot comparison is clean, and a deploy dry run shows the new files. Deploy needed.

## 9. Browser tests for the frontend (Value 3, Tokens 3)

**Problem:** the JavaScript, most of the code, has no automated tests. Bugs like #8 are found only by eye.

**Fix:**
1. Add Playwright for Python to `requirements-dev.txt`. It runs the same on Windows and Linux.
2. Write a small set of smoke tests against the local server. Each spine section opens without console errors. Leaving GS OPS stops its timers (the bug #8 regression test). ADD OBJ search returns results. Each ON-ORBIT chart draws.
3. Add them to the test harness as a "Browser tests" group, DEV only.
4. Start with about 10 tests. Add one with each frontend bug fixed from then on.

**Done when:** `pytest 0_tests/browser` passes against `python server.py`, and reintroducing bug #8 makes a test fail.

## 10. Split the large frontend files (Value 3, Tokens 3)

**Problem:** `grdTrackPanel.js` (2,147 lines), `onOrbitPanel.js` (1,683), `gsOpsPanel.js` (1,399), `lcars.js` (1,218) and `grdViewPanel.js` (1,216) share global state and are risky to change.

**Fix:** do this after section 9, so the browser tests catch regressions.
1. Begin with `lcars.js`. Separate the spine/section manager (show, leave hooks, timers) from shared helpers, and give each section a clear `enter`/`leave` life cycle that owns its timers.
2. Then split one panel at a time into modules of under about 500 lines: data loading, drawing and controls. Use native ES modules (`<script type="module">`), so there is still no build step.
3. Run the browser tests and check by eye after each panel. Deploy after each panel, not all at once.

**Done when:** no frontend file is over about 600 lines, each section owns and clears its own timers, and the browser tests pass. This takes several sessions, one panel per session.

## 11. Documents git can track (Value 1, Tokens 2)

**Problem:** the design, install and test documents are Word files, so git can't show what changed between versions.

**Fix (optional):**
1. Either keep Word and add a script that exports each `.docx` to Markdown alongside it, so git shows changes. That's cheap.
2. Or move the living documents to Markdown and generate Word or PDF only when someone needs a copy.

**Done when:** you can see in git what changed in a document between two commits. Decide first which you prefer.

---

**Suggested batching to save tokens:**
- **Session A:** sections 1, 2 and 7, all cheap, in one sitting.
- **Session B:** section 3, on 4 Nov as booked; section 4 straight after, while the scripts are fresh.
- **Session C:** sections 5 and 6, both deployment and server work, with one deploy.
- **Session D:** section 8.
- **Sessions E and up:** section 9, then section 10, one panel per session.
