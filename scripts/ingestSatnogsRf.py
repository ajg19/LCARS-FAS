"""Server side script supplementing the orbital object cache with SatNOGS
DB transmitter data -- real downlink / uplink centre frequencies, mode and
baud, keyed by NORAD ID.

Fourth of the ingestion scripts. Needs the rows from ingestOrbitalData.py;
independent of ingestSatcat.py (objectType / owner) and enrichEirp.py
(downlink band + EIRP + satellite G/T) -- it writes its own disjoint
columns and never inserts or deletes a row.

Source: https://db.satnogs.org/api/transmitters/ -- the crowd-sourced
SatNOGS DB, one record per transmitter / transceiver / transponder. A
single unauthenticated GET of the full set (~5k records, ~4 MB). Coverage
is the amateur / CubeSat / university-smallsat / weather-satellite segment
(~2.6k satellites); large commercial GEO/LEO comms, military and most
operational government payloads are absent. Data is CC BY-SA; every field
is community-entered, so frequency_violation / unconfirmed records are
deprioritised and status / updated break ties.

Columns written (all left NULL when a satellite has no usable record):

  * dlFreqHz       -- chosen downlink centre frequency, Hz
  * ulFreqHz       -- chosen uplink centre frequency, Hz (only ~300 sats:
                      the transceiver / transponder records)
  * dlBandwidthHz  -- downlink passband span, Hz (transponders only; NULL
                      for a fixed channel -- derive from baud downstream)
  * rfMode         -- modulation of the chosen downlink (FM, BPSK, GMSK...)
  * rfBaud         -- baud of the chosen downlink, or NULL
  * rfSource       -- 'satnogs' when the columns above are populated

These are the Tier-1 ("filing") frequency inputs for the link budget:
downstream code should prefer dlFreqHz over the enrichEirp downlinkBand
mid-point, and treat ulFreqHz as the only non-guessed uplink frequency.
See designAndArchitecture_0.4 (On-Orbit section) and
satellite_link_budget_2.md Appendix A.2.

Idempotent: a run clears every prior rfSource='satnogs' tag first, then
re-populates from the fresh fetch, so a satellite dropped from SatNOGS
loses its stale RF data. A failed fetch leaves the database untouched.

Scheduling is owned by cron, not this script -- SatNOGS transmitter data
changes on the order of days-to-weeks, so a weekly cadence right after
ingestSatcat.py / enrichEirp.py is ample.
"""

import json
import sqlite3
import time

from common import httpGet
from dbPaths import ORBITAL_DB, dbPath
from rfSelection import choose_rf

# 1. Same database the sibling scripts write to -- this job enriches
# existing rows, it never owns a database of its own. isolation_level=None
# (autocommit) + WAL, matching the sibling scripts.
db_path = dbPath(ORBITAL_DB)
db = sqlite3.connect(db_path, isolation_level=None)
db.execute('PRAGMA journal_mode = WAL;')

# 2. Migration -- add our columns if they aren't there yet. Same
# try/except-on-duplicate pattern the sibling scripts use.
for column in ('dlFreqHz REAL', 'ulFreqHz REAL', 'dlBandwidthHz REAL',
               'rfMode TEXT', 'rfBaud REAL', 'rfSource TEXT'):
    try:
        db.execute(f'ALTER TABLE orbital_objects ADD COLUMN {column};')
    except sqlite3.OperationalError as err:
        if 'duplicate column name' not in str(err).lower():
            raise


SATNOGS_TRANSMITTERS_URL = 'https://db.satnogs.org/api/transmitters/?format=json'
HTTP_HEADERS = {
    'User-Agent': 'LCARS-FAS/1.0 (orbital-object RF enrichment; +https://github.com/ajg19/LCARS-FAS)',
    'Accept': 'application/json',
}
# 3. Fetch -- one GET of the whole transmitter set. The endpoint returns a
# bare JSON list; a DRF {"results": [...]} shape is tolerated in case that
# ever changes.
def fetch_transmitters():
    status, text = httpGet(SATNOGS_TRANSMITTERS_URL, HTTP_HEADERS)
    if status >= 400:
        raise Exception(f'HTTP {status}')
    data = json.loads(text)
    return data if isinstance(data, list) else data.get('results', [])


CLEAR_SQL = (
    "UPDATE orbital_objects SET dlFreqHz = NULL, ulFreqHz = NULL, "
    "dlBandwidthHz = NULL, rfMode = NULL, rfBaud = NULL, rfSource = NULL "
    "WHERE rfSource = 'satnogs'"
)
UPDATE_SQL = (
    'UPDATE orbital_objects SET dlFreqHz = ?, ulFreqHz = ?, dlBandwidthHz = ?, '
    "rfMode = ?, rfBaud = ?, rfSource = 'satnogs' WHERE noradID = ?"
)


# 4. Main enrichment run
def run_satnogs_rf_ingestion():
    """Returns the number of catalogue objects given RF data, or None if
    the SatNOGS fetch failed (database left unchanged)."""
    print(f'\n=== [{time.strftime("%H:%M:%S")}] Starting SatNOGS RF Ingestion ===')

    try:
        records = fetch_transmitters()
    except Exception as err:
        print(f'  [satnogs] ERROR {err} -- database left unchanged')
        return None
    print(f'  [satnogs] {len(records)} transmitter records fetched')

    by_norad = {}
    for tx in records:
        norad = tx.get('norad_cat_id')
        if isinstance(norad, int) and not isinstance(norad, bool) and norad > 0:
            by_norad.setdefault(norad, []).append(tx)

    # Clear the previous run's tags first, so a satellite SatNOGS has since
    # dropped doesn't keep stale RF data.
    db.execute(CLEAR_SQL)

    matched = with_uplink = with_baud = 0
    modes = {}
    for norad, txs in by_norad.items():
        chosen = choose_rf(txs)
        if chosen is None:
            continue
        dl_hz, ul_hz, span, mode, baud = chosen
        cursor = db.execute(UPDATE_SQL, (dl_hz, ul_hz, span, mode, baud, norad))
        if cursor.rowcount == 0:
            continue  # SatNOGS lists it, our catalogue doesn't
        matched += 1
        if ul_hz is not None:
            with_uplink += 1
        if baud is not None:
            with_baud += 1
        if mode:
            modes[mode] = modes.get(mode, 0) + 1

    print(f'  {matched} catalogue objects given SatNOGS RF data '
          f'({with_uplink} with an uplink frequency, {with_baud} with baud)')
    if modes:
        top = ', '.join(f'{k}={v}' for k, v in
                        sorted(modes.items(), key=lambda kv: -kv[1])[:8])
        print(f'  top modes: {top}')
    print('=== SatNOGS RF INGESTION COMPLETE ===\n')
    return matched


# 5. Run once and exit -- cron owns the schedule. Each run is recorded in
# ingestionRuns for the landing page's data-freshness table; a failed
# SatNOGS fetch is recorded as a failed run.
if __name__ == '__main__':
    from ingestionLog import trackRun
    with trackRun(db, 'satnogsRf') as run:
        run.changes = run_satnogs_rf_ingestion()
        if run.changes is None:
            run.failed = True
            run.note = 'SatNOGS transmitter fetch failed -- database left unchanged'
