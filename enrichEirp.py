"""Server side script tagging each active payload in the orbital object
cache with a downlink RF band and an estimated downlink EIRP (dBW).

Third of the ingestion scripts -- run AFTER ingestOrbitalData.py (creates
the rows and populates orbital_object_groups) and ingestSatcat.py
(objectType / owner). Pure local computation: no network, no external
fetch. Idempotent -- re-running just recomputes and overwrites.

Two tiers, recorded in the `eirpSource` column so downstream code can
weight confidence:

  * 'filing'    -- Tier 1: the object belongs to a CelesTrak group that
                  maps to a known constellation/operator whose downlink
                  EIRP is public (FCC Schedule S, ITU filings, published
                  nav ICDs, operator footprint data). One value per
                  constellation.
  * 'estimated' -- Tier 2: no constellation match, so the band is inferred
                  from the object's groups / type / orbit and the EIRP is
                  a class-typical figure from BAND_CLASS_EIRP.
  * 'none'      -- not a payload (rocket body / debris): no downlink.
  * 'unknown'   -- a payload we couldn't place in any class.

Every number is a REPRESENTATIVE PEAK downlink EIRP toward the ground, in
dBW -- a boresight-ish envelope good to a few dB at best, NOT the EIRP
toward a particular ground station's position in the beam. Fine for
"could a station plausibly close this link" triage; not for operations.
"""

import os
import sqlite3
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 1. Same database ingestOrbitalData.py / ingestSatcat.py write to -- this
# job enriches existing rows, it never owns a database of its own.
# isolation_level=None (autocommit) + WAL, matching the sibling scripts.
db_path = os.path.join(BASE_DIR, 'ingestionDBs', 'orbitalObjects.db')
db = sqlite3.connect(db_path, isolation_level=None)
db.execute('PRAGMA journal_mode = WAL;')

# 2. Migration -- add our columns if they aren't there yet. Same
# try/except-on-duplicate pattern the sibling scripts use for their own
# additive columns.
for column in ('downlinkBand TEXT', 'eirpDbw REAL', 'eirpSource TEXT'):
    try:
        db.execute(f'ALTER TABLE orbital_objects ADD COLUMN {column};')
    except sqlite3.OperationalError as err:
        if 'duplicate column name' not in str(err).lower():
            raise


