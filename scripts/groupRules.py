"""Satellite group membership -- 'active', 'stations', 'starlink' and the
constellation groups the link budget uses -- by our own documented rules,
with CelesTrak's lists definitive whenever they are available.

Decision A of 0_documentation/dbRefactorPlan.md (extended 2026-10-21).
Used by the publish step (publishSite.py) to build siteOrbital.db's
orbital_object_groups.

PRECEDENCE, per group and object:
  1. CelesTrak, when "available": its latest successful fetch of that
     group is at most CELESTRAK_MAX_AGE_DAYS old. Its list is definitive
     for every object launched before that fetch -- in the list means a
     member, absent means not.
  2. The recent-launch rule (active only): a payload launched within
     RECENT_LAUNCH_DAYS (3 months) counts as active unless proven
     otherwise -- a CelesTrak fetch after its launch leaves it out, or it
     has decayed. Catalogues take weeks to record a new satellite's
     status, so new launches are assumed to be working.
  3. Our own rules (RULES, below), for everything else: objects launched
     after CelesTrak's fetch, and every object when CelesTrak isn't
     available (the live server has been blocked by CelesTrak since
     2026-08-27).
Groups with no rule here (weather, cubesat, geo, ...) come from CelesTrak
only, and are absent while it isn't available.

OUR RULES work from the object's Space-Track record and its GCAT entry
(owner code, programme, payload category, operations-end date):
  - active:   a payload in orbit with no GCAT operations-end date
              (gcatPayloads.tOp). On the August data this agreed with
              CelesTrak for 97% of on-orbit payloads. A payload GCAT
              doesn't list yet is active only under the recent-launch rule.
  - stations: GCAT payload category SS (station modules and the crewed
              and cargo craft docked to them), or, for craft too new for
              GCAT, a crewed/cargo vehicle name.
  - constellation groups: an active payload whose GCAT owner code or
              programme belongs to the constellation (or, for the
              function groups sar / gnss / sbas / sarsat / argos, whose
              payload category or programme does); for payloads GCAT
              doesn't list yet, a name prefix.
Each rule's agreement with CelesTrak's latest list is measured on every
publish (agreement()), so drift shows up.
"""

from datetime import datetime, timedelta, timezone

RECENT_LAUNCH_DAYS = 91
CELESTRAK_MAX_AGE_DAYS = 14

# Crewed and cargo craft that visit stations, for those not yet in GCAT.
STATION_VEHICLE_NAMES = ('ISS ', 'CSS ', 'SOYUZ', 'PROGRESS', 'CREW DRAGON', 'DRAGON', 'CYGNUS',
                         'TIANZHOU', 'SHENZHOU', 'HTV', 'DREAM CHASER', 'STARLINER')

# Constellation rules. owners: GCAT owner codes; programs: GCAT programme
# prefixes; categories: GCAT payload categories; names: name prefixes,
# used only for payloads GCAT doesn't list yet. A payload matches when
# any of its GCAT fields matches (or, without GCAT, its name does).
RULES = {
    'starlink':     {'owners': {'SPXS'}, 'names': ('STARLINK',)},
    'oneweb':       {'owners': {'ONEWEB', 'ONEWEBN', 'ONEWEBE'}, 'names': ('ONEWEB',)},
    'kuiper':       {'owners': {'KUIP'}, 'names': ('KUIPER',)},
    'iridium-NEXT': {'programs': ('Iridium Next',), 'names': ('IRIDIUM',)},
    'globalstar':   {'owners': {'GLOBL', 'GLOB'}, 'names': ('GLOBALSTAR',)},
    'orbcomm':      {'owners': {'ORBC'}, 'names': ('ORBCOMM',)},
    'gps-ops':      {'programs': ('GPS ',), 'names': ('NAVSTAR', 'GPS ')},
    'glo-ops':      {'programs': ('Uragan', 'Glonass'), 'names': ('GLONASS',)},
    'galileo':      {'programs': ('Galileo',), 'names': ('GALILEO',)},
    'beidou':       {'programs': ('Beidou-2', 'Beidou-3'), 'names': ('BEIDOU',)},
    'sbas':         {'programs': ('QZSS', 'Luch5', 'Beidou-3G', 'GSAT', 'WAAS', 'EGNOS', 'SDCM'), 'names': ('QZS',)},
    'gnss':         {'categories': {'NAV', 'NAV/COM'},
                     'names': ('NAVSTAR', 'GPS ', 'GALILEO', 'BEIDOU', 'GLONASS', 'QZS', 'IRNSS', 'NVS')},
    'planet':       {'owners': {'PLAN', 'PLABST', 'TBELLA', 'SKYBOX'}, 'names': ('FLOCK', 'SKYSAT', 'PELICAN', 'TANAGER')},
    'ses':          {'owners': {'O3BS', 'O3B', 'SESSA', 'SESSL', 'SES', 'SESGS'}, 'names': ('SES', 'O3B', 'ASTRA')},
    'intelsat':     {'owners': {'INTELU', 'INTELD', 'INTEL', 'PAN'}, 'names': ('INTELSAT', 'GALAXY', 'HORIZONS')},
    'eutelsat':     {'owners': {'EUTSA', 'EUTAM', 'EUTEL'}, 'names': ('EUTELSAT', 'EUTE ', 'HOTBIRD')},
    'telesat':      {'owners': {'TCANL', 'TCAN', 'TSKY', 'TELES'}, 'names': ('NIMIQ', 'ANIK', 'TELSTAR', 'TELESAT')},
    'qianfan':      {'owners': {'YUANX'}, 'programs': ('Qianfan',), 'names': ('QIANFAN',)},
    'hulianwang':   {'owners': {'ZXW'}, 'programs': ('HWD',), 'names': ('HULIANWANG',)},
    'sar':          {'categories': {'IMG-R'}, 'names': ('ICEYE', 'CAPELLA', 'QPS', 'STRIX', 'UMBRA')},
    'spire':        {'owners': {'SPIRE', 'SPIREL', 'SPIREG', 'ORORA'}, 'names': ('LEMUR',)},
    'argos':        {'owners': {'KINEIS'}, 'programs': ('METOP', 'NOAA', 'SARAL', 'Kineis'), 'names': ('KINEIS',)},
    'sarsat':       {'programs': ('Galileo', 'GPS IIF', 'GPS IIR', 'GPS III', 'Beidou-3M', 'Meteosat', 'GOES',
                                  'NOAA', 'METOP', 'Elektro', 'Meteor-M'),
                     'names': ('GALILEO', 'NAVSTAR', 'GOES', 'METEOSAT', 'NOAA')},
}
RULE_GROUPS = ('active', 'stations') + tuple(RULES)


