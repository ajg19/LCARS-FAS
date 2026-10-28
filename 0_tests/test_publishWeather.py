"""Tests for the weather publish (scripts/publishSite.py, kind 'weather'):
siteWeather.db built from temporary ingestion databases -- native and hourly
series, events, maps, derived series, run history, and the refusals."""

import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'scripts'))
import dbPaths  # noqa: E402
import publishSite as ps  # noqa: E402
import spaceWeatherSamples as sws  # noqa: E402

NOW = datetime(2026, 10, 24, 12, tzinfo=timezone.utc)


@pytest.fixture
def dbDir(tmp_path, monkeypatch):
    monkeypatch.setattr(dbPaths, 'DB_DIR', str(tmp_path))
    monkeypatch.setattr(dbPaths, 'LEGACY', False)
    return tmp_path


def stamp(days, minutes=0):
    return (NOW - timedelta(days=days, minutes=-minutes)).strftime('%Y-%m-%dT%H:%M:00Z')


def makeSwpc(extra=()):
    db = sws.connect(dbPaths.dbPath(dbPaths.SWPC_DB))
    rows = [('l1MagBt', stamp(10, i), 5.0, 'nT', 'SOLAR1') for i in range(120)]     # old: hourly only
    rows += [('l1MagBt', stamp(1, i), 6.0 + i % 2, 'nT', 'SOLAR1') for i in range(120)]  # recent: native
    rows += [('swpcKp', stamp(5), 3.0, 'Kp', 'observed'), ('swpcDst', stamp(20), -30.0, 'nT', None)]
    rows += list(extra)
    sws.upsertSamples(db, rows)
    sws.upsertEvents(db, [('flare', stamp(2), 'f1', {'class': 'M1'})])
    sws.upsertMap(db, 'testMap', stamp(0), {'grid': [1, 2]})
    db.execute("CREATE TABLE ingestionRuns (job TEXT, startedAt TEXT, finishedAt TEXT, succeeded INTEGER, changes INTEGER, note TEXT)")
    db.execute("INSERT INTO ingestionRuns VALUES ('swpcFast', ?, ?, 1, 5, '')", (stamp(0), stamp(0)))
    db.commit()
    db.close()


def siteDb():
    return sqlite3.connect(dbPaths.dbPath(dbPaths.SITE_WEATHER_DB))


def test_publish_builds_native_and_hourly_series(dbDir):
    makeSwpc()
    counts = ps.publish('weather', NOW)
    assert counts['samples'] > 0
    db = siteDb()
    # 10-day-old minutes are not native, but their hours are in samplesHourly
    assert db.execute("SELECT COUNT(*) FROM samples WHERE series = 'l1MagBt' AND tsUtc < ?", (stamp(3),)).fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM samples WHERE series = 'l1MagBt'").fetchone()[0] == 120
    hours = db.execute("SELECT tsUtc, value, readings FROM samplesHourly WHERE series = 'l1MagBt' ORDER BY tsUtc").fetchall()
    assert len(hours) >= 4 and sum(h[2] for h in hours) == 240
    # slow series are copied whole
    assert db.execute("SELECT value FROM samples WHERE series = 'swpcDst'").fetchone()[0] == -30.0
    assert db.execute("SELECT COUNT(*) FROM samplesHourly WHERE series = 'swpcKp'").fetchone()[0] == 0


def test_events_maps_and_runs_come_across(dbDir):
    makeSwpc()
    ps.publish('weather', NOW)
    db = siteDb()
    assert db.execute('SELECT eventType, eventID FROM events').fetchall() == [('flare', 'f1')]
    assert db.execute("SELECT json FROM latestMaps WHERE name = 'testMap'").fetchone()[0] == '{"grid":[1,2]}'
    runs = db.execute('SELECT sourceDb, job FROM ingestionRuns ORDER BY finishedAt').fetchall()
    assert ('ingestionSWPC', 'swpcFast') in runs and ('publishSite', 'publishWeather') in runs


def test_gfz_and_donki_are_used_when_present(dbDir):
    makeSwpc()
    gfz = sws.connect(dbPaths.dbPath(dbPaths.GFZ_DB))
    sws.upsertSamples(gfz, [('gfzKp', stamp(1), 6.0, 'Kp', 'def'), ('gfzKp', stamp(1, 180), 4.0, 'Kp', 'def')])
    gfz.close()
    donki = sws.connect(dbPaths.dbPath(dbPaths.DONKI_DB))
    sws.upsertEvents(donki, [('CME', stamp(3), 'c1', {'a': 1})])
    donki.close()
    ps.publish('weather', NOW)
    db = siteDb()
    assert db.execute("SELECT COUNT(*) FROM samples WHERE series = 'gfzKp'").fetchone()[0] == 2
    assert db.execute("SELECT COUNT(*) FROM events WHERE eventType = 'CME'").fetchone()[0] == 1


