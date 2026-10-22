"""Tests for scripts/rfSelection.py -- picking each satellite's main
downlink and uplink from its SatNOGS transmitter records (the link
budget's real frequencies). Pure functions; records in SatNOGS's own
field names."""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'scripts'))
from rfSelection import _centre, choose_rf  # noqa: E402


def tx(low=437.1e6, high=None, ul_low=None, ul_high=None, **extra):
    record = {'downlink_low': low, 'downlink_high': low if high is None else high,
              'uplink_low': ul_low, 'uplink_high': ul_high, 'mode': 'GMSK', 'baud': 9600,
              'status': 'active', 'alive': True, 'frequency_violation': False, 'unconfirmed': False,
              'updated': '2026-01-01T00:00:00Z'}
    record.update(extra)
    return record


# --- _centre -----------------------------------------------------------------------

def test_fixed_channel_and_transponder_centres():
    assert _centre(437.1e6, 437.1e6) == 437.1e6
    assert _centre(145.8e6, 146.0e6) == pytest.approx(145.9e6)


def test_high_below_low_or_missing_uses_low():
    assert _centre(437e6, 436e6) == 437e6
    assert _centre(437e6, None) == 437e6


@pytest.mark.parametrize('low', [None, 0, -5, True, '437e6'])
def test_unusable_low_is_rejected(low):
    assert _centre(low, 437e6) is None


def test_implausible_frequencies_are_rejected():
    assert _centre(10e6, 10e6) is None      # below 20 MHz
    assert _centre(100e9, 100e9) is None    # above 60 GHz
    assert _centre(20e6, 20e6) == 20e6      # range is inclusive


# --- choose_rf ---------------------------------------------------------------------

def test_no_usable_downlink_gives_none():
    assert choose_rf([]) is None
    assert choose_rf([tx(low=None), tx(low=5e6)]) is None


def test_single_fixed_channel():
    dl, ul, span, mode, baud = choose_rf([tx()])
    assert (dl, ul, span, mode, baud) == (437.1e6, None, None, 'GMSK', 9600)


def test_transponder_gives_span_and_uplink():
    dl, ul, span, _, _ = choose_rf([tx(low=435.8e6, high=435.84e6, ul_low=145.9e6, ul_high=145.94e6)])
    assert dl == pytest.approx(435.82e6)
    assert span == pytest.approx(40e3)
    assert ul == pytest.approx(145.92e6)


def test_confirmed_record_beats_a_violating_or_unconfirmed_one():
    chosen = choose_rf([tx(low=400e6, frequency_violation=True, baud=99999),
                        tx(low=401e6, unconfirmed=True, baud=99999),
                        tx(low=437e6, baud=1200)])
    assert chosen[0] == 437e6


def test_active_beats_inactive_then_higher_baud_then_newer():
    assert choose_rf([tx(low=400e6, status='inactive', alive=False, baud=9600),
                      tx(low=437e6, baud=1200)])[0] == 437e6
    assert choose_rf([tx(low=400e6, baud=1200), tx(low=437e6, baud=9600)])[0] == 437e6
    assert choose_rf([tx(low=400e6, updated='2025-01-01'), tx(low=437e6, updated='2026-06-01')])[0] == 437e6


def test_uplink_is_chosen_independently_of_the_downlink():
    # The best downlink has no uplink; the uplink comes from another record.
    chosen = choose_rf([tx(low=437e6, baud=9600), tx(low=145e6, baud=1200, ul_low=145.9e6, ul_high=145.9e6)])
    assert chosen[0] == 437e6 and chosen[1] == 145.9e6


def test_missing_mode_and_boolean_baud_become_none():
    dl, _, _, mode, baud = choose_rf([tx(mode='', baud=True)])
    assert dl == 437.1e6 and mode is None and baud is None
