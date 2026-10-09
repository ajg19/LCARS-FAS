# TO DO — LCARS-FAS

Reverse chronological — newest first. Completed items are marked **DONE**. Items with no recorded date are grouped at the bottom rather than guessed at.

## 2026-10-09 — News filtering, retention and topic histogram **(DONE locally — not yet deployed)**

On branch `newsFilters`. Filler (entertainment, shopping, daily features, NASA admin) is never stored; `scripts/pruneNews.py` deletes stored filler, duplicate titles and anything older than six months, then VACUUMs; `scripts/tagNews.py` tags articles for the ten news filter buttons and stores per-topic counts for the control-area histogram. All run after every `readNews.py`. Local `space_news.db` cleaned (415 → 337 articles) and tagged; backup at `ingestionDBs/space_news.db.bak` (not to be committed). Documented in the News section of `designAndArchitecture_0.4.docx` (v0.6), plus `testPlan_0.1.docx` and `installationAndStartupGuide_0.1.docx` (both v0.2); pre-change copies in `0_documentation/rollback/*.pre-news-filters.bak`.

Still to do:

- **Deploy**: `DRY_RUN=1 ./deployToGoDaddy.sh` first, then for real; over SSH back up the live `space_news.db`, run `python3 scripts/pruneNews.py --dry-run`, then `pruneNews.py` and `tagNews.py`. Cron needs no change.
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

Write a script to deploy LCARS-FAS to GoDaddy (automate the scp/tar upload + re-sync we've been doing by hand). **DONE** — `deployToGoDaddy.sh`.

## (undated) — Refactor duplicated object-list rendering

Check whether the code that renders the list of selected/plotted objects is duplicated across places (e.g. `renderOrbitalObjectsList` and the ADD OBJ / DEL OBJ results table rendering) and refactor to a single shared place if so.

## (undated) — SHW ALT button label sync check

Check the ON/OFF label stays in sync with whether altitude is actually being displayed under object names (e.g. toggle off then on, and check after GRD TRCK is toggled off/on too).
