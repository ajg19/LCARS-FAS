"""Tests for scripts/estimateBrightness.py -- GRD VIEW's standard
magnitudes: stations, Starlink generations, size from GCAT, defaults.
Pure functions, plus brightnessRows against small temporary databases."""

import os
import sqlite3
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'scripts'))
import estimateBrightness as eb  # noqa: E402


# --- Starlink generations ------------------------------------------------------------

@pytest.mark.parametrize('bus, launch, expected', [
    ('Starlink V2M', '2024-01-01', (7.22, 'V2 Mini')),
    ('Starlink V2MD', '2025-01-01', (7.22, 'V2 Mini DTC')),
    ('Starlink V2MO', '2025-06-01', (7.22, 'V2 Mini Optimised')),
    ('Starlink', '2020-01-15', (5.89, 'v1.0')),
    ('Starlink', '2021-01-15', (7.21, 'VisorSat')),
    ('Starlink', '2022-01-15', (6.34, 'v1.5')),
    (None, '2020-10-01', (7.21, 'VisorSat')),            # GCAT has no bus for a few VisorSats
    (None, '2025-03-01', (7.22, 'V2 Mini (assumed)')),   # newest, not in GCAT yet
])
def test_starlink_classes(bus, launch, expected):
    assert eb.starlinkMagnitude(bus, launch) == expected


def test_unclassifiable_starlink_gives_none():
    assert eb.starlinkMagnitude(None, '2022-01-01') is None      # no bus, between the dated rules
    assert eb.starlinkMagnitude('Unknown bus', '2024-01-01') is None
    assert eb.starlinkMagnitude('Starlink', None) is None


def test_class_boundaries_are_start_inclusive():
    assert eb.starlinkMagnitude('Starlink', '2020-08-01')[1] == 'VisorSat'
    assert eb.starlinkMagnitude('Starlink', '2021-09-01')[1] == 'v1.5'


# --- Size --------------------------------------------------------------------------

def test_size_magnitude_of_a_one_metre_body():
    # Lambertian, albedo 0.25, half lit, at 1,000 km: worked by hand.
    assert eb.sizeMagnitude(1.0, 1.0, None) == pytest.approx(7.69, abs=0.01)


def test_no_size_gives_none():
    assert eb.sizeMagnitude(None, None, None) is None
    assert eb.sizeMagnitude(0, 0, 0) is None


def test_bigger_is_brighter_and_panels_count_half():
    small, large = eb.sizeMagnitude(1, 1, None), eb.sizeMagnitude(4, 2, None)
    assert large < small
    with_panels = eb.sizeMagnitude(2, 1, 10)
    assert with_panels < eb.sizeMagnitude(2, 1, None)


def test_span_is_capped_at_max_span_ratio():
    # GCAT's span can include wire antennas; beyond MAX_SPAN_RATIO x body it adds nothing.
    capped = eb.sizeMagnitude(2, 1, 2 * eb.MAX_SPAN_RATIO)
    assert eb.sizeMagnitude(2, 1, 500) == capped


# --- brightnessRows ----------------------------------------------------------------

def test_brightness_rows_rules(tmp_path):
    orbital = tmp_path / 'orbital.db'
    o = sqlite3.connect(str(orbital))
    o.execute('CREATE TABLE orbital_objects (noradID INTEGER, objectType TEXT, name TEXT, launchDate TEXT, decayDate TEXT)')
    o.executemany('INSERT INTO orbital_objects VALUES (?, ?, ?, ?, ?)', [
        (25544, 'PAY', 'ISS (ZARYA)', '1998-11-20', None),     # station override
        (44713, 'PAY', 'STARLINK-1007', '2019-11-11', None),   # Starlink v1.0 via GCAT bus
        (100, 'PAY', 'SIZED SAT', '2015-01-01', None),         # size from GCAT
        (101, 'R/B', 'SOME R/B', '2015-01-01', None),          # no size: R/B default
        (102, 'PAY', 'NOT IN GCAT', '2015-01-01', None),       # no size: payload default
        (103, 'DEB', 'DEBRIS', '2015-01-01', None),            # debris: no row
        (104, 'PAY', 'DECAYED', '2015-01-01', '2026-01-01'),   # decayed: no row
    ])
    o.commit()
    o.close()
    g = sqlite3.connect('file::memory:', uri=True)   # uri, as both real callers open it: ATTACH takes a URI
    g.execute('CREATE TABLE gcatObjects (noradID INTEGER, name TEXT, bus TEXT, launchDate TEXT, '
              'lengthM REAL, diameterM REAL, spanM REAL)')
    g.executemany('INSERT INTO gcatObjects VALUES (?, ?, ?, ?, ?, ?, ?)', [
        (44713, 'Starlink-1007', 'Starlink', '2019-11-11', None, None, None),
        (100, 'Sized Sat', 'Some bus', '2015-01-01', 1.0, 1.0, None),
        (101, 'Some R/B', None, '2015-01-01', None, None, None),
    ])
    g.commit()   # no open transaction: brightnessRows ATTACHes and DETACHes
    rows = {norad: (mag, source) for norad, mag, source in eb.brightnessRows(g, str(orbital))}
    assert rows[25544] == (-1.3, 'station')
    assert rows[44713] == (5.89, 'starlink v1.0')
    assert rows[100][0] == pytest.approx(7.69, abs=0.01) and rows[100][1] == 'size'
    assert rows[101] == (6.0, 'default')
    assert rows[102] == (7.0, 'default')
    assert 103 not in rows and 104 not in rows
