# LCARS-FAS tools

Helpers that run on the **laptop**, from the project root (`LCARS-FAS/`). None is deployed: `0_tools/` is excluded from the deploy. (The scripts that run on the server are in `scripts/`.)

| Tool | What it's for | Touches |
|---|---|---|
| [`testHarness.py`](#testharnesspy) | Pick and run tests from a tickbox table | Laptop code; read-only requests to a site |
| [`checkLiveDeployment.py`](#checklivedeploymentpy) | Read-only health check of a running site | A site, GET requests only |
| [`deployToGoDaddy.sh`](#deploytogodaddysh) | Deploy the working copy to LIVE | **LIVE server** |
| [`apiSnapshot.py`](#apisnapshotpy) | Record every API answer, compare two recordings | Local databases, read-only |
| [`bugs.py`](#bugspy) | Read and edit the bug log (`bugsDB.xlsx`) | The workbook |
| `dbDiagrams.py` | Draw every database as an ER diagram (SVG, PNG, Mermaid) from its real schema, plus the README and data-flow overview in `0_documentation/databases/`. Run `python 0_tools/dbDiagrams.py`; `--no-png` skips PNGs | Reads copies of the databases; writes `0_documentation/databases/` |

## testHarness.py

A window with a table of every test, grouped by LCARS spine section, server-side backend and deployment. Tick what you want and press **Run ticked**.

```bash
python 0_tools/testHarness.py
```

- **Columns:** Functionality (spine section or backend area), what is tested, and a tickbox. Expand a row to pick single tests.
- **Environment toggle (top):** DEV / LOCAL runs code tests and checks the local server (`python server.py` first). LIVE / GODADDY runs site checks only, against the live site; code tests are greyed out.
- **Pace:** the pause between requests to a site, with random variation. LIVE never goes below 1.5 s. This avoids GoDaddy's bot screening.
- **Private-file lock:** the probes for `.env`, `server.py`, databases and so on are greyed out until you tick "Allow probes of private files". It relocks after every run.
- **Results:** rows turn green, amber (warning, skipped, not run) or red. "Tick failed" reselects the failures.
- **Needs:** Python with tkinter and pytest. On Linux, `sudo apt install python3-tk`.

## checkLiveDeployment.py

Checks a running site with GET requests only: pages and APIs answer with sensible data, every data source was refreshed on schedule, private files are refused, and (optionally) deployed files match the working copy. Standard library only.

```bash
python 0_tools/checkLiveDeployment.py                    # LIVE
python 0_tools/checkLiveDeployment.py --quick            # skip the large downloads
python 0_tools/checkLiveDeployment.py --compare-assets   # also compare deployed files with this copy
python 0_tools/checkLiveDeployment.py --base http://127.0.0.1:3000   # another site, e.g. local
```

Each line reads OK, WARN or FAIL, with what was checked and found. Exit code 0 means nothing failed, 1 means something failed, and 2 means the site couldn't be reached. Requests are spaced at random 1.5–4.5 s gaps. A "being verified" reply is GoDaddy's bot check: stop and retry in several minutes.

## deployToGoDaddy.sh

Packs the working copy, uploads it over SSH and mirrors it onto the live folder (`rsync --delete`). Databases, credentials and `0_*` folders never travel. The two reference databases are uploaded separately and installed on the server.

```bash
DRY_RUN=1 ./0_tools/deployToGoDaddy.sh    # preview what would change or be deleted; nothing applied
./0_tools/deployToGoDaddy.sh              # the real deploy
```

Run from Git Bash. **Always dry-run first and read what it would delete.** Needs the SSH key `~/.ssh/godaddy_lcars_fas`. The file must keep LF line endings.

## apiSnapshot.py

Calls the server's API in-process (no running server needed) for about 359 endpoint and filter combinations, and saves the answers. Use it before a risky change to prove afterwards what did or didn't change.

```bash
python 0_tools/apiSnapshot.py take before-change
# ...make the change...
python 0_tools/apiSnapshot.py take after-change
python 0_tools/apiSnapshot.py compare before-change after-change
```

Snapshots go to `0_testReports/apiSnapshots/` (large, gitignored). Endpoints that depend on the clock are flagged as expected differences.

## bugs.py

The command-line interface to the bug log `bugsDB.xlsx`. It edits the workbook in place, so formatting and drop-downs survive, and it saves `bugsDB.xlsx.bak` before every change. **Close the workbook in Excel first.** Needs `openpyxl`.

```bash
python 0_tools/bugs.py list --open
python 0_tools/bugs.py show 8
python 0_tools/bugs.py add --title "Map won't zoom" --severity Medium --component "On-Orbit map"
python 0_tools/bugs.py set 8 --fixed          # Status=Fixed, Date Fixed=today
python 0_tools/bugs.py set 8 --reopen
python 0_tools/bugs.py import-reports         # bring in visitor bug reports (add --dry-run to preview)
```

`add` and `set` take `--dry-run` to show the result without saving. Run `python 0_tools/bugs.py --help` for every field.
