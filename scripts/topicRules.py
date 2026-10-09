"""Rules assigning news articles to the topics behind the news filter
buttons 02-10 (see the 'news' registerPanelControls() call in
assets/lcars.js). An article can carry several topics -- a Sentinel launch
is launch, onOrbit and eo at once -- and one matching no rule is tagged
'other', so gaps in the rules stay visible in the data.

Matching is on title + description together. Topic keys are what
api/news?topic=... takes, so they must match the topic each news button
passes in assets/lcars.js.
"""

import re

TOPIC_RULES = {
    'launch': re.compile(
        r'\blaunch(es|ed|ing)?\b|\brockets?\b|\bliftoff\b|\bFalcon\b|\bStarship\b|New Glenn|Vulcan Centaur'
        r'|\bAriane\b|\bVega\b|Electron|Neutron|\bLong March\b|\bboosters?\b|\bspaceports?\b|Starbase'
        r'|\blaunch (site|pad|vehicle)',
        re.IGNORECASE),
    'onOrbit': re.compile(
        r'\bsatellites?\b|\bconstellations?\b|\bStarlink\b|\bKuiper\b|OneWeb|BlueBird|\bspace station\b|\bISS\b'
        r'|\bspacewalks?\b|\bon-orbit\b|\bin orbit\b|\bdebris\b|\bspace junk\b|\bdocking\b|\bastronauts?\b'
        r'|\bTiangong\b|\bStarliner\b|\bDragon\b|\bmicrogravity\b',
        re.IGNORECASE),
    'groundSegment': re.compile(
        r'ground stations?|\bantennas?\b|\bdish(es)?\b|Deep Space Network|\bDSN\b|\bspectrum\b|\brelay\b'
        r'|\bdownlink|\buplink|\bjamming\b|\bspoofing\b|\bteleports?\b|laser comm|optical (data|network|comm)'
        r'|\btracking station|\bmission control\b|\bground segment\b|\bGNSS\b|\bGPS\b|\bnavigation\b',
        re.IGNORECASE),
    'deepSpace': re.compile(
        r'\bmoon\b|\blunar\b|\bMars\b|\bMartian\b|\bArtemis\b|\btelescopes?\b|\bgalax(y|ies)\b|black holes?'
        r'|\bexoplanets?\b|\bnebula\b|\bPluto\b|\bWebb\b|\bJWST\b|\bHubble\b|\basteroids?\b|\bcomets?\b'
        r'|\bJupiter\b|\bSaturn\b|\bVenus\b|\bMercury\b|\bNeptune\b|\bUranus\b|\bquasars?\b|\bsupernova'
        r'|\bdark matter\b|\bpulsars?\b|\binterstellar\b|\bChang.e\b|\bRoman Space Telescope\b|\brover\b'
        r'|\bstars?\b|\bastronom|Milky Way|\bobservator(y|ies)\b|solar system|\bexoworlds?\b|Betelgeuse',
        re.IGNORECASE),
    'orgs': re.compile(
        r'\bpolicy\b|\bcontracts?\b|\bearnings\b|\bIPO\b|\btariffs?\b|\bfunding\b|\braises?\b|\bbankrupt'
        r'|\bawards?\b|\bacqui(re|res|red|sition)\b|\binvest(s|ed|ment|ors?)?\b|\bbudget\b|\bCEO\b'
        r'|\bregulat(ion|ory|or)s?\b|\bstartup\b|\bmerger\b|\bagency\b|\bCongress\b|\bexport\b|\bcompany\b',
        re.IGNORECASE),
    'sky': re.compile(
        r'\beclipse\b|meteor shower|\bPerseid|\baurora\b|northern lights|full moon|\bskywatch|night sky'
        r'|blood moon|planet parade|\bsupermoon\b',
        re.IGNORECASE),
    'defence': re.compile(
        r'Space Force|\bUSSF\b|\bdefen[cs]e\b|\bmilitary\b|\bmissiles?\b|\bNRO\b|\bISR\b|space wars?'
        r'|counterspace|\bweapons?\b|Pentagon|\bDoD\b|national security|Golden Dome|\bspy satellite'
        r'|\barmed forces\b|\bNATO\b|space domain awareness|\bspace awareness\b',
        re.IGNORECASE),
    # Unambiguous terms only -- see TITLE_ONLY_RULES for the rest.
    'finance': re.compile(
        r'\bmerg(er|ers|ed|ing)\b|\btakeover\b|\bbuyout\b|\btakes [\d.]+% stake\b|\bstake in\b'
        r'|\bprivate[- ]equity\b|\bIPO\b|\bgoing public\b|\bpublic(ly)? (offering|traded)\b|\bSPAC\b'
        r'|\bfunding round\b|\bSeries [A-F]\b|\bseed (round|funding)\b|\braise[sd]? \$|\bvaluation\b'
        r'|\bventure capital\b|\bearnings\b|\bnet loss\b|\bsenior notes\b|\bprivate placement\b|\bbankrupt'
        r'|\bshareholders?\b|\bstock (price|market)\b',
        re.IGNORECASE),
    'eo': re.compile(
        r'Earth[- ]observ|\bEO\b|\bSentinel|Copernicus|Landsat|\bglaciers?\b|ice loss|ice sheet|\bforests?\b'
        r'|\bbiomass\b|\bwildfires?\b|air quality|\bclimate\b|\bfloods?\b|\bdrought\b|sea level|hyperspectral'
        r'|\bTEMPO\b|weather satellite|\bMTG-|Meteosat|\bSAR\b|radar imag|\bimaging constellation',
        re.IGNORECASE),
}

