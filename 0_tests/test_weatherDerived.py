"""Tests for scripts/weatherDerived.py -- the derived quantities of Spock's review
(enterpriseCrewOutput/spock_dbDataQuestions_2026-10-24.md). Pure functions; no database."""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'scripts'))
import weatherDerived as wd  # noqa: E402


# --- Newell function (item 3) -----------------------------------------------------------------------

def test_newell_example_from_the_review():
    # v = 400 km/s, B_T = 5 nT, field due south: 8.6e3
    assert wd.newellRate(400, 0, -5) == pytest.approx(8.6e3, rel=0.01)


def test_newell_is_zero_for_a_northward_field_and_uses_by_and_bz_not_bx():
    assert wd.newellRate(400, 0, 5) == pytest.approx(0, abs=1e-6)
    east = wd.newellRate(400, 5, 0)                       # clock angle 90 degrees: sin(45 deg)^(8/3) = 0.397 of due south
    assert east == pytest.approx(wd.newellRate(400, 0, -5) * (0.5 ** 0.5) ** (8 / 3), rel=1e-9)
    assert wd.newellRate(400, 3, -4) == wd.newellRate(400, -3, -4)   # symmetric in By


def test_newell_needs_all_three_inputs():
    assert wd.newellRate(None, 1, 1) is None and wd.newellRate(400, None, 1) is None and wd.newellRate(400, 1, None) is None


def minute(i, hour=5):
    return f'2026-10-24T{hour:02d}:{i:02d}:00Z'


def test_hourly_newell_needs_30_minutes_with_field_and_plasma_and_never_interpolates():
    rows = [(minute(i), 400.0, 0.0, -5.0) for i in range(60)]
    rows[10:40] = [(minute(i), None, 0.0, -5.0) for i in range(10, 40)]            # 30 minutes without plasma: 30 left
    minutes, hourly = wd.newellSeries(rows)
    assert len(minutes) == 30 and len(hourly) == 1 and hourly[0][2] == 30
    rows[40] = (minute(40), None, 0.0, -5.0)                                        # now 29
    assert wd.newellSeries(rows)[1] == []


# --- G levels and the storm list (items 4 and 11) ---------------------------------------------------------

@pytest.mark.parametrize('kp, level', [(4.33, 0), (4.667, 1), (5.0, 1), (5.333, 1), (5.667, 2), (6.333, 2), (6.667, 3),
                                       (7.333, 3), (7.667, 4), (8.667, 4), (9.0, 5), (None, 0)])
def test_g_levels_include_thirds(kp, level):
    assert wd.gLevel(kp) == level


def block(day, hour):
    return f'2026-10-{day:02d}T{hour:02d}:00:00Z'


def test_a_storm_is_a_run_of_blocks_at_or_above_467_with_the_highest_g_in_it():
    kp = [(block(10, 12), 3.0, 'def'), (block(10, 15), 7.333, 'pre'), (block(10, 18), 7.0, 'def'), (block(10, 21), 5.667, 'def'),
          (block(11, 0), 4.0, 'def'), (block(11, 3), 4.667, 'def'), (block(11, 6), 4.333, 'def'),
          (block(11, 15), 5.0, 'def')]                                           # a later single block, after a gap
    storms = wd.stormRuns(kp)
    assert [(s['startUtc'], s['endUtc'], s['level'], s['blocks']) for s in storms] == [
        (block(10, 15), block(11, 0), 3, 3), (block(11, 3), block(11, 6), 1, 1), (block(11, 15), block(11, 18), 1, 1)]
    assert storms[0]['maxKp'] == 7.333 and storms[0]['preliminary'] is True and storms[1]['preliminary'] is False


def test_blocks_that_are_not_consecutive_are_not_one_storm():
    kp = [(block(10, 15), 5.0, 'def'), (block(10, 21), 5.0, 'def')]
    assert len(wd.stormRuns(kp)) == 2


