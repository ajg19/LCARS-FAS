"""Tests for scripts/runIngestion.py -- decision C: publish after an
ingestion that changed something, and only then. In a temporary database
folder; the ingestion script and the publish are stand-ins."""

import os
import sqlite3
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'scripts'))
import dbPaths  # noqa: E402
import runIngestion as ri  # noqa: E402
from ingestionLog import recordRun  # noqa: E402


@pytest.fixture
def dbDir(tmp_path, monkeypatch):
    monkeypatch.setattr(dbPaths, 'DB_DIR', str(tmp_path))
    monkeypatch.setattr(dbPaths, 'LEGACY', False)
    return tmp_path


def fakeIngestion(job, succeeded=True, changes=1, code=0, record=True, dbFile=dbPaths.SATNOGS_DB):
    """A run() stand-in that records one run, as the real script would."""
    def run(argv):
        if record:
            db = sqlite3.connect(dbPaths.dbPath(dbFile))
            recordRun(db, job, '2099-01-01T00:00:00Z', succeeded, changes)
            db.close()
        return code
    return run


class Publisher:
    def __init__(self, fail=False):
        self.kinds, self.fail = [], fail

    def __call__(self, kind):
        self.kinds.append(kind)
        if self.fail:
            raise RuntimeError('refused')
        return {'orbital_objects': 10}


def test_changes_trigger_publish_of_dependent_files(dbDir):
    publish = Publisher()
    assert ri.runSource('satnogs', fakeIngestion('satnogs', changes=5), publish) == 0
    assert publish.kinds == ['orbital']


def test_no_changes_no_publish(dbDir):
    publish = Publisher()
    ri.runSource('satnogs', fakeIngestion('satnogs', changes=0), publish)
    assert publish.kinds == []


def test_failed_run_publishes_nothing_and_keeps_its_exit_code(dbDir):
    publish = Publisher()
    assert ri.runSource('satnogs', fakeIngestion('satnogs', succeeded=False, code=1), publish) == 1
    assert publish.kinds == []


def test_skipped_run_records_nothing_and_publishes_nothing(dbDir):
    publish = Publisher()
    assert ri.runSource('satnogs', fakeIngestion('satnogs', record=False), publish) == 0
    assert publish.kinds == []


def test_an_older_run_is_not_mistaken_for_this_one(dbDir):
    db = sqlite3.connect(dbPaths.dbPath(dbPaths.SATNOGS_DB))
    recordRun(db, 'satnogs', '2000-01-01T00:00:00Z', True, 99)
    db.execute("UPDATE ingestionRuns SET finishedAt = '2000-01-01T00:01:00Z'")
    db.commit()
    db.close()
    publish = Publisher()
    ri.runSource('satnogs', fakeIngestion('satnogs', record=False), publish)
    assert publish.kinds == []


def test_refused_publish_makes_the_run_fail(dbDir):
    assert ri.runSource('satnogs', fakeIngestion('satnogs'), Publisher(fail=True)) == 1


def test_every_source_maps_to_a_script_that_exists():
    for script, _, jobs, kinds in ri.SOURCES.values():
        assert os.path.exists(os.path.join(ri.SCRIPTS_DIR, script))
        assert jobs and set(kinds) <= {'orbital', 'news', 'sky', 'groundSegment', 'weather'}


@pytest.mark.parametrize('source, dbFile', [('swpcFast', dbPaths.SWPC_DB), ('swpcSlow', dbPaths.SWPC_DB), ('swpcMaps', dbPaths.SWPC_DB),
                                            ('gfz', dbPaths.GFZ_DB), ('donki', dbPaths.DONKI_DB),
                                            ('tecCode', dbPaths.TEC_DB), ('tecGlotec', dbPaths.TEC_DB)])
def test_a_changed_space_weather_run_publishes_the_weather_file(dbDir, source, dbFile):
    assert ri.SOURCES[source][3] == ('weather',)
    publish = Publisher()
    assert ri.runSource(source, fakeIngestion(source, changes=5, dbFile=dbFile), publish) == 0
    assert publish.kinds == ['weather']


def test_the_prune_job_publishes_nothing(dbDir):
    assert ri.SOURCES['swpcPrune'][3] == ()
    publish = Publisher()
    assert ri.runSource('swpcPrune', fakeIngestion('swpcPrune', changes=5, dbFile=dbPaths.SWPC_DB), publish) == 0
    assert publish.kinds == []


def test_a_failed_space_weather_run_reports_the_failure_and_publishes_nothing(dbDir):
    publish = Publisher()
    code = ri.runSource('gfz', fakeIngestion('gfz', succeeded=False, code=1, dbFile=dbPaths.GFZ_DB), publish)
    assert code == 1 and publish.kinds == []


def test_the_two_swpc_sources_run_one_script_with_their_own_job_argument(dbDir):
    calls = []

    def run(argv):
        calls.append(argv[1:])
        return 0

    for source in ('swpcFast', 'swpcSlow', 'gfz'):
        ri.runSource(source, run, Publisher())
    scripts = [os.path.basename(c[0]) for c in calls]
    assert scripts == ['ingestionSWPC.py', 'ingestionSWPC.py', 'ingestionGFZ.py']
    assert calls[0][1:] == ['--job', 'swpcFast'] and calls[1][1:] == ['--job', 'swpcSlow'] and calls[2][1:] == []


def test_each_sources_recorded_jobs_are_the_names_its_script_logs():
    import ingestionDONKI
    import ingestionGFZ
    import ingestionSWPC
    import ingestionTEC
    assert ri.SOURCES['swpcFast'][2] == (ingestionSWPC.JOB_FAST,) and ri.SOURCES['swpcSlow'][2] == (ingestionSWPC.JOB_SLOW,)
    assert ri.SOURCES['swpcPrune'][2] == (ingestionSWPC.JOB_PRUNE,) and ri.SOURCES['swpcMaps'][2] == (ingestionSWPC.JOB_MAPS,)
    assert ri.SOURCES['gfz'][2] == (ingestionGFZ.JOB,) and ri.SOURCES['donki'][2] == (ingestionDONKI.JOB,)
    assert ri.SOURCES['tecCode'][2] == (ingestionTEC.JOB_CODE,) and ri.SOURCES['tecGlotec'][2] == (ingestionTEC.JOB_GLOTEC,)
    assert ri.SCRIPT_ARGS['tecCode'] == ('--job', 'tecCode') and ri.SCRIPT_ARGS['tecGlotec'] == ('--job', 'tecGlotec')


def test_unknown_source_is_a_usage_error():
    assert ri.main(['nonsense']) == 2


@pytest.mark.skipif(os.name == 'nt', reason='fcntl locking is Linux-only')
def test_lock_times_out_while_another_writer_holds_it(tmp_path):
    path = str(tmp_path / '.writers.lock')
    with ri.Lock(path):
        with pytest.raises(TimeoutError):
            with ri.Lock(path, wait=0):
                pass
