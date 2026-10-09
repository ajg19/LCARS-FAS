"""Rules deciding which news articles are filler -- entertainment, shopping,
recurring daily features and agency admin notices -- rather than space news.

Shared by readNews.py (filler is never stored) and pruneNews.py (filler
already stored is deleted, so a rule change also applies retroactively),
so the two can never disagree about what counts as filler.

Matching is on the title only: descriptions are too loose to judge by.
Each rule is (ruleName, sources, pattern) -- sources None means the rule
applies to every feed; otherwise only to the named feeds, for patterns that
are safe on one feed but not another (e.g. "review" on Space.com is a
product/film review, but on SpaceNews could be a government review board).
"""

import re

FILLER_RULES = [
    ('dailyFeatures', None, re.compile(
        r'photo of the day'
        r'|^\s*on this day in space'
        r'|^\s*APOD:'
        r'|this week in space podcast',
        re.IGNORECASE)),
    ('nasaAdmin', ['NASA News'], re.compile(
        r'^\s*JOB OPPORTUNIT'
        r'|^\s*TB \d'
        r'|\bInvites Media\b',
        re.IGNORECASE)),
    ('entertainment', ['Space.com'], re.compile(
        r'\breview\b'
        r'|\(interview\)'
        r'|\btrailer\b'
        r'|\bseason \d'
        r'|\bepisode\b'
        r'|Star Wars|Star Trek|Strange New Worlds|Blade Runner|Warhammer|Gears of War'
        r'|\bSilo\b|\bThe Ark\b|Dark Matter. season'
        r'|\bmovie\b|\bfilm\b|\bdocumentary\b|\banime\b|\bsci-fi\b'
        r'|\bgames?\b|\bLego\b|\btoys?\b'
        r'|Prime Video|Apple TV|Netflix|Disney|\bHBO\b'
        r"|^\s*'[^']+' at \d+",
        re.IGNORECASE)),
    ('shopping', ['Space.com'], re.compile(
        r'\d+% off'
        r'|\bVPN\b'
        r'|\bdrone\b'
        r'|spotting scope|Dobsonian|binoculars'
        r'|\b(beginner|smart) telescope'
        r'|\bI bought\b'
        r'|eclipse glasses'
        r'|\bbest\b.*\bto buy\b',
        re.IGNORECASE)),
]


def classifyFiller(source, title):
    """Returns the name of the first filler rule the title matches, or
    None if the article is real news and should be kept."""
    if not title:
        return None
    for ruleName, sources, pattern in FILLER_RULES:
        if sources is not None and source not in sources:
            continue
        if pattern.search(title):
            return ruleName
    return None