# ---------------------------------------------------------------------------
# 3. Tier 1 -- constellation / operator -> (band, peak downlink EIRP dBW).
#
# Keyed by CelesTrak group name (orbital_object_groups.groupName). Checked
# in priority order (dict order): the first of an object's groups that
# appears here wins. Some entries also carry a `names` tuple of uppercase
# name prefixes -- resolve() falls back to those when CelesTrak has left a
# clearly-named constellation member out of its own group (it lags, and
# drops drifters / oddball variants). Values and their bases are noted per
# row; a design-class estimate rather than a citable filing carries
# source='estimated' explicitly.
# ---------------------------------------------------------------------------
CONSTELLATION_EIRP = {
    # SpaceX Starlink -- Ku-band space-to-Earth user downlink (10.7-12.7
    # GHz). FCC Schedule S: per-beam peak EIRP ~37-40 dBW.
    'starlink':      {'band': 'Ku', 'eirpDbw': 38.0, 'source': 'filing', 'names': ('STARLINK',)},
    # OneWeb -- Ku-band user downlink (10.7-12.75 GHz). FCC/ITU filings:
    # per-beam peak EIRP ~34-37 dBW.
    'oneweb':        {'band': 'Ku', 'eirpDbw': 36.0, 'source': 'filing', 'names': ('ONEWEB',)},
    # Amazon Kuiper -- Ka-band downlink (17.7-20.2 GHz). FCC Schedule S:
    # per-beam peak EIRP ~36-40 dBW.
    'kuiper':        {'band': 'Ka', 'eirpDbw': 38.0, 'source': 'filing', 'names': ('KUIPER',)},
    # Iridium NEXT -- L-band user downlink (1616-1626.5 MHz) spot beams;
    # Ka feeder/crosslink not counted here. FCC: per-beam EIRP ~15-20 dBW.
    'iridium-NEXT':  {'band': 'L',  'eirpDbw': 17.0, 'source': 'filing', 'names': ('IRIDIUM',)},
    # Globalstar -- S-band downlink (2483.5-2500 MHz). FCC: ~20 dBW/beam.
    'globalstar':    {'band': 'S',  'eirpDbw': 20.0, 'source': 'filing', 'names': ('GLOBALSTAR',)},
    # ORBCOMM -- VHF downlink (137-138 MHz), low power. FCC: ~12 dBW.
    'orbcomm':       {'band': 'VHF', 'eirpDbw': 12.0, 'source': 'filing', 'names': ('ORBCOMM',)},
    # GNSS L-band navigation downlinks. GPS SPS PS / Galileo OS SIS ICD /
    # GLONASS / BeiDou ICDs put satellite EIRP around 26-30 dBW (newer
    # blocks at the top of that). One figure for all of them.
    'gps-ops':       {'band': 'L',  'eirpDbw': 27.0, 'source': 'filing'},
    'glo-ops':       {'band': 'L',  'eirpDbw': 27.0, 'source': 'filing'},
    'galileo':       {'band': 'L',  'eirpDbw': 27.0, 'source': 'filing'},
    'beidou':        {'band': 'L',  'eirpDbw': 27.0, 'source': 'filing'},
    'sbas':          {'band': 'L',  'eirpDbw': 27.0, 'source': 'filing'},
    'gnss':          {'band': 'L',  'eirpDbw': 27.0, 'source': 'filing'},
    # Planet Labs (Dove / SuperDove / Pelican / SkySat) -- X-band payload
    # downlink (8025-8400 MHz), small sats. FCC filings: ~12-15 dBW.
    'planet':        {'band': 'X',  'eirpDbw': 13.0, 'source': 'filing',
                      'names': ('FLOCK', 'SKYSAT', 'SUPERDOVE', 'PELICAN')},
    # Named GEO comms operators -- Ku/Ka (and C) downlinks. Peak spot-beam
    # EIRP from published footprint maps runs 48-55 dBW; representative 52.
    'ses':           {'band': 'Ku', 'eirpDbw': 52.0, 'source': 'filing'},
    'intelsat':      {'band': 'Ku', 'eirpDbw': 52.0, 'source': 'filing'},
    'eutelsat':      {'band': 'Ku', 'eirpDbw': 52.0, 'source': 'filing'},
    'telesat':       {'band': 'Ku', 'eirpDbw': 52.0, 'source': 'filing'},
    # --- design-class estimates (no readily-citable filing) ---
    # Chinese LEO broadband (Qianfan / "Thousand Sails" G60, GuoWang
    # "hulianwang"): Ku/Ka, treated as the broadband-LEO class figure.
    'qianfan':       {'band': 'Ku', 'eirpDbw': 37.0, 'source': 'estimated'},
    'hulianwang':    {'band': 'Ku', 'eirpDbw': 37.0, 'source': 'estimated'},
    # NB: CelesTrak's 'tdrss' group is *users* of TDRSS (ISS, HST, TERRA,
    # AQUA, MMS, JPSS...), not the relay sats -- deliberately NOT mapped
    # here; those objects fall through to classify() on their own merits.
    # SAR imagers grouped by CelesTrak as 'sar' (ICEYE, Capella, Umbra):
    # X-band imagery downlink, higher rate than optical smallsats.
    'sar':           {'band': 'X',  'eirpDbw': 18.0, 'source': 'estimated'},
    # Spire Lemur-2 -- UHF + S-band cubesat downlinks, low EIRP.
    'spire':         {'band': 'S',  'eirpDbw': 5.0,  'source': 'estimated'},
    # Argos / COSPAS-SARSAT -- UHF relay downlinks, low EIRP.
    'argos':         {'band': 'UHF', 'eirpDbw': 10.0, 'source': 'estimated'},
    'sarsat':        {'band': 'UHF', 'eirpDbw': 10.0, 'source': 'estimated'},
}


# ---------------------------------------------------------------------------
# 4. Tier 2 -- class -> (band, typical peak downlink EIRP dBW). Used when
# no constellation matched; the class is picked by classify() below.
# ---------------------------------------------------------------------------
BAND_CLASS_EIRP = {
    'comms-geo':       {'band': 'Ku', 'eirpDbw': 50.0},
    'comms-leo-narrow': {'band': 'S', 'eirpDbw': 16.0},
    'eo-optical':      {'band': 'X',  'eirpDbw': 14.0},
    'eo-radar':        {'band': 'X',  'eirpDbw': 18.0},
    'weather-leo':     {'band': 'X',  'eirpDbw': 15.0},
    'weather-geo':     {'band': 'L',  'eirpDbw': 45.0},
    'science':         {'band': 'S',  'eirpDbw': 12.0},
    'military-comms':  {'band': 'X',  'eirpDbw': 40.0},
    'cubesat':         {'band': 'UHF', 'eirpDbw': 2.0},
    'amateur':         {'band': 'UHF', 'eirpDbw': 3.0},
    'station':         {'band': 'S',  'eirpDbw': 10.0},
}

