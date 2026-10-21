"""Server side script tagging each payload in the orbital object cache
with a downlink RF band, an estimated downlink EIRP (dBW), and an
estimated satellite *receive* figure of merit -- antenna gain (dBi),
system noise temperature (K) and the resulting G/T (dB/K).

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

The downlink EIRP is a REPRESENTATIVE PEAK toward the ground, in dBW -- a
boresight-ish envelope good to a few dB at best, NOT the EIRP toward a
particular ground station's position in the beam.

The satellite receive gain / noise temperature / G/T are ALWAYS
class-typical estimates (`satGtSource = 'estimated'`), never filing-grade:
no public catalogue carries a satellite's receive figure of merit. Gain
follows the same constellation -> class resolution as the EIRP; the
receive antenna it models is the one the spacecraft would use to hear a
ground station (near-omni on a CubeSat, a spot beam on a broadband
bird, an Earth-coverage horn on a GEO comsat). Noise temperature is a
flat SAT_NOISE_TEMP_K for every Earth-pointing payload -- it barely
varies between missions because the ~290 K Earth fills the beam and
swamps LNA differences (see designAndArchitecture_0.4, On-Orbit section,
and satellite_link_budget_2.md Appendix A). Confidence is +/-3-6 dB;
useful for "could a station plausibly close this link" triage, not for
operations.
"""

import math
import sqlite3
import time

from dbPaths import ORBITAL_DB, dbPath

# 1. Same database ingestOrbitalData.py / ingestSatcat.py write to -- this
# job enriches existing rows, it never owns a database of its own.
# isolation_level=None (autocommit) + WAL, matching the sibling scripts.
db_path = dbPath(ORBITAL_DB)
db = sqlite3.connect(db_path, isolation_level=None)
db.execute('PRAGMA journal_mode = WAL;')

# 2. Migration -- add our columns if they aren't there yet. Same
# try/except-on-duplicate pattern the sibling scripts use for their own
# additive columns.
for column in ('downlinkBand TEXT', 'eirpDbw REAL', 'eirpSource TEXT',
               'satRxGainDbi REAL', 'satNoiseTempK REAL',
               'satGtDbk REAL', 'satGtSource TEXT'):
    try:
        db.execute(f'ALTER TABLE orbital_objects ADD COLUMN {column};')
    except sqlite3.OperationalError as err:
        if 'duplicate column name' not in str(err).lower():
            raise


