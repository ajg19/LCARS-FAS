"""Tests for scripts/enrichEirp.py's class tier and its GCAT fallback
(gcat_class) -- pure functions, no database."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'scripts'))
import enrichEirp as ee  # noqa: E402

GEO, LEO = 1436.0, 95.0


def test_gcat_class_rules_in_order():
    assert ee.gcat_class('SS', 'C', LEO, 20000) == 'station'
    assert ee.gcat_class('IMG', 'B', LEO, 5) == 'cubesat'          # size before mission
    assert ee.gcat_class('TECH', 'A', LEO, 2) == 'amateur'
    assert ee.gcat_class('MET', 'C', GEO, 3000) == 'weather-geo'
    assert ee.gcat_class('MET', 'C', LEO, 1000) == 'weather-leo'
    assert ee.gcat_class('IMG-R', 'B', LEO, 100) == 'eo-radar'
    assert ee.gcat_class('IMG', 'C', LEO, 500) == 'eo-optical'
    assert ee.gcat_class('EOSCI', 'C', LEO, 500) == 'eo-optical'
    assert ee.gcat_class('COM', 'B', GEO, 5000) == 'comms-geo'
    assert ee.gcat_class('COM', 'D', GEO, 5000) == 'military-comms'
    assert ee.gcat_class('COM', 'B', LEO, 300) == 'comms-leo-narrow'
    assert ee.gcat_class('SCI', 'C', LEO, 300) == 'science'
    assert ee.gcat_class('SIG', 'D', LEO, 300) is None
    assert ee.gcat_class(None, None, None, None) is None


def test_unknown_mass_skips_the_size_rule():
    assert ee.gcat_class('IMG', 'B', LEO, None) == 'eo-optical'


def test_fallback_used_only_when_groups_place_nothing():
    # CelesTrak group decides when present...
    band, eirp, source, _ = ee.resolve('SAT', 'PAY', {'weather'}, LEO, 'comms-leo-narrow')
    assert (band, source) == (ee.BAND_CLASS_EIRP['weather-leo']['band'], 'estimated')
    # ...the GCAT class only when the groups give nothing.
    band, eirp, source, _ = ee.resolve('SAT', 'PAY', set(), LEO, 'eo-radar')
    assert (band, eirp, source) == ('X', ee.BAND_CLASS_EIRP['eo-radar']['eirpDbw'], 'estimated')
    assert ee.resolve('SAT', 'PAY', set(), LEO)[2] == 'unknown'


def test_constellation_still_beats_the_fallback():
    band, _, source, _ = ee.resolve('STARLINK-1', 'PAY', {'starlink'}, LEO, 'cubesat')
    assert (band, source) == ('Ku', 'filing')


def test_rocket_bodies_get_no_class():
    assert ee.resolve('R/B', 'R/B', set(), LEO, 'science')[2] == 'none'
