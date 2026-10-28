"""The map outline (assets/weatherCoast.json) is what 0_tools/buildWeatherCoast.py makes from the shipped world file, and it is small."""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, '0_tools'))

import buildWeatherCoast  # noqa: E402


def test_simplify_keeps_the_ends_and_the_corners_and_drops_the_straight_run():
    points = [(0, 0), (1, 0.01), (2, 0), (3, 0), (3, 5), (3, 10)]
    kept = buildWeatherCoast.simplify(points, 0.25)
    assert kept[0] == (0, 0) and kept[-1] == (3, 10)
    assert (3, 0) in kept
    assert (1, 0.01) not in kept and (3, 5) not in kept


def test_saved_outline_is_the_current_build_and_light():
    saved_path = os.path.join(ROOT, 'assets', 'weatherCoast.json')
    with open(saved_path, encoding='utf-8') as handle:
        saved = json.load(handle)
    assert saved == buildWeatherCoast.build()
    assert os.path.getsize(saved_path) < 60000
    for flat in saved['rings']:
        x = y = 0
        for i in range(0, len(flat), 2):
            x += flat[i]
            y += flat[i + 1]
            assert -1800 <= x <= 1800 and -900 <= y <= 900   # tenths of a degree