# ---------------------------------------------------------------------------
# 3. Tier 1 -- constellation / operator -> (band, peak downlink EIRP dBW,
#    representative satellite *receive*-antenna gain dBi).
#
# Keyed by CelesTrak group name (orbital_object_groups.groupName). Checked
# in priority order (dict order): the first of an object's groups that
# appears here wins. Some entries also carry a `names` tuple of uppercase
# name prefixes -- resolve() falls back to those when CelesTrak has left a
# clearly-named constellation member out of its own group (it lags, and
# drops drifters / oddball variants). `source` applies to the EIRP only;
# `rxGainDbi` is always a class-typical estimate. The gain models the
# antenna the spacecraft would use to receive a ground station: a near-omni
# element on a small bird (~0-3 dBi), a steered spot beam on a broadband
# constellation (~30-35 dBi), an Earth-coverage horn on a GEO comsat
# (~17-20 dBi), a shaped Earth-coverage array on a GNSS bird (~13 dBi).
# ---------------------------------------------------------------------------
CONSTELLATION_EIRP = {
    # SpaceX Starlink -- Ku-band space-to-Earth user downlink (10.7-12.7
    # GHz). FCC Schedule S: per-beam peak EIRP ~37-40 dBW. Rx via the same
    # Ku phased array -> steered spot beam ~34 dBi.
    'starlink':      {'band': 'Ku', 'eirpDbw': 38.0, 'source': 'filing', 'rxGainDbi': 34.0, 'names': ('STARLINK',)},
    # OneWeb -- Ku-band user downlink (10.7-12.75 GHz). FCC/ITU filings:
    # per-beam peak EIRP ~34-37 dBW. ~16 fixed Ku beams -> ~30 dBi.
    'oneweb':        {'band': 'Ku', 'eirpDbw': 36.0, 'source': 'filing', 'rxGainDbi': 30.0, 'names': ('ONEWEB',)},
    # Amazon Kuiper -- Ka-band downlink (17.7-20.2 GHz). FCC Schedule S:
    # per-beam peak EIRP ~36-40 dBW. Ka phased array spot beam ~34 dBi.
    'kuiper':        {'band': 'Ka', 'eirpDbw': 38.0, 'source': 'filing', 'rxGainDbi': 34.0, 'names': ('KUIPER',)},
    # Iridium NEXT -- L-band user downlink (1616-1626.5 MHz) spot beams;
    # Ka feeder/crosslink not counted here. FCC: per-beam EIRP ~15-20 dBW.
    # 48-beam L-band phased array -> ~22 dBi.
    'iridium-NEXT':  {'band': 'L',  'eirpDbw': 17.0, 'source': 'filing', 'rxGainDbi': 22.0, 'names': ('IRIDIUM',)},
    # Globalstar -- S-band downlink (2483.5-2500 MHz). FCC: ~20 dBW/beam.
    # 16-beam bent-pipe S-band array -> ~16 dBi.
    'globalstar':    {'band': 'S',  'eirpDbw': 20.0, 'source': 'filing', 'rxGainDbi': 16.0, 'names': ('GLOBALSTAR',)},
    # ORBCOMM -- VHF downlink (137-138 MHz), low power. FCC: ~12 dBW.
    # Near-omni VHF -> ~2 dBi.
    'orbcomm':       {'band': 'VHF', 'eirpDbw': 12.0, 'source': 'filing', 'rxGainDbi': 2.0, 'names': ('ORBCOMM',)},
    # GNSS L-band navigation downlinks. GPS SPS PS / Galileo OS SIS ICD /
    # GLONASS / BeiDou ICDs put satellite EIRP around 26-30 dBW (newer
    # blocks at the top of that). Shaped Earth-coverage helical array (and
    # a comparable S-band command antenna) -> ~13 dBi. One figure for all.
    'gps-ops':       {'band': 'L',  'eirpDbw': 27.0, 'source': 'filing', 'rxGainDbi': 13.0},
    'glo-ops':       {'band': 'L',  'eirpDbw': 27.0, 'source': 'filing', 'rxGainDbi': 13.0},
    'galileo':       {'band': 'L',  'eirpDbw': 27.0, 'source': 'filing', 'rxGainDbi': 13.0},
    'beidou':        {'band': 'L',  'eirpDbw': 27.0, 'source': 'filing', 'rxGainDbi': 13.0},
    'sbas':          {'band': 'L',  'eirpDbw': 27.0, 'source': 'filing', 'rxGainDbi': 13.0},
    'gnss':          {'band': 'L',  'eirpDbw': 27.0, 'source': 'filing', 'rxGainDbi': 13.0},
    # Planet Labs (Dove / SuperDove / Pelican / SkySat) -- X-band payload
    # downlink (8025-8400 MHz), small sats. FCC filings: ~12-15 dBW.
    # Command via a low-gain S-band / UHF patch -> ~4 dBi.
    'planet':        {'band': 'X',  'eirpDbw': 13.0, 'source': 'filing', 'rxGainDbi': 4.0,
                      'names': ('FLOCK', 'SKYSAT', 'SUPERDOVE', 'PELICAN')},
    # Named GEO comms operators -- Ku/Ka (and C) downlinks. Peak spot-beam
    # EIRP from published footprint maps runs 48-55 dBW; representative 52.
    # TT&C / command via an Earth-coverage horn -> ~18 dBi.
    'ses':           {'band': 'Ku', 'eirpDbw': 52.0, 'source': 'filing', 'rxGainDbi': 18.0},
    'intelsat':      {'band': 'Ku', 'eirpDbw': 52.0, 'source': 'filing', 'rxGainDbi': 18.0},
    'eutelsat':      {'band': 'Ku', 'eirpDbw': 52.0, 'source': 'filing', 'rxGainDbi': 18.0},
    'telesat':       {'band': 'Ku', 'eirpDbw': 52.0, 'source': 'filing', 'rxGainDbi': 18.0},
    # --- design-class estimates (no readily-citable filing) ---
    # Chinese LEO broadband (Qianfan / "Thousand Sails" G60, GuoWang
    # "hulianwang"): Ku/Ka phased array spot beam ~34 dBi.
    'qianfan':       {'band': 'Ku', 'eirpDbw': 37.0, 'source': 'estimated', 'rxGainDbi': 34.0},
    'hulianwang':    {'band': 'Ku', 'eirpDbw': 37.0, 'source': 'estimated', 'rxGainDbi': 34.0},
    # NB: CelesTrak's 'tdrss' group is *users* of TDRSS (ISS, HST, TERRA,
    # AQUA, MMS, JPSS...), not the relay sats -- deliberately NOT mapped
    # here; those objects fall through to classify() on their own merits.
    # SAR imagers grouped by CelesTrak as 'sar' (ICEYE, Capella, Umbra):
    # X-band imagery downlink; command via a low-gain S/UHF antenna ~6 dBi.
    'sar':           {'band': 'X',  'eirpDbw': 18.0, 'source': 'estimated', 'rxGainDbi': 6.0},
    # Spire Lemur-2 -- UHF + S-band cubesat downlinks, near-omni ~1 dBi.
    'spire':         {'band': 'S',  'eirpDbw': 5.0,  'source': 'estimated', 'rxGainDbi': 1.0},
    # Argos / COSPAS-SARSAT -- UHF relay downlinks, near-omni ~2 dBi.
    'argos':         {'band': 'UHF', 'eirpDbw': 10.0, 'source': 'estimated', 'rxGainDbi': 2.0},
    'sarsat':        {'band': 'UHF', 'eirpDbw': 10.0, 'source': 'estimated', 'rxGainDbi': 2.0},
}


