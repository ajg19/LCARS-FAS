"""Builds assets/weatherCoast.json, the light outline used by the WEATHER maps (assets/weatherMap.js),
from the country boundaries the site already ships (assets/leaflet/world.json). Offline: no network.

Each ring is simplified (Douglas-Peucker, tolerance TOLERANCE_DEG) and stored as whole tenths of a degree,
the first point absolute and the rest as steps from the one before: {"unit": 0.1, "rings": [[lon0, lat0, dLon, dLat, ...], ...]}.
Rings shorter than MIN_EXTENT_DEG across are dropped (specks of islands). Run:  python 0_tools/buildWeatherCoast.py
"""
import json
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE = os.path.join(ROOT, 'assets', 'leaflet', 'world.json')
TARGET = os.path.join(ROOT, 'assets', 'weatherCoast.json')
TOLERANCE_DEG = 0.25     # a 4 px error at most on a 1,000 px wide world map is 1.4 degrees; this is well inside it
MIN_EXTENT_DEG = 0.8


def simplify(points, tolerance):
    """Douglas-Peucker on an open polyline (iterative, no recursion limit)."""
    if len(points) < 3:
        return points
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        first, last = stack.pop()
        (x1, y1), (x2, y2) = points[first], points[last]
        dx, dy = x2 - x1, y2 - y1
        length = math.hypot(dx, dy)
        worst, worstAt = -1.0, None
        for i in range(first + 1, last):
            x, y = points[i]
            distance = (math.hypot(x - x1, y - y1) if length == 0 else abs(dy * (x - x1) - dx * (y - y1)) / length)
            if distance > worst:
                worst, worstAt = distance, i
        if worstAt is not None and worst > tolerance:
            keep[worstAt] = True
            stack.append((first, worstAt))
            stack.append((worstAt, last))
    return [p for p, k in zip(points, keep) if k]


def rings_of(geometry):
    if geometry['type'] == 'Polygon':
        polygons = [geometry['coordinates']]
    elif geometry['type'] == 'MultiPolygon':
        polygons = geometry['coordinates']
    else:
        polygons = []
    for polygon in polygons:
        for ring in polygon:
            yield ring


def build():
    with open(SOURCE, encoding='utf-8') as handle:
        collection = json.load(handle)
    out = []
    for feature in collection['features']:
        for ring in rings_of(feature['geometry']):
            points = [(p[0], p[1]) for p in ring]
            xs, ys = [p[0] for p in points], [p[1] for p in points]
            if max(max(xs) - min(xs), max(ys) - min(ys)) < MIN_EXTENT_DEG:
                continue
            points = simplify(points, TOLERANCE_DEG)
            tenths = [(round(x * 10), round(y * 10)) for x, y in points]
            flat = [tenths[0][0], tenths[0][1]]
            for (x0, y0), (x1, y1) in zip(tenths, tenths[1:]):
                flat += [x1 - x0, y1 - y0]
            out.append(flat)
    return {'unit': 0.1, 'rings': out}


if __name__ == '__main__':
    result = build()
    with open(TARGET, 'w', encoding='utf-8', newline='\n') as handle:
        json.dump(result, handle, separators=(',', ':'))
    size = os.path.getsize(TARGET)
    print(f'{len(result["rings"])} rings, {sum(len(r) // 2 for r in result["rings"])} points, {size} bytes -> {TARGET}')
    sys.exit(0)
