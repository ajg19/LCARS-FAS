"""Where every database lives -- the single place DB paths and names are
defined, for the ingestion scripts, server.py and 0_tools/bugs.py.

The folder is databases/ (0_documentation/plans/dbRefactorPlan.md, step 4) and
the files follow the ingestion<Source>.db / site<Type>.db / inbox<Name>.db
convention (step 8 onward). Until the live server is migrated (step 12)
it still has the old folder, ingestionDBs/, with the old file names. So
where only ingestionDBs/ exists, DB_DIR falls back to it and dbPath()
maps each new name to its old one (LEGACY_NAMES) -- master stays
deployable throughout the refactor. Remove both fallbacks in step 15.

Always build a path with dbPath(NAME); never join DB_DIR and a name
yourself, or the old-name mapping is bypassed.
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
LEGACY = os.path.basename(DB_DIR) == LEGACY_DB_DIR_NAME

# Ingestion databases, one per source.
SPACETRACK_DB = 'ingestionSpaceTrack.db'
CELESTRAK_DB = 'ingestionCelesTrak.db'
SATNOGS_DB = 'ingestionSatNOGS.db'
GCAT_DB = 'ingestionGCAT.db'
NEWS_DB = 'ingestionNews.db'
GROUND_SEGMENT_DB = 'ingestionGroundSegment.db'
SKY_DB = 'ingestionSkyCatalogue.db'
GEOIP_DB = 'ingestionGeoIP.db'   # address ranges to cities (DB-IP), built on the laptop by 0_tools/buildGeoIPDb.py
SWPC_DB = 'ingestionSWPC.db'     # NOAA space weather: solar wind, X-ray, protons, Kp, F10.7, forecasts
GFZ_DB = 'ingestionGFZ.db'       # GFZ Potsdam: Kp, ap, Ap, Hp30, Hp60, F10.7, sunspot number
DONKI_DB = 'ingestionDONKI.db'   # NASA CCMC DONKI: CME, HSS, GST, SEP, FLR, IPS events
GCR_DB = 'ingestionGCR.db'       # Oulu cosmic ray station: neutron monitor count rates (Oulu, Dome C), hourly and monthly
SILSO_DB = 'ingestionSILSO.db'   # WDC-SILSO: monthly mean sunspot number since 1749
TEC_DB = 'ingestionTEC.db'       # total electron content maps: CODE (Bern) observed and predicted, NOAA GloTEC; 7 days

# Site databases: what the website reads, one per type of data, each
# built and swapped in whole by scripts/publishSite.py (step 9).
SITE_ORBITAL_DB = 'siteOrbital.db'
SITE_NEWS_DB = 'siteNews.db'
SITE_SKY_DB = 'siteSky.db'
SITE_GROUND_SEGMENT_DB = 'siteGroundSegment.db'
SITE_WEATHER_DB = 'siteWeather.db'

# Pre-refactor databases the website still reads until the publish step
# (step 9) replaces them with site<Type>.db files.
ORBITAL_DB = 'orbitalObjects.db'
STATS_DB = 'onOrbitStats.db'

# Written by the website: visitor submissions (inbox<Name>.db).
BUG_REPORTS_DB = 'inboxBugReports.db'
USAGE_DB = 'inboxUsage.db'   # logins per day and city, written by the login counter

# New name -> the name the file still has in a legacy ingestionDBs/ folder.
LEGACY_NAMES = {
    GCAT_DB: 'gcat.db',
    NEWS_DB: 'space_news.db',
    GROUND_SEGMENT_DB: 'groundSegmentAssets.db',
    SKY_DB: 'skyCatalogue.db',
    BUG_REPORTS_DB: 'bugReports.db',
}


def dbPath(name):
    """Full path of database file `name` (one of the *_DB names above)."""
    return os.path.join(DB_DIR, LEGACY_NAMES.get(name, name) if LEGACY else name)


# The live server's app folder, for tools that reach it over SSH.
LIVE_ROOT = '/home/sip9rb1lekyg/public_html/LCARS-FAS'
LIVE_DB_DIRS = (f'{LIVE_ROOT}/{DB_DIR_NAME}', f'{LIVE_ROOT}/{LEGACY_DB_DIR_NAME}')