def test_donki_storms_give_links_only_when_they_match_within_one_block():
    kp = [(block(10, 15), 7.333, 'def'), (block(10, 18), 7.0, 'def')]
    gst = [{'gstID': 'G1', 'allKpIndex': [{'kpIndex': 7.0, 'observedTime': '2026-10-10T18:00Z', 'source': 'NOAA'}],
            'linkedEvents': [{'activityID': '2026-10-10T14:33:00-IPS-001'}, {'activityID': '2026-10-10T15:33:00-MPC-001'},
                             {'activityID': '2026-10-09T11:00:00-CME-001'}]},
           {'gstID': 'FAR', 'allKpIndex': [{'kpIndex': 5.67, 'observedTime': '2026-10-04T18:00Z'}],
            'linkedEvents': [{'activityID': 'x-CME-001'}]}]
    storm = wd.stormRuns(kp, gst)[0]
    # DONKI's observedTime is the END of a block (18:00 = the 15:00 block); GFZ stamps the start
    assert storm['gst'] == ['G1'] and storm['links'] == ['2026-10-10T14:33:00-IPS-001', '2026-10-09T11:00:00-CME-001']


# --- Energetic protons (item 10) --------------------------------------------------------------------------

def five(i):
    total = 12 * 60 + 5 * i
    return f'2026-10-20T{total // 60:02d}:{total % 60:02d}:00Z'


def test_s_events_start_at_three_consecutive_values_at_or_above_10_pfu_and_end_at_the_last_such_value():
    flux = [0.2, 12, 11, 0.3, 15, 40, 90, 55, 12, 9.9, 30, 31, 0.2]
    events = wd.sEvents([(five(i), f) for i, f in enumerate(flux)])
    assert events == [{'startUtc': five(4), 'endUtc': five(8), 'peakPfu': 90, 'peakUtc': five(6)}]    # 12, 11 is only two values


def test_a_gap_in_the_data_breaks_a_run_and_nulls_are_below_threshold():
    rows = [(five(0), 20), (five(1), 20), (five(3), 20), (five(4), 20), (five(5), None), (five(6), 20)]
    assert wd.sEvents(rows) == []


# --- DONKI SEP records (item 10) --------------------------------------------------------------------------

def sep(time, instruments, links=()):
    return {'eventTime': time, 'instruments': [{'displayName': n} for n in instruments],
            'linkedEvents': [{'activityID': a} for a in links]}


def test_sep_records_become_one_marker_per_event_and_stereo_is_left_out():
    records = [sep('2026-07-30T18:20Z', ['GOES-P: SEISS >10 MeV'], ['2026-07-30T15:53:00-FLR-001']),
               sep('2026-07-30T18:20Z', ['SOHO: COSTEP 15.8-39.8 MeV'], ['2026-07-30T15:53:00-FLR-001', '2026-07-30T16:53:00-CME-001']),
               sep('2026-07-30T18:20Z', ['MODEL: REleASE:ACE/EPAM 15.8-39.8 MeV'], ['2026-07-30T15:53:00-FLR-001']),
               sep('2026-08-20T10:00Z', ['STEREO A: IMPACT 13-100 MeV']),
               sep('2026-09-01T10:00Z', ['MODEL: REleASE:SOHO/EPHIN 15.8-39.8 MeV'], ['2026-09-01T09:00:00-FLR-001'])]
    groups = wd.sepGroups(records)
    assert [(g['startUtc'], g['status']) for g in groups] == [('2026-07-30T18:20:00Z', 'observed'), ('2026-09-01T10:00:00Z', 'forecast')]
    assert groups[0]['observed'] == ['GOES-P: SEISS >10 MeV', 'SOHO: COSTEP 15.8-39.8 MeV']
    assert groups[0]['links'] == ['2026-07-30T15:53:00-FLR-001', '2026-07-30T16:53:00-CME-001']


# --- CMEs (item 12) ---------------------------------------------------------------------------------------

def cme(speed, enlil=None, extra=()):
    analyses = [{'featureCode': 'LE', 'isMostAccurate': True, 'speed': speed, 'type': 'S', 'halfAngle': 20.0, 'latitude': 1, 'longitude': 2,
                 'enlilList': enlil}] + list(extra)
    return {'activityID': 'c', 'startTime': '2026-10-20T01:00Z', 'cmeAnalyses': analyses}