# GEO if the orbital period is within this window (minutes). A sidereal
# day is ~1436 min; the band is wide enough to also catch inclined /
# slightly-drifting GEO and near-GEO without pulling in HEO or MEO.
GEO_PERIOD_MIN, GEO_PERIOD_MAX = 1350.0, 1550.0


def classify(groups, period):
    """Return a BAND_CLASS_EIRP key for a payload with no constellation
    match, or None if it can't be placed. `groups` is the set of that
    object's CelesTrak group names."""
    is_geo = period is not None and GEO_PERIOD_MIN <= period <= GEO_PERIOD_MAX

    # A crewed station is a station first, even though it's typically also
    # tagged amateur / satnogs / visual.
    if groups & {'stations'}:
        return 'station'
    if groups & {'weather'}:
        return 'weather-geo' if is_geo else 'weather-leo'
    if groups & {'radar'}:
        return 'eo-radar'
    if groups & {'resource', 'dmc', 'geodetic'}:
        return 'eo-optical'
    if groups & {'science', 'engineering', 'education'}:
        return 'science'
    if groups & {'amateur'}:
        return 'amateur'
    if groups & {'cubesat', 'satnogs'}:
        return 'cubesat'
    if groups & {'military', 'x-comm'}:
        return 'military-comms'
    if groups & {'geo'}:
        return 'comms-geo'
    if groups & {'other-comm'}:
        return 'comms-geo' if is_geo else 'comms-leo-narrow'
    return None


def resolve(name, object_type, groups, period):
    """(downlinkBand, eirpDbw, eirpSource) for one object."""
    if object_type in ('R/B', 'DEB'):
        return None, None, 'none'

    # Tier 1a -- CelesTrak group membership.
    for group_name, spec in CONSTELLATION_EIRP.items():
        if group_name in groups:
            return spec['band'], spec['eirpDbw'], spec['source']

    # Tier 1b -- name prefix, for constellation members CelesTrak has left
    # out of its own group (e.g. a drifting or DTC Starlink still named
    # STARLINK-nnnn but only in 'active').
    upper = (name or '').upper()
    for spec in CONSTELLATION_EIRP.values():
        if any(upper.startswith(p) for p in spec.get('names', ())):
            return spec['band'], spec['eirpDbw'], spec['source']

    # Tier 2 -- class-typical figure.
    cls = classify(groups, period)
    if cls is not None:
        spec = BAND_CLASS_EIRP[cls]
        return spec['band'], spec['eirpDbw'], 'estimated'

    return None, None, 'unknown'


UPDATE_SQL = (
    'UPDATE orbital_objects SET downlinkBand = ?, eirpDbw = ?, eirpSource = ? '
    'WHERE noradID = ?'
)


# 5. Main enrichment run
def run_eirp_enrichment():
    print(f'\n=== [{time.strftime("%H:%M:%S")}] Starting EIRP Enrichment ===')

    # noradID -> set of its CelesTrak group names.
    groups_by_id = {}
    for norad_id, group_name in db.execute(
        'SELECT noradID, groupName FROM orbital_object_groups'
    ):
        groups_by_id.setdefault(norad_id, set()).add(group_name)

    rows = db.execute(
        'SELECT noradID, name, objectType, period FROM orbital_objects'
    ).fetchall()

    by_source = {}
    by_band = {}
    updated = 0
    for norad_id, name, object_type, period in rows:
        band, eirp, source = resolve(
            name, object_type, groups_by_id.get(norad_id, set()), period
        )
        db.execute(UPDATE_SQL, (band, eirp, source, norad_id))
        updated += 1
        by_source[source] = by_source.get(source, 0) + 1
        if band is not None:
            by_band[band] = by_band.get(band, 0) + 1

    print(f'  {updated} rows tagged')
    print('  by source: ' + ', '.join(
        f'{k}={v}' for k, v in sorted(by_source.items(), key=lambda kv: -kv[1])
    ))
    print('  by band:   ' + ', '.join(
        f'{k}={v}' for k, v in sorted(by_band.items(), key=lambda kv: -kv[1])
    ))
    print('=== EIRP ENRICHMENT COMPLETE ===\n')


# 6. Run once and exit -- cron owns the schedule. Cheap (pure local
# compute over ~30k rows) so it can run right after each ingestSatcat.py
# pass, or on its own daily cadence.
if __name__ == '__main__':
    run_eirp_enrichment()