# Words that mean the topic in a headline but are too common in passing in
# descriptions -- "acquired images", "investments in Arctic defence" --
# so they're only matched against the title.
TITLE_ONLY_RULES = {
    'finance': re.compile(
        r'\bacqui(re|res|red|ring|sition)\b|\binvest(s|ed|ment|ments|or|ors)?\b|\braises\b'
        r'|\brevenue\b|\bprofits?\b|\bfunding\b',
        re.IGNORECASE),
}

# Feeds whose every article belongs to a topic, whatever its wording.
SOURCE_TOPICS = {
    'US Space Force': ['defence'],
    'ESA EO': ['eo'],
    'ESA Launchers': ['launch'],
    'ESA Navigation': ['groundSegment'],
    'ESA Science': ['deepSpace'],
}

# Base/station names mention the Space Force without the story being about
# defence -- every Vandenberg or Cape Canaveral launch would otherwise land
# under defence -- so they're removed before the defence rule runs.
SPACE_FORCE_PLACE_NAMES = re.compile(r'Space Force (Base|Station)|\bSF[BS]\b', re.IGNORECASE)

# Wording that looks financial but isn't: "acquisition" in the military
# procurement sense, an agency's name, and buying land -- removed before
# the finance rule runs, the same way as SPACE_FORCE_PLACE_NAMES above.
NOT_FINANCE = re.compile(
    r'\b(space|defen[cs]e|military) acquisition\b|\bacquisition (lead|wins|integration|reform|workforce|programs?)\b'
    r'|Defen[cs]e Investment Agency|\bacquire [\d,]+ acres\b',
    re.IGNORECASE)

TOPIC_KEYS = list(TOPIC_RULES)


def classifyTopics(source, title, description):
    """Returns the sorted list of topics for one article -- ['other'] if no
    rule matches."""
    text = f'{title or ""} {description or ""}'
    textForTopic = {
        'defence': SPACE_FORCE_PLACE_NAMES.sub('', text),
        'finance': NOT_FINANCE.sub('', text),
    }
    topics = {
        topic for topic, pattern in TOPIC_RULES.items()
        if pattern.search(textForTopic.get(topic, text))
    }
    for topic, pattern in TITLE_ONLY_RULES.items():
        if pattern.search(NOT_FINANCE.sub('', title or '')):
            topics.add(topic)
    topics.update(SOURCE_TOPICS.get(source, []))
    return sorted(topics) or ['other']