def test_a_cme_is_shown_when_enlil_predicts_an_arrival_or_the_leading_edge_is_fast():
    assert not wd.cmeShown(cme(500))
    assert wd.cmeShown(cme(1000)) and wd.cmeShown(cme(1862))
    assert wd.cmeShown(cme(300, [{'estimatedShockArrivalTime': '2026-10-23T00:00Z'}]))
    assert wd.cmeShown(cme(300, [{'estimatedShockArrivalTime': None, 'isEarthGB': True}]))
    assert wd.cmeShown(cme(300, [{'estimatedShockArrivalTime': None, 'isEarthMinorImpact': True}]))
    assert not wd.cmeShown(cme(300, [{'estimatedShockArrivalTime': None, 'isEarthGB': False, 'isEarthMinorImpact': False}]))


def test_the_shock_analysis_does_not_make_a_slow_cme_fast_and_le_is_the_one_summarised():
    shock = {'featureCode': 'SH', 'isMostAccurate': False, 'speed': 1500.0, 'type': 'O'}
    record = cme(400, None, [shock])
    assert not wd.cmeShown(record)
    summary = wd.cmeSummary(record)
    assert summary['speed'] == 400 and summary['type'] == 'S' and summary['halfAngle'] == 20.0 and summary['predictedArrival'] is None
    assert wd.cmeSummary(cme(300, [{'estimatedShockArrivalTime': '2026-10-23T00:00Z'}]))['predictedArrival'] == '2026-10-23T00:00Z'


# --- Streams and shocks (item 13) ----------------------------------------------------------------------------

def test_streams_seen_at_l1_are_kept_and_stereo_a_streams_give_a_22_day_recurrence_hint():
    hss = [{'hssID': 'a', 'eventTime': '2026-08-07T04:00Z', 'instruments': [{'displayName': 'SOLAR-1: MAG'}, {'displayName': 'STEREO A: PLASTIC'}]},
           {'hssID': 'b', 'eventTime': '2026-10-10T12:00Z', 'instruments': [{'displayName': 'STEREO A: IMPACT'}]},
           {'hssID': 'c', 'eventTime': '2026-10-12T00:00Z', 'instruments': [{'displayName': 'ACE: SWEPAM'}]}]
    ips = [{'activityID': 'x', 'location': 'Earth'}, {'activityID': 'y', 'location': 'STEREO A'}]
    streams, shocks, recurrence = wd.earthStreams(hss, ips)
    assert [r['hssID'] for r in streams] == ['a', 'c'] and [r['activityID'] for r in shocks] == ['x']
    assert recurrence == [{'hssID': 'b', 'seenUtc': '2026-10-10T12:00:00Z', 'expectedUtc': '2026-11-01T12:00:00Z', 'plusMinusDays': 3}]


# --- F10.7 bursts, the cleaned series and the centred 81-day mean (second review) -----------------------------------

def run(start, values):
    """{day: value} for consecutive days from `start` (YYYY-MM-DD)."""
    return {wd.shiftDay(start, i): v for i, v in enumerate(values)}


def test_the_three_known_burst_days_are_flagged_and_the_next_largest_excess_is_not():
    obs = {**run('2026-06-30', [202.6, 249.7, 202.9]), **run('2026-01-17', [159.2, 231.8, 173.4]),
           **run('2026-09-01', [100.5, 139.0, 108.2]), **run('2025-11-03', [100.0, 113.5, 100.0])}    # 4 Nov: +13.5%, not flagged
    assert wd.f107Bursts(obs) == {'2026-07-01': 'neighbours', '2026-01-18': 'neighbours', '2026-09-02': 'neighbours'}


def test_a_day_without_both_neighbours_is_not_flagged_by_the_neighbour_rule_and_a_missing_value_is_skipped():
    assert wd.f107Bursts({'2026-01-01': 100.0, '2026-01-02': 300.0}) == {}
    assert wd.f107Bursts(run('2026-01-01', [100.0, None, 300.0, 100.0])) == {}


def test_swpcs_three_readings_flag_a_noon_burst_on_the_same_day():
    flagged = wd.f107Bursts({}, {'2026-07-01': (200.0, 249.7, 203.0), '2026-10-13': (124.0, 136.0, 207.0), '2026-10-14': (124.0, 123.0, 121.0),
                                  '2026-10-15': (None, 300.0, 100.0)})
    assert flagged == {'2026-07-01': 'same day'}           # on 13 Oct the afternoon is the burst, not the daily (Noon) value