# ---------------------------------------------------------------------------
# 4. Tier 2 -- class -> (band, typical peak downlink EIRP dBW, typical
# satellite receive-antenna gain dBi). Used when no constellation matched;
# the class is picked by classify() below. `rxGainDbi`: near-omni on
# CubeSats/amateur (~1 dBi), a modest directional antenna on an S-band
# LEO comsat or a smallsat command receiver (~6-12 dBi), an Earth-coverage
# horn on anything at GEO (~18 dBi), a better antenna on a military
# comsat (~20 dBi).
# ---------------------------------------------------------------------------
BAND_CLASS_EIRP = {
    'comms-geo':       {'band': 'Ku', 'eirpDbw': 50.0, 'rxGainDbi': 18.0},
    'comms-leo-narrow': {'band': 'S', 'eirpDbw': 16.0, 'rxGainDbi': 12.0},
    'eo-optical':      {'band': 'X',  'eirpDbw': 14.0, 'rxGainDbi': 6.0},
    'eo-radar':        {'band': 'X',  'eirpDbw': 18.0, 'rxGainDbi': 6.0},
    'weather-leo':     {'band': 'X',  'eirpDbw': 15.0, 'rxGainDbi': 8.0},
    'weather-geo':     {'band': 'L',  'eirpDbw': 45.0, 'rxGainDbi': 18.0},
    'science':         {'band': 'S',  'eirpDbw': 12.0, 'rxGainDbi': 6.0},
    'military-comms':  {'band': 'X',  'eirpDbw': 40.0, 'rxGainDbi': 20.0},
    'cubesat':         {'band': 'UHF', 'eirpDbw': 2.0, 'rxGainDbi': 1.0},
    'amateur':         {'band': 'UHF', 'eirpDbw': 3.0, 'rxGainDbi': 1.0},
    'station':         {'band': 'S',  'eirpDbw': 10.0, 'rxGainDbi': 6.0},
}

