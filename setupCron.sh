#!/bin/bash
# Idempotent cron installer for the LCARS-FAS ingestion scripts.
#
# Safe to re-run any number of times: always strips out any previous
# LCARS-FAS entries first (matched by the MARKER comment on each managed
# line), then installs the current set fresh -- so re-running this after
# a path/schedule/credential change never leaves stale duplicate entries
# behind, and never touches any other, unrelated cron jobs already on
# this account.
#
# Space-Track credentials are read from spacetrack.env (next to this
# script, NOT committed to git -- see spacetrack.env.example for the
# format) rather than being embedded in this script's own source, so
# this file itself never becomes something that has to be treated as
# sensitive. This installer only checks the file is present and filled
# in; the ingest scripts read it themselves at run time, so the
# credentials never appear in the crontab.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CREDS_FILE="$SCRIPT_DIR/spacetrack.env"

if [ ! -f "$CREDS_FILE" ]; then
    echo "ERROR: $CREDS_FILE not found."
    echo "Copy spacetrack.env.example to spacetrack.env and fill in your real Space-Track credentials first."
    exit 1
fi

# Lock down permissions on the credentials file every run, not just once --
# cheap and idempotent, and guards against it ever ending up world/group
# readable (e.g. after a re-upload that resets permissions).
chmod 600 "$CREDS_FILE"

source "$CREDS_FILE"

if [ -z "$SPACETRACK_USER" ] || [ -z "$SPACETRACK_PASS" ]; then
    echo "ERROR: SPACETRACK_USER and/or SPACETRACK_PASS are empty in $CREDS_FILE."
    exit 1
fi

APP_ROOT="/home/sip9rb1lekyg/public_html/LCARS-FAS"
PYTHON="/home/sip9rb1lekyg/virtualenv/public_html/LCARS-FAS/3.9/bin/python"
LOG_DIR="/home/sip9rb1lekyg/logs"
MARKER="# LCARS-FAS-CRON"

TMPFILE=$(mktemp)

# Keep every existing cron entry EXCEPT ones we previously installed
# (identified by the marker), so this never disturbs anything else on
# the account.
crontab -l 2>/dev/null | grep -v "$MARKER" > "$TMPFILE"

# News ingestion is independent (its own DB, no dependency on the orbital
# pipeline). The orbital-object pipeline -- ingestOrbitalData -> ingestSatcat
# (daily) -> enrichEirp -> ingestSatnogsRf -- runs as ONE ordered process
# via scripts/runPipeline.sh so the enrichment steps can only start after
# ingestion returns; flock -n makes a slow run skip the next tick rather
# than overlap it. The wrapper writes its own consolidated pipeline_cron.log.
# GCAT (its own gcat.db) is fetched weekly, Sunday 03:00 server time -- GCAT
# updates nightly, but its ~30 MB is not worth re-fetching more often, and
# unchanged files are skipped anyway (If-Modified-Since).
#
# CelesTrak etiquette lives in the ingest scripts (72 h default) and the
# server's own .env (CELESTRAK_ENABLED=0 since 2026-10-17), NOT here: a
# variable set on the cron line would override .env.
cat >> "$TMPFILE" << EOF
*/30 * * * * $PYTHON $APP_ROOT/scripts/readNews.py >> $LOG_DIR/readNews_cron.log 2>&1 $MARKER
0 */12 * * * PYTHON="$PYTHON" LOG_DIR="$LOG_DIR" /usr/bin/flock -n $LOG_DIR/lcarsPipeline.lock /bin/bash $APP_ROOT/scripts/runPipeline.sh >> $LOG_DIR/pipeline_cron.log 2>&1 $MARKER
0 3 * * 0 $PYTHON $APP_ROOT/scripts/ingestGcat.py >> $LOG_DIR/gcat_cron.log 2>&1 $MARKER
EOF

crontab "$TMPFILE"
rm "$TMPFILE"

echo "Cron jobs installed. Current crontab:"
crontab -l