def test_derived_storm_scale(dbDir):
    assert [ps.stormScale(k) for k in (3.0, 4.67, 5.0, 6.33, 8.0, 9.0)] == [0, 1, 1, 2, 4, 5]
    makeSwpc()
    gfz = sws.connect(dbPaths.dbPath(dbPaths.GFZ_DB))
    sws.upsertSamples(gfz, [('gfzKp', stamp(1), 7.0, 'Kp', 'def')])
    gfz.close()
    ps.publish('weather', NOW)
    assert siteDb().execute("SELECT value FROM samples WHERE series = 'derivedStormG'").fetchone()[0] == 3.0


def day(n):
    return (NOW - timedelta(days=n)).strftime('%Y-%m-%dT00:00:00Z')


def test_f107_bursts_are_flagged_cleaned_and_the_centred_mean_is_a_full_window_of_cleaned_observed_flux(dbDir):
    makeSwpc()
    gfz = sws.connect(dbPaths.dbPath(dbPaths.GFZ_DB))
    values = {n: 100.0 for n in range(150, -1, -1)}
    values[60] = 160.0                                          # a burst day: 60% above its neighbours
    sws.upsertSamples(gfz, [('gfzF107Obs', day(n), v, 'sfu', None) for n, v in values.items()]
                      + [('gfzF107Adj', day(n), v - 1, 'sfu', None) for n, v in values.items()])
    gfz.close()
    ps.publish('weather', NOW)
    db = siteDb()
    flagged = db.execute("SELECT series, tsUtc, value FROM samples WHERE quality = 'burst?' ORDER BY series").fetchall()
    assert flagged == [('gfzF107Adj', day(60), 159.0), ('gfzF107Obs', day(60), 160.0)]          # flagged, value untouched
    clean = dict((t, (v, q)) for t, v, q in db.execute("SELECT tsUtc, value, quality FROM samples WHERE series = 'derivedF107ObsClean'"))
    assert clean[day(60)] == (100.0, 'cleaned: mean of the neighbours') and clean[day(61)] == (100.0, 'observed') and len(clean) == 151
    mean = db.execute("SELECT tsUtc, value, quality FROM samples WHERE series = 'derivedF107A81' ORDER BY tsUtc").fetchall()
    # observed record: 151 days; a full window needs 40 days each side: the first and last 40 are absent, no partial windows
    assert len(mean) == 151 - 80 and mean[0][0] == day(110) and mean[-1][0] == day(40)
    assert all(v == pytest.approx(100.0) for _, v, _ in mean)                              # the burst never reaches the mean
    assert {q for _, _, q in mean} == {'centred 81-day mean of the cleaned observed flux'}


def test_the_newest_days_of_the_centred_mean_use_the_45_day_forecast_and_say_so(dbDir):
    forecast = [('swpcForecastF107', day(-n), 130.0, 'sfu', 'issued') for n in range(1, 46)]
    makeSwpc(extra=forecast)
    gfz = sws.connect(dbPaths.dbPath(dbPaths.GFZ_DB))
    sws.upsertSamples(gfz, [('gfzF107Obs', day(n), 100.0, 'sfu', None) for n in range(150, -1, -1)])
    gfz.close()
    ps.publish('weather', NOW)
    mean = dict((t, (v, q)) for t, v, q in siteDb().execute("SELECT tsUtc, value, quality FROM samples WHERE series = 'derivedF107A81'"))
    assert mean[day(40)] == (pytest.approx(100.0), 'centred 81-day mean of the cleaned observed flux')
    value, quality = mean[day(0)]
    assert quality == 'centred 81-day mean, includes the SWPC 45-day forecast' and value == pytest.approx((41 * 100.0 + 40 * 130.0) / 81)
    assert max(mean) == day(-5)                                                             # 45 days of forecast: five days past the data


def test_no_swpc_database_is_refused(dbDir):
    with pytest.raises(ps.PublishRefused, match='not found'):
        ps.publish('weather', NOW)
    assert not os.path.exists(dbPaths.dbPath(dbPaths.SITE_WEATHER_DB))


def test_an_empty_ingestion_database_is_refused(dbDir):
    sws.connect(dbPaths.dbPath(dbPaths.SWPC_DB)).close()
    with pytest.raises(ps.PublishRefused, match='empty table'):
        ps.publish('weather', NOW)


