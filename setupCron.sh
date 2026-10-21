#!/bin/bash
# Idempotent cron installer for the LCARS-FAS ingestion jobs.
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

# Since the database refactor (0_documentation/dbRefactorPlan.md, step 11)
# every job is one source's ingestion run through scripts/runIngestion.py,
# which takes the shared writers' lock, runs the ingestion, and publishes
# the site files that source feeds -- only if the run changed something.
# Each source runs on its own schedule, so one failing never holds up the
# others. Server time throughout.
#   news        every 30 min
#   spaceTrack  every 12 h (one pass a day is the full catalogue)
#   satnogs     every 12 h, offset 30 min from Space-Track
#   celesTrak   every 3 days (the script itself also refuses to ask
#               CelesTrak sooner than 72 h, and nothing at all while the
#               server's .env has CELESTRAK_ENABLED=0)
#   gcat        weekly, Sunday 03:00 -- GCAT updates nightly, but its
#               ~30 MB is not worth re-fetching more often
# The reference databases (ground segment, sky) have no job: they are
# built on the laptop and published by the deploy (decision D).
#
# This crontab is for the migrated layout only (databases/). Installing it
# on a server still on the old layout would start the new pipeline before
# the migration (step 12) has backed up and converted the databases.
if [ ! -d "$APP_ROOT/databases" ]; then
    echo "ERROR: $APP_ROOT/databases not found -- this server hasn't been migrated (plan step 12)."
    echo "Nothing installed; the existing crontab is unchanged."
    rm "$TMPFILE"
    exit 1
fi

RUN="$PYTHON $APP_ROOT/scripts/runIngestion.py"
cat >> "$TMPFILE" << EOF
*/30 * * * * $RUN news >> $LOG_DIR/news_cron.log 2>&1 $MARKER
0 */12 * * * $RUN spaceTrack >> $LOG_DIR/spaceTrack_cron.log 2>&1 $MARKER
30 */12 * * * $RUN satnogs >> $LOG_DIR/satnogs_cron.log 2>&1 $MARKER
15 4 */3 * * $RUN celesTrak >> $LOG_DIR/celesTrak_cron.log 2>&1 $MARKER
0 3 * * 0 $RUN gcat >> $LOG_DIR/gcat_cron.log 2>&1 $MARKER
EOF

crontab "$TMPFILE"
rm "$TMPFILE"

echo "Cron jobs installed. Current crontab:"
crontab -l