def parseDate(text):
    if not text:
        return None
    try:
        return datetime.fromisoformat(str(text)[:10]).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def ruleMembers(objects, now):
    """{group: set(noradID)} by our own rules alone. `objects`: dicts with
    noradID, name, objectType ('PAY', ...), launchDate, decayDate, and the
    GCAT fields inGcat, ownerCode, program, category, tOp."""
    recent = now - timedelta(days=RECENT_LAUNCH_DAYS)
    members = {group: set() for group in RULE_GROUPS}
    for o in objects:
        if o['decayDate'] or o['objectType'] != 'PAY':
            continue
        name = (o['name'] or '').upper()
        launched = parseDate(o['launchDate'])
        newLaunch = launched is not None and launched >= recent
        if o['inGcat']:
            active = not o['tOp'] or newLaunch
        else:
            active = newLaunch
        if active:
            members['active'].add(o['noradID'])
        category = o['category'] or ''
        if category.startswith('SS') or (not o['inGcat'] and name.startswith(STATION_VEHICLE_NAMES)):
            members['stations'].add(o['noradID'])
        if not active:
            continue
        for group, rule in RULES.items():
            if o['inGcat']:
                hit = (o['ownerCode'] in rule.get('owners', ())
                       or (o['program'] or '').startswith(rule.get('programs', ()) or ('\0',))
                       or category in rule.get('categories', ()))
            else:
                hit = name.startswith(rule.get('names', ()) or ('\0',))
            if hit:
                members[group].add(o['noradID'])
    return members


def parseStamp(text):
    """A run timestamp ('2026-10-21T16:57:36Z') as a UTC datetime."""
    return datetime.strptime(text, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)


def celestrakAvailable(lastSuccess, now):
    """True when a group's latest successful fetch is recent enough."""
    return bool(lastSuccess) and now - parseStamp(lastSuccess) <= timedelta(days=CELESTRAK_MAX_AGE_DAYS)


def groupMembers(objects, celestrak, now):
    """{group: set(noradID)} for the site, applying the precedence in the
    module docstring. celestrak: {group: (lastSuccess, set(noradID))} from
    ingestionCelesTrak.db, for every group it has fetched."""
    byID = {o['noradID']: o for o in objects}
    ours = ruleMembers(objects, now)
    result = {}
    for group in sorted(set(RULE_GROUPS) | set(celestrak)):
        lastSuccess, listed = celestrak.get(group, (None, set()))
        if not celestrakAvailable(lastSuccess, now):
            result[group] = set(ours.get(group, set()))   # rule groups only; others absent
            continue
        fetched = parseStamp(lastSuccess)
        members = {n for n in listed if n in byID}
        if group in ours:
            # Objects launched after CelesTrak's fetch: our rules decide.
            for n in ours[group]:
                launched = parseDate(byID[n]['launchDate'])
                if launched is not None and launched > fetched:
                    members.add(n)
        result[group] = members
    return {group: members for group, members in result.items() if members}


def agreement(objects, celestrak, now):
    """[(group, ours, celestraks, both, agreementPercent)] for every rule
    group CelesTrak has a list for -- how far our rules alone reproduce
    CelesTrak's membership, over objects both can see."""
    byID = {o['noradID'] for o in objects}
    ours = ruleMembers(objects, now)
    rows = []
    for group in RULE_GROUPS:
        if group not in celestrak:
            continue
        listed = {n for n in celestrak[group][1] if n in byID}
        mine = ours[group]
        union = mine | listed
        both = mine & listed
        rows.append((group, len(mine), len(listed), len(both), round(100 * len(both) / len(union), 1) if union else 100.0))
    return rows