def test_second_publish_keeps_prev_and_a_big_drop_is_refused(dbDir):
    makeSwpc()
    ps.publish('weather', NOW)
    ps.publish('weather', NOW)
    assert os.path.exists(dbPaths.dbPath('siteWeather.db.prev'))
    db = sqlite3.connect(dbPaths.dbPath(dbPaths.SWPC_DB))
    db.execute("DELETE FROM samples WHERE series = 'l1MagBt'")
    db.commit()
    db.close()
    with pytest.raises(ps.PublishRefused, match='would drop'):
        ps.publish('weather', NOW)


# --- Spock's derived series and events (enterpriseCrewOutput/spock_dbDataQuestions_2026-10-24.md) ---------

def hourStamps(hours, minutes):
    base = NOW - timedelta(hours=hours)
    return [(base + timedelta(minutes=i)).strftime('%Y-%m-%dT%H:%M:00Z') for i in range(minutes)]


def test_newell_series_hourly_needs_30_minutes_and_native_covers_only_the_recent_days(dbDir):
    rows = []
    full = hourStamps(5, 60)                       # 60 minutes
    short = hourStamps(3, 29)                      # 29 minutes: no hourly mean
    for ts in full + short:
        rows += [('l1WindSpeed', ts, 400.0, 'km/s', 'SOLAR1'), ('l1MagByGSM', ts, 0.0, 'nT', 'SOLAR1'), ('l1MagBzGSM', ts, -5.0, 'nT', 'SOLAR1')]
    makeSwpc(extra=rows)
    ps.publish('weather', NOW)
    db = siteDb()
    assert db.execute("SELECT COUNT(*) FROM samples WHERE series = 'derivedNewell'").fetchone()[0] == 89
    assert db.execute("SELECT value FROM samples WHERE series = 'derivedNewell' LIMIT 1").fetchone()[0] == pytest.approx(8.6e3, rel=0.01)
    hourly = db.execute("SELECT tsUtc, readings FROM samplesHourly WHERE series = 'derivedNewell'").fetchall()
    assert hourly and all(n >= 30 for _, n in hourly) and sum(n for _, n in hourly) <= 60


def test_hourly_means_need_half_an_hour_of_readings_and_protons_need_six(dbDir):
    thin = hourStamps(30, 20)                       # 20 minutes of a 1-minute series: not enough
    protons = hourStamps(30, 25)[::5][:5]           # 5 five-minute readings in an hour: not enough (6 needed)
    makeSwpc(extra=[('l1MagBt', ts, 5.0, 'nT', 'SOLAR1') for ts in thin] + [('goesProtonGE10MeV', ts, 0.2, 'pfu', 'GOES-18') for ts in protons])
    ps.publish('weather', NOW)
    db = siteDb()
    assert db.execute("SELECT COUNT(*) FROM samplesHourly WHERE series = 'l1MagBt' AND readings < 30").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM samplesHourly WHERE series = 'goesProtonGE10MeV'").fetchone()[0] == 0


def test_only_the_latest_one_minute_kp_is_published(dbDir):
    makeSwpc(extra=[('swpcKp1m', ts, 1.0 + i % 3 / 3, 'Kp', None) for i, ts in enumerate(hourStamps(2, 90))])
    ps.publish('weather', NOW)
    db = siteDb()
    assert db.execute("SELECT COUNT(*) FROM samples WHERE series = 'swpcKp1m'").fetchone()[0] == 1
    assert db.execute("SELECT COUNT(*) FROM samplesHourly WHERE series = 'swpcKp1m'").fetchone()[0] == 0
    assert db.execute("SELECT tsUtc FROM samples WHERE series = 'swpcKp1m'").fetchone()[0] == hourStamps(2, 90)[-1]


