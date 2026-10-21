"""Where every database lives -- the single place DB paths and names are
defined, for the ingestion scripts, server.py and 0_tools/bugs.py.

The folder is databases/ (0_documentation/dbRefactorPlan.md, step 4).
Until the live server is migrated (step 12) its folder is still called
ingestionDBs/, so DB_DIR falls back to that name when databases/ doesn't
exist -- master stays deployable throughout the refactor. Remove the
fallback in step 15.

File names are still the pre-refactor ones; step 8 renames them to the
ingestion<Source>.db / site<Type>.db / inbox<Name>.db convention.
"""

import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DB_DIR_NAME = 'databases'
LEGACY_DB_DIR_NAME = 'ingestionDBs'  # until step 12; see the module docstring


def dbDir(root=ROOT):
    """The database folder under `root`: databases/, or ingestionDBs/
    where only that exists (the live server, until step 12)."""
    current = os.path.join(root, DB_DIR_NAME)
    legacy = os.path.join(root, LEGACY_DB_DIR_NAME)
    if not os.path.isdir(current) and os.path.isdir(legacy):
        return legacy
    return current


DB_DIR = dbDir()

NEWS_DB = 'space_news.db'
ORBITAL_DB = 'orbitalObjects.db'
GCAT_DB = 'gcat.db'
STATS_DB = 'onOrbitStats.db'
SKY_DB = 'skyCatalogue.db'
GROUND_SEGMENT_DB = 'groundSegmentAssets.db'
BUG_REPORTS_DB = 'bugReports.db'

# Ingestion databases under the new convention (one per source).
SPACETRACK_DB = 'ingestionSpaceTrack.db'
CELESTRAK_DB = 'ingestionCelesTrak.db'


def dbPath(name):
    """Full path of database file `name` (one of the *_DB names above)."""
    return os.path.join(DB_DIR, name)


# The live server's app folder, for tools that reach it over SSH.
LIVE_ROOT = '/home/sip9rb1lekyg/public_html/LCARS-FAS'
LIVE_DB_DIRS = (f'{LIVE_ROOT}/{DB_DIR_NAME}', f'{LIVE_ROOT}/{LEGACY_DB_DIR_NAME}')