def test_the_cleaned_series_uses_the_median_of_three_readings_else_the_neighbour_mean():
    obs = run('2026-06-30', [202.6, 249.7, 202.9])
    flagged = wd.f107Bursts(obs)
    clean = wd.f107Clean(obs, flagged)
    assert clean['2026-07-01'] == (pytest.approx(202.75), 'cleaned: mean of the neighbours')
    assert clean['2026-06-30'] == (202.6, 'observed')
    withReadings = wd.f107Clean(obs, flagged, {'2026-07-01': (200.0, 249.7, 203.0)})
    assert withReadings['2026-07-01'] == (203.0, 'cleaned: median of the three readings')
    assert wd.f107Clean({'2026-01-01': None, '2026-01-02': 100.0}, {}) == {'2026-01-02': (100.0, 'observed')}


def flat(first, days, value=100.0):
    return {wd.shiftDay(first, i): value for i in range(days)}


def test_the_centred_mean_has_no_partial_windows():
    clean = flat('2026-01-01', 200)
    mean = wd.f107Centred(clean)
    days = sorted(mean)
    assert days[0] == '2026-02-10' and days[-1] == wd.shiftDay('2026-01-01', 199 - 40)      # first+40 .. last-40: 120 days
    assert len(mean) == 200 - 80 and all(v == (100.0, 'observed') for v in mean.values())


def test_the_centred_mean_tolerates_a_few_gaps_but_not_many():
    clean = flat('2026-01-01', 200)
    for i in range(5):
        del clean[wd.shiftDay('2026-03-01', i)]
    assert '2026-03-02' in wd.f107Centred(clean)                       # 76 of 81 days present (needs 75)
    for i in range(5, 8):
        del clean[wd.shiftDay('2026-03-01', i)]
    assert '2026-03-02' not in wd.f107Centred(clean)                   # 73 of 81: no value at all, never a partial mean


def test_the_newest_40_days_come_from_the_forecast_and_say_so():
    clean = flat('2026-01-01', 200, 100.0)                             # last observed day 2026-07-19
    forecast = flat('2026-07-20', 45, 130.0)
    mean = wd.f107Centred(clean, forecast)
    last = wd.shiftDay('2026-01-01', 199)
    assert mean[wd.shiftDay(last, -40)] == (100.0, 'observed') and mean[wd.shiftDay(last, -39)][1] == 'forecast'
    assert mean[last][0] == pytest.approx((41 * 100.0 + 40 * 130.0) / 81)
    assert max(mean) == wd.shiftDay(wd.shiftDay(last, 45), -40)        # the forecast reaches 45 days, so the curve runs 5 days past the data
    # the forecast never replaces an observed day
    assert wd.f107Centred(clean, flat('2026-01-01', 45, 999.0)).get('2026-02-10') == (100.0, 'observed')


# --- Flares (item 9) ------------------------------------------------------------------------------------------

def xra(observatory, cls, flux, peak):
    return {'observatory': observatory, 'particulars1': cls, 'particulars10': flux, 'max_datetime': peak}


def test_the_daily_maximum_uses_the_primary_satellite_only_and_the_peak_date():
    records = [xra('G18', 'C1.0', '1.0E-06', '2026-10-24T06:44:00'), xra('G19', 'B9.9', '9.9E-07', '2026-10-24T06:44:00'),
               xra('G18', 'M1.7', '1.7E-05', '2026-10-24T23:50:00'), xra('G18', 'C3.3', '3.3E-06', '2026-10-23T05:42:00'),
               xra('G18', 'B2.0', '2.0E-07', '2026-10-23T09:00:00'), xra('G19', 'X1.0', '1.0E-04', '2026-10-23T12:00:00'),
               xra('G18', 'C1.0', None, '2026-10-22T01:00:00')]
    best = wd.dailyFlareMax(records, 'G18')
    assert best == {'2026-10-24': (1.7e-05, 'M1.7', '2026-10-24T23:50:00Z'), '2026-10-23': (3.3e-06, 'C3.3', '2026-10-23T05:42:00Z')}
