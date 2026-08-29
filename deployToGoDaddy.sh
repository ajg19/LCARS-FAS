#!/bin/bash
# Deploys the local LCARS-FAS working directory to GoDaddy over SSH/SCP.
# Excludes local-only, secret, and live-server-owned files (see EXCLUDES)
# so a deploy never overwrites the live databases, live credentials file,
# or Passenger's own tmp/ restart-trigger directory.
set -euo pipefail

REMOTE_USER="sip9rb1lekyg"
REMOTE_HOST="gaps2024.com"
REMOTE_PATH="public_html/LCARS-FAS"
SSH_KEY="$HOME/.ssh/godaddy_lcars_fas"
ARCHIVE="lcarsFasDeploy.tar.gz"

cd "$(dirname "$0")"

EXCLUDES=(
    --exclude='.git'
    --exclude='.env'
    --exclude='spacetrack.env'
    --exclude='__pycache__'
    --exclude='*.pyc'
    --exclude='ingestionDBs'
    --exclude='0_documentation'
    --exclude='0_tests'
    --exclude='0_testReports'
    --exclude='0_codeReviews'
    --exclude='bugsDB.xlsx'
    --exclude='~$bugsDB.xlsx'
    --exclude='toDo.md'
    --exclude='nodePersistenceTest.js'
    --exclude='persistenceTest.log'
    --exclude='tmp'
    --exclude="$ARCHIVE"
)

echo "Packaging..."
tar -czf "$ARCHIVE" "${EXCLUDES[@]}" .

echo "Uploading..."
scp -i "$SSH_KEY" "$ARCHIVE" "$REMOTE_USER@$REMOTE_HOST:$REMOTE_PATH/"

echo "Extracting and restarting app on server..."
ssh -i "$SSH_KEY" "$REMOTE_USER@$REMOTE_HOST" "cd $REMOTE_PATH && tar -xzf $ARCHIVE && rm $ARCHIVE && touch tmp/restart.txt"

rm "$ARCHIVE"
echo "Deploy complete."