def test_storms_s_events_flares_and_donki_groups_are_derived(dbDir):
    stamps = hourStamps(2, 40)[::5]                  # eight 5-minute readings
    protons = [('goesProtonGE10MeV', ts, 30.0 if 1 <= i <= 5 else 0.2, 'pfu', 'GOES-18') for i, ts in enumerate(stamps)]
    makeSwpc(extra=protons + [('goesXrayLong', stamps[0], 1e-6, 'W/m2', 'GOES-18')])
    swpc = sws.connect(dbPaths.dbPath(dbPaths.SWPC_DB))
    sws.upsertEvents(swpc, [('XRA', stamp(1), 'x1', {'observatory': 'G18', 'particulars1': 'M1.7', 'particulars10': '1.7E-05',
                                                      'max_datetime': stamp(1)[:19]}),
                            ('XRA', stamp(1), 'x2', {'observatory': 'G19', 'particulars1': 'X1.0', 'particulars10': '1.0E-04',
                                                      'max_datetime': stamp(1)[:19]})])
    swpc.close()
    gfz = sws.connect(dbPaths.dbPath(dbPaths.GFZ_DB))
    sws.upsertSamples(gfz, [('gfzKp', '2026-10-10T12:00:00Z', 3.0, 'Kp', 'def'), ('gfzKp', '2026-10-10T15:00:00Z', 7.333, 'Kp', 'def'),
                            ('gfzKp', '2026-10-10T18:00:00Z', 7.0, 'Kp', 'def'), ('gfzKp', '2026-10-10T21:00:00Z', 3.0, 'Kp', 'def')])
    gfz.close()
    donki = sws.connect(dbPaths.dbPath(dbPaths.DONKI_DB))
    sws.upsertEvents(donki, [
        ('GST', '2026-10-10T15:00:00Z', 'g1', {'gstID': 'g1', 'allKpIndex': [{'kpIndex': 7.0, 'observedTime': '2026-10-10T18:00Z'}],
                                               'linkedEvents': [{'activityID': 'i-IPS-001'}]}),
        ('SEP', '2026-10-10T16:00:00Z', 's1', {'eventTime': '2026-10-10T16:00Z', 'instruments': [{'displayName': 'GOES-P: SEISS >10 MeV'}],
                                               'linkedEvents': [{'activityID': 'f-FLR-001'}]}),
        ('SEP', '2026-10-11T16:00:00Z', 's2', {'eventTime': '2026-10-11T16:00Z', 'instruments': [{'displayName': 'STEREO A: IMPACT 13-100 MeV'}]}),
        ('CME', '2026-10-10T01:00:00Z', 'c1', {'activityID': 'c1', 'startTime': '2026-10-10T01:00Z',
                                               'cmeAnalyses': [{'featureCode': 'LE', 'isMostAccurate': True, 'speed': 1200.0, 'type': 'O'}]}),
        ('CME', '2026-10-10T05:00:00Z', 'c2', {'activityID': 'c2', 'startTime': '2026-10-10T05:00Z',
                                               'cmeAnalyses': [{'featureCode': 'LE', 'isMostAccurate': True, 'speed': 300.0, 'type': 'S'}]}),
        ('HSS', '2026-10-09T00:00:00Z', 'h1', {'hssID': 'h1', 'eventTime': '2026-10-09T00:00Z', 'instruments': [{'displayName': 'STEREO A: IMPACT'}]}),
        ('IPS', '2026-10-10T11:23:00Z', 'i1', {'activityID': 'i1', 'eventTime': '2026-10-10T11:23Z', 'location': 'Earth'})])
    donki.close()
    ps.publish('weather', NOW)
    db = siteDb()
    event = lambda kind: [json.loads(r[0]) for r in db.execute('SELECT json FROM events WHERE eventType = ? ORDER BY startUtc', (kind,))]   # noqa: E731
    storm = event('storm')
    assert len(storm) == 1 and storm[0]['level'] == 3 and storm[0]['gst'] == ['g1'] and storm[0]['links'] == ['i-IPS-001']
    assert db.execute("SELECT value FROM samples WHERE series = 'derivedStormG'").fetchone()[0] == 3.0
    s = event('sEvent')
    assert len(s) == 1 and s[0]['peakPfu'] == 30.0 and s[0]['startUtc'] == stamps[1] and s[0]['endUtc'] == stamps[5]
    assert [g['status'] for g in event('sepGroup')] == ['observed']                    # the STEREO-A record is left out
    assert [c['activityID'] for c in event('cmeShown')] == ['c1']
    assert db.execute("SELECT value FROM samples WHERE series = 'derivedCmeOtherPerDay' AND tsUtc = '2026-10-10T00:00:00Z'").fetchone()[0] == 1.0
    assert event('hssL1') == [] and [r['expectedUtc'] for r in event('hssRecurrence')] == ['2026-10-31T00:00:00Z']
    assert [r['activityID'] for r in event('ipsEarth')] == ['i1']
    flare = db.execute("SELECT value, quality FROM samples WHERE series = 'derivedFlareMaxDay'").fetchall()
    assert len(flare) == 1 and flare[0][0] == 1.7e-05 and flare[0][1].startswith('M1.7 peak') and flare[0][1].endswith('GOES-18')


def test_publish_failure_does_not_leave_the_temporary_file_locked(dbDir, monkeypatch):
    makeSwpc()

    def boom(*args, **kwargs):
        raise RuntimeError('boom')
    monkeypatch.setattr(ps, 'addScienceDerived', boom)
    with pytest.raises(RuntimeError):
        ps.publish('weather', NOW)
    assert not os.path.exists(dbPaths.dbPath('siteWeather.db.tmp'))