# Flat receive-system noise temperature (K) for every Earth-pointing
# payload: the antenna sees the ~290 K Earth filling its beam, and an
# uncooled space LNA + feed add ~150 K, landing every class near 400-600 K
# with little spread. See satellite_link_budget_2.md Appendix A.4.
SAT_NOISE_TEMP_K = 500.0

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
    """(downlinkBand, eirpDbw, eirpSource, satRxGainDbi) for one object.

    The gain is None exactly when the object is a rocket body / debris or
    an unplaceable payload -- i.e. whenever there is no band either."""
    if object_type in ('R/B', 'DEB'):
        return None, None, 'none', None

    # Tier 1a -- CelesTrak group membership.
    for group_name, spec in CONSTELLATION_EIRP.items():
        if group_name in groups:
            return spec['band'], spec['eirpDbw'], spec['source'], spec['rxGainDbi']

    # Tier 1b -- name prefix, for constellation members CelesTrak has left
    # out of its own group (e.g. a drifting or DTC Starlink still named
    # STARLINK-nnnn but only in 'active').
    upper = (name or '').upper()
    for spec in CONSTELLATION_EIRP.values():
        if any(upper.startswith(p) for p in spec.get('names', ())):
            return spec['band'], spec['eirpDbw'], spec['source'], spec['rxGainDbi']

    # Tier 2 -- class-typical figure.
    cls = classify(groups, period)
    if cls is not None:
        spec = BAND_CLASS_EIRP[cls]
        return spec['band'], spec['eirpDbw'], 'estimated', spec['rxGainDbi']

    return None, None, 'unknown', None


def sat_receive_fom(rx_gain_dbi, eirp_source):
    """(satRxGainDbi, satNoiseTempK, satGtDbk, satGtSource) from the gain
    resolve() returned. Noise temperature is the flat class default for
    every payload with a gain; G/T = gain - 10 log10(T). The source tag is
    'none' for RB/debris, 'unknown' for an unplaceable payload, and always
    'estimated' when we have a value -- there is no filing-grade satellite
    G/T anywhere, whatever the EIRP tier says."""
    if rx_gain_dbi is None:
        return None, None, None, ('none' if eirp_source == 'none' else 'unknown')
    gt = round(rx_gain_dbi - 10.0 * math.log10(SAT_NOISE_TEMP_K), 1)
    return rx_gain_dbi, SAT_NOISE_TEMP_K, gt, 'estimated'


UPDATE_SQL = (
    'UPDATE orbital_objects SET downlinkBand = ?, eirpDbw = ?, eirpSource = ?, '
    'satRxGainDbi = ?, satNoiseTempK = ?, satGtDbk = ?, satGtSource = ? '
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
    gt_values = 0
    updated = 0
    for norad_id, name, object_type, period in rows:
        band, eirp, source, rx_gain = resolve(
            name, object_type, groups_by_id.get(norad_id, set()), period
        )
        gain, temp, gt, gt_source = sat_receive_fom(rx_gain, source)
        db.execute(UPDATE_SQL,
                   (band, eirp, source, gain, temp, gt, gt_source, norad_id))
        updated += 1
        by_source[source] = by_source.get(source, 0) + 1
        if band is not None:
            by_band[band] = by_band.get(band, 0) + 1
        if gt is not None:
            gt_values += 1

    print(f'  {updated} rows tagged')
    print('  by EIRP source: ' + ', '.join(
        f'{k}={v}' for k, v in sorted(by_source.items(), key=lambda kv: -kv[1])
    ))
    print('  by band:        ' + ', '.join(
        f'{k}={v}' for k, v in sorted(by_band.items(), key=lambda kv: -kv[1])
    ))
    print(f'  satellite G/T estimated for {gt_values} payload(s) '
          f'(T_sys = {SAT_NOISE_TEMP_K:.0f} K)')
    print('=== EIRP ENRICHMENT COMPLETE ===\n')
    return updated


# 6. Run once and exit -- cron owns the schedule. Cheap (pure local
# compute over ~30k rows) so it can run right after each ingestSatcat.py
# pass, or on its own daily cadence. Each run is recorded in ingestionRuns
# for the landing page's data-freshness table ("changes" = rows tagged).
if __name__ == '__main__':
    from ingestionLog import trackRun
    with trackRun(db, 'eirp') as run:
        run.changes = run_eirp_enrichment()
