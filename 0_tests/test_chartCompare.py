"""Runs 0_tests/chartCompare.js (node): the OLD LAUNCHES charts against the NEW ones built on assets/chartCore.js, same
data, same inputs; and `node --check` on every JavaScript file under assets/. Skipped where node is not installed."""

import glob
import os
import shutil
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NODE = shutil.which('node')
pytestmark = pytest.mark.skipif(NODE is None, reason='node is not installed')


def test_new_launches_charts_match_the_old_ones():
    result = subprocess.run([NODE, os.path.join(ROOT, '0_tests', 'chartCompare.js')], capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout[-3000:] + result.stderr[-1000:]
    assert 'different' in result.stdout


def test_new_on_orbit_charts_match_the_old_ones():
    result = subprocess.run([NODE, os.path.join(ROOT, '0_tests', 'chartCompareOnOrbit.js')], capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout[-3000:] + result.stderr[-1000:]
    assert ' 0 different' in result.stdout


def test_weather_time_charts():
    """assets/chartTime.js and the first WEATHER chart (K1): assertions and a golden string (no old version to compare)."""
    result = subprocess.run([NODE, os.path.join(ROOT, '0_tests', 'chartTimeTest.js')], capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout[-3000:] + result.stderr[-1000:]
    assert ' 0 failed' in result.stdout


def test_eo_selectors():
    """The EO control panel's selectors (assets/eoPanel.js, assets/eoOptions.js): the SOURCE drop-down lists exactly the sources matching every filter."""
    result = subprocess.run([NODE, os.path.join(ROOT, '0_tests', 'eoSelectorsTest.js')], capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout[-3000:] + result.stderr[-1000:]
    assert ' 0 failed' in result.stdout


@pytest.mark.parametrize('path', sorted(p for p in glob.glob(os.path.join(ROOT, 'assets', '*.js'))))
def test_javascript_syntax(path):
    result = subprocess.run([NODE, '--check', path], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr[-2000:]
