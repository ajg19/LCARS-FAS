#!/bin/bash
# Runs the orbital-object cache pipeline in dependency order, as ONE
# process, so the supplementation steps can only start once ingestion has
# returned:
#
#   1. ingestOrbitalData.py   rows + orbital_object_groups      (every run)
#   2. ingestSatcat.py        objectType / owner / period       (daily, or RUN_SATCAT=1)
#   3. enrichEirp.py          downlinkBand / EIRP / sat G/T      (every run)
#   4. ingestSatnogsRf.py     dl/ul frequency / mode / baud      (every run)
#   5. orbitStats.py          ON-ORBIT overview figures           (every run)
#
# Steps 3-4 need step 1 (and 3 also needs 2); they are independent of each
# other. Step 5 needs the current orbits from 1-2 (and GCAT's ownership,
# from the separate weekly ingestGcat.py -- it skips itself until ingestionGCAT.db
# exists). Every step is idempotent, so 3-5 run on every pass rather than
# trying to detect whether new objects were actually added.
#
# Invoked by a single cron entry wrapped in `flock -n` (see setupCron.sh)
# so a slow run never overlaps the next tick. Safe to run by hand too.
#
# Environment (cron sets these; sane defaults otherwise):
#   PYTHON      interpreter path                     [python3]
#   LOG_DIR     dir for pipeline_cron.log            [$HOME/logs]
#   RUN_SATCAT  set to 1 to force step 2 off-hour    [auto: only at 00:xx]
#   Space-Track credentials: read by steps 1-2 from spacetrack.env, not here
#   CelesTrak etiquette settings live in the app's .env, not here
#   (see ingestOrbitalData.py)

set -u

cd "$(dirname "${BASH_SOURCE[0]}")/.." || exit 1

PYTHON="${PYTHON:-python3}"
LOG_DIR="${LOG_DIR:-$HOME/logs}"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/pipeline_cron.log"

step() {
    echo "[$(date -Is)] >>> $1" >> "$LOG"
    "$PYTHON" "scripts/$1" >> "$LOG" 2>&1
    echo "[$(date -Is)] <<< $1 (exit $?)" >> "$LOG"
}

echo "[$(date -Is)] === pipeline start ===" >> "$LOG"

step ingestOrbitalData.py

if [ "${RUN_SATCAT:-}" = "1" ] || [ "$(date +%H)" = "00" ]; then
    step ingestSatcat.py
else
    echo "[$(date -Is)] --- ingestSatcat.py skipped (runs daily; RUN_SATCAT=1 to force) ---" >> "$LOG"
fi

step enrichEirp.py
step ingestSatnogsRf.py
step orbitStats.py

echo "[$(date -Is)] === pipeline end ===" >> "$LOG"
