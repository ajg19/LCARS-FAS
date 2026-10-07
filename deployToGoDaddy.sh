#!/bin/bash
# Deploys the local LCARS-FAS working directory to GoDaddy over SSH.
#
# Transport is still a single compressed archive (kind to the link), but
# the server no longer just extracts it on top of whatever is already
# there -- it stages the archive and then `rsync -a --delete` mirrors the
# staged tree onto the live directory, so any file that no longer exists
# locally is removed on the server too.
#
# EXCLUDE_PATTERNS is the single source of truth for what must never leave
# the dev box or be touched on the server. It is fed to `tar` (so those
# paths are not in the archive) AND to the server-side `rsync --exclude-
# from` (so --delete does NOT remove the live databases, credentials, or
# Passenger's tmp/ restart-trigger dir just because they are absent from
# the archive).
#
# Preview what the sync would change and, especially, DELETE on the server
# without applying anything (the app is not restarted):
#     DRY_RUN=1 ./deployToGoDaddy.sh
set -euo pipefail

REMOTE_USER="sip9rb1lekyg"
REMOTE_HOST="gaps2024.com"
REMOTE_PATH="public_html/LCARS-FAS"
SSH_KEY="$HOME/.ssh/godaddy_lcars_fas"
ARCHIVE="lcarsFasDeploy.tar.gz"
EXCLUDE_FILE=".deployExcludes"
STAGE=".deployStage"

cd "$(dirname "$0")"

EXCLUDE_PATTERNS=(
    .git
    .env
    spacetrack.env
    __pycache__
    '*.pyc'
    ingestionDBs
    0_documentation
    0_tests
    0_testReports
    0_codeReviews
    bugsDB.xlsx
    '~$bugsDB.xlsx'
    toDo.md
    nodePersistenceTest.js
    persistenceTest.log
    tmp
    "$ARCHIVE"
    "$EXCLUDE_FILE"
    "$STAGE"
)

# Bare-pattern file for the server-side rsync (one pattern per line, no
# shell interpretation there -- so '*.pyc' / '~$bugsDB.xlsx' are safe).
printf '%s\n' "${EXCLUDE_PATTERNS[@]}" > "$EXCLUDE_FILE"

TAR_EXCLUDES=()
for p in "${EXCLUDE_PATTERNS[@]}"; do TAR_EXCLUDES+=(--exclude="$p"); done

echo "Packaging..."
tar -czf "$ARCHIVE" "${TAR_EXCLUDES[@]}" .

RSYNC_OPTS="-a --delete"
RESTART_CMD="touch tmp/restart.txt"
if [ -n "${DRY_RUN:-}" ]; then
    RSYNC_OPTS="$RSYNC_OPTS --dry-run --itemize-changes"
    RESTART_CMD="echo '(dry run: nothing applied, app not restarted)'"
    echo "DRY RUN"
fi

echo "Uploading..."
scp -i "$SSH_KEY" "$ARCHIVE" "$EXCLUDE_FILE" "$REMOTE_USER@$REMOTE_HOST:$REMOTE_PATH/"

echo "Staging and syncing on server..."
ssh -i "$SSH_KEY" "$REMOTE_USER@$REMOTE_HOST" "
    set -eu
    cd '$REMOTE_PATH'
    rm -rf '$STAGE'
    mkdir '$STAGE'
    tar -xzf '$ARCHIVE' -C '$STAGE'
    rsync $RSYNC_OPTS --exclude-from='$EXCLUDE_FILE' '$STAGE'/ ./
    rm -rf '$STAGE' '$ARCHIVE' '$EXCLUDE_FILE'
    $RESTART_CMD
"

rm -f "$ARCHIVE" "$EXCLUDE_FILE"
echo "Deploy complete."
