"""Picks a satellite's main downlink and uplink from its SatNOGS
transmitter records -- the rule ingestSatnogsRf.py has always used,
shared with the publish step (publishSite.py), which applies it to the
records in ingestionSatNOGS.db. Pure functions, no database.

Records are dicts with SatNOGS's own field names (downlink_low, baud,
frequency_violation, ...).
"""

# Plausible space-comms downlink / uplink range, Hz -- guards against a
# malformed 0 / negative / obviously-wrong community entry.
FREQ_MIN_HZ, FREQ_MAX_HZ = 2e7, 6e10


def _centre(low, high):
    """Centre frequency of a low/high pair (Hz), or None if unusable. A
    fixed channel has low == high; a transponder has high > low."""
    if not isinstance(low, (int, float)) or isinstance(low, bool) or low <= 0:
        return None
    hi = high if isinstance(high, (int, float)) and not isinstance(high, bool) and high >= low else low
    centre = (low + hi) / 2.0
    if not (FREQ_MIN_HZ <= centre <= FREQ_MAX_HZ):
        return None
    return centre


def _rank(tx):
    """Sort key for picking the 'main' record for a satellite -- higher is
    better: confirmed and non-violating first, then active, then higher
    baud (the primary data link), then more recently updated."""
    clean = not tx.get('frequency_violation') and not tx.get('unconfirmed')
    active = tx.get('status') == 'active' or bool(tx.get('alive'))
    baud = tx.get('baud') or 0
    updated = tx.get('updated') or ''
    return (clean, active, baud, updated)


def choose_rf(transmitters):
    """(dlFreqHz, ulFreqHz, dlBandwidthHz, rfMode, rfBaud) for one
    satellite's list of SatNOGS transmitter records, or None when none of
    them carry a usable downlink."""
    dl_candidates = []
    ul_candidates = []
    for tx in transmitters:
        dl = _centre(tx.get('downlink_low'), tx.get('downlink_high'))
        if dl is not None:
            dl_candidates.append((tx, dl))
        ul = _centre(tx.get('uplink_low'), tx.get('uplink_high'))
        if ul is not None:
            ul_candidates.append((tx, ul))
    if not dl_candidates:
        return None

    tx, dl_hz = max(dl_candidates, key=lambda pair: _rank(pair[0]))
    low, high = tx.get('downlink_low'), tx.get('downlink_high')
    span = (high - low) if isinstance(high, (int, float)) and high > low else None
    mode = tx.get('mode') or None
    baud = tx.get('baud') if isinstance(tx.get('baud'), (int, float)) and not isinstance(tx.get('baud'), bool) else None

    ul_hz = None
    if ul_candidates:
        ul_hz = max(ul_candidates, key=lambda pair: _rank(pair[0]))[1]

    return dl_hz, ul_hz, span, mode, baud
