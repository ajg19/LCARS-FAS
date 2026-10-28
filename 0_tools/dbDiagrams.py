"""Draws every LCARS-FAS database as an entity-relationship diagram, from the
REAL schemas, so the documentation cannot drift from the code.

    python 0_tools/dbDiagrams.py                 # writes 0_documentation/databases/
    python 0_tools/dbDiagrams.py --out some/dir  # elsewhere
    python 0_tools/dbDiagrams.py --no-png        # SVG and Markdown only

Where each schema comes from (the README says which, per database):
  file      the database file in databases/ (or the legacy ingestionDBs/): a COPY of it
            (and of its -wal file) is opened read-only and read with PRAGMA table_info,
            foreign_key_list, index_list and sqlite_master. The original is only copied
            from, never opened, so nothing about it changes.
  code      the file does not exist on this machine, but its CREATE TABLE
            statements are in the code (a database the website or a tool creates on
            first use, or the weather site file). They are taken from the string
            constants of the named source files and run in an in-memory database.
  planned   designed in a plan, not built (PLANNED_TABLES below).

Outputs, in 0_documentation/databases/:
  <databaseFile>.svg and .png   one diagram per database
  overview.svg and .png         how scripts move data between the databases
  schemas.md                    the same diagrams as Mermaid erDiagram source
  README.md                     one paragraph per database, generated schema notes

Relationships: declared foreign keys are solid lines. None of the databases
declares any, so the joins are drawn as DASHED lines ("logical joins"): a join-key
column (names ending ID or Id, and the few in EXTRA_JOIN_KEYS) joins to the table
that has that column as its whole primary key, or failing that as its first primary
key column. These are inferred from names, not enforced by SQLite.

Standard library only. PNG needs Pillow and a monospace TTF (matplotlib ships
DejaVu Sans Mono); without them the PNGs are skipped. No network.
"""

import argparse
import ast
import math
import os
import re
import shutil
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'scripts'))

import dbPaths  # noqa: E402

DEFAULT_OUT = os.path.join(ROOT, '0_documentation', 'databases')

# --- What is drawn ---------------------------------------------------------------
# kind: ingestion / site / inbox / legacy. status: file / code / planned (see above).
# `code`: the (source file, text its string must contain) pairs the schema comes from.
DATABASES = [
    ('SPACETRACK_DB', 'ingestion'), ('CELESTRAK_DB', 'ingestion'), ('SATNOGS_DB', 'ingestion'),
    ('GCAT_DB', 'ingestion'), ('NEWS_DB', 'ingestion'), ('GROUND_SEGMENT_DB', 'ingestion'),
    ('SKY_DB', 'ingestion'), ('GEOIP_DB', 'ingestion'), ('SWPC_DB', 'ingestion'), ('GFZ_DB', 'ingestion'),
    ('DONKI_DB', 'ingestion'), ('GCR_DB', 'ingestion'), ('SILSO_DB', 'ingestion'), ('TEC_DB', 'ingestion'),
    ('SITE_ORBITAL_DB', 'site'), ('SITE_NEWS_DB', 'site'), ('SITE_SKY_DB', 'site'),
    ('SITE_GROUND_SEGMENT_DB', 'site'), ('SITE_WEATHER_DB', 'site'),
    ('BUG_REPORTS_DB', 'inbox'), ('USAGE_DB', 'inbox'),
    ('ORBITAL_DB', 'legacy'), ('STATS_DB', 'legacy'),
]

CODE_SCHEMAS = {
    'GEOIP_DB': [('0_tools/buildGeoIPDb.py', 'CREATE TABLE places')],
    'SWPC_DB': [('scripts/spaceWeatherSamples.py', 'CREATE TABLE IF NOT EXISTS samples'), ('scripts/ingestionLog.py', 'ingestionRuns')],
    'GFZ_DB': [('scripts/spaceWeatherSamples.py', 'CREATE TABLE IF NOT EXISTS samples'), ('scripts/ingestionLog.py', 'ingestionRuns')],
    'DONKI_DB': [('scripts/spaceWeatherSamples.py', 'CREATE TABLE IF NOT EXISTS samples'), ('scripts/ingestionLog.py', 'ingestionRuns')],
    'GCR_DB': [('scripts/spaceWeatherSamples.py', 'CREATE TABLE IF NOT EXISTS samples'), ('scripts/ingestionLog.py', 'ingestionRuns')],
    'SILSO_DB': [('scripts/spaceWeatherSamples.py', 'CREATE TABLE IF NOT EXISTS samples'), ('scripts/ingestionLog.py', 'ingestionRuns'), ('scripts/ingestionSILSO.py', 'sourceFiles')],
    'TEC_DB': [('scripts/spaceWeatherSamples.py', 'CREATE TABLE IF NOT EXISTS samples'), ('scripts/ingestionLog.py', 'ingestionRuns'), ('scripts/ingestionTEC.py', 'CREATE TABLE IF NOT EXISTS tecMaps')],
    'USAGE_DB': [('scripts/visitCounter.py', 'CREATE TABLE IF NOT EXISTS logins')],
    'BUG_REPORTS_DB': [('server.py', 'CREATE TABLE IF NOT EXISTS bugReports')],
    'SITE_WEATHER_DB': [('scripts/publishSite.py', 'samplesHourly'), ('scripts/publishSite.py', 'sourceDb TEXT NOT NULL')],
}

# Designed in the plans, not yet in any database: (database constant, table, columns, note).
PLANNED_TABLES = [
    ('SPACETRACK_DB', 'gpHistory',
     [('noradID', 'INTEGER', True), ('day', 'TEXT', True), ('epoch', 'INTEGER', False), ('bstar', 'REAL', False),
      ('ndot', 'REAL', False), ('meanMotion', 'REAL', False), ('perigeeKm', 'REAL', False),
      ('apogeeKm', 'REAL', False)],
     'planned: one row per object per day, WITHOUT ROWID (0_documentation/plans/spaceWeatherIngestionPlan.md, section 4)'),
]

EXTRA_JOIN_KEYS = {'jcat', 'groupName', 'topic', 'desig', 'hip'}
JOIN_KEY = re.compile(r'(ID|Id)$')
# Logical joins that no naming rule finds: (database constant, child table, child column, parent table, parent column).
HINTS = [
    ('NEWS_DB', 'articleTopics', 'articleID', 'articles', 'id'),
    ('SITE_NEWS_DB', 'articleTopics', 'articleID', 'articles', 'id'),
]


# --- Reading schemas ---------------------------------------------------------------

class Table:
    def __init__(self, name):
        self.name = name
        self.columns = []        # (name, type, notNull, pkPosition, default)
        self.indexes = []        # (name, unique, [columns])
        self.foreignKeys = []    # (column, parentTable, parentColumn)
        self.withoutRowid = False
        self.planned = False
        self.note = ''

    @property
    def pk(self):
        return [c[0] for c in sorted((c for c in self.columns if c[3]), key=lambda c: c[3])]


class Schema:
    def __init__(self, constant, kind):
        self.constant, self.kind = constant, kind
        self.fileName = getattr(dbPaths, constant)
        self.status = 'file'
        self.path = None
        self.sources = []        # description of where the schema came from
        self.tables = []
        self.edges = []          # (childTable, childColumn, parentTable, parentColumn, declared)
        self.notes = []

    def table(self, name):
        return next((t for t in self.tables if t.name == name), None)


def readConnection(conn, schema):
    names = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    for name in names:
        table = Table(name)
        sql = conn.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)).fetchone()[0] or ''
        table.withoutRowid = bool(re.search(r'WITHOUT\s+ROWID', sql, re.I))
        for _, cname, ctype, notNull, default, pk in conn.execute(f'PRAGMA table_info("{name}")'):
            table.columns.append((cname, (ctype or '').strip(), bool(notNull), pk, default))
        for row in conn.execute(f'PRAGMA index_list("{name}")'):
            iname, unique, origin = row[1], bool(row[2]), row[3]
            if origin == 'pk':
                continue
            cols = [r[2] for r in conn.execute(f'PRAGMA index_info("{iname}")')]
            table.indexes.append((iname, unique, cols))
        for row in conn.execute(f'PRAGMA foreign_key_list("{name}")'):
            table.foreignKeys.append((row[3], row[2], row[4]))
        schema.tables.append(table)


def codeStrings(path, mustContain):
    """Every string constant in the file that has all of `mustContain` in it."""
    with open(path, encoding='utf-8') as f:
        tree = ast.parse(f.read())
    return [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)
            and 'CREATE TABLE' in n.value and mustContain in n.value]


def loadSchema(constant, kind, dbDir):
    schema = Schema(constant, kind)
    candidates = [os.path.join(dbDir, schema.fileName)]
    legacy = dbPaths.LEGACY_NAMES.get(schema.fileName)
    if legacy:
        candidates.append(os.path.join(ROOT, dbPaths.LEGACY_DB_DIR_NAME, legacy))
    found = next((p for p in candidates if os.path.exists(p)), None)
    if found:
        # Read a COPY (database and its write-ahead log): opening a WAL-mode original, even read-only,
        # rewrites its -shm file. The copy is opened read-only and thrown away.
        with tempfile.TemporaryDirectory() as scratch:
            copy = os.path.join(scratch, 'copy.db')
            shutil.copyfile(found, copy)
            if os.path.exists(found + '-wal'):
                shutil.copyfile(found + '-wal', copy + '-wal')
            conn = sqlite3.connect('file:' + copy.replace(os.sep, '/') + '?mode=ro', uri=True)
            try:
                readConnection(conn, schema)
            finally:
                conn.close()
        schema.path = found
        schema.sources = [f'introspected from the file {os.path.relpath(found, ROOT)} (a read-only copy; the original is never opened)']
    elif constant in CODE_SCHEMAS:
        schema.status = 'code'
        conn = sqlite3.connect(':memory:')
        seen = set()
        for relative, marker in CODE_SCHEMAS[constant]:
            for sql in codeStrings(os.path.join(ROOT, *relative.split('/')), marker):
                if sql not in seen:
                    seen.add(sql)
                    conn.executescript(sql)
            schema.sources.append(f'CREATE statements in {relative}')
        readConnection(conn, schema)
        conn.close()
        schema.sources.insert(0, 'the file does not exist on this machine; schema read from the code that creates it')
    else:
        raise SystemExit(f'{schema.fileName}: no file and no code schema; add it to CODE_SCHEMAS')
    for planned in PLANNED_TABLES:
        if planned[0] == constant:
            table = Table(planned[1])
            for position, (cname, ctype, isPk) in enumerate(planned[2], 1):
                table.columns.append((cname, ctype, isPk, 1 + sum(1 for c in planned[2][:position - 1] if c[2]) if isPk else 0, None))
            table.planned, table.note, table.withoutRowid = True, planned[3], True
            schema.tables.append(table)
    findEdges(schema)
    findNotes(schema)
    return schema


def findEdges(schema):
    declared = set()
    for t in schema.tables:
        for column, parent, parentColumn in t.foreignKeys:
            schema.edges.append((t.name, column, parent, parentColumn, True))
            declared.add((t.name, column))
    names = {t.name: t for t in schema.tables}
    for constant, child, column, parent, parentColumn in HINTS:
        if constant == schema.constant and child in names and parent in names:
            schema.edges.append((child, column, parent, parentColumn, False))
    done = {(e[0], e[1], e[2]) for e in schema.edges}
    keys = {c[0] for t in schema.tables for c in t.columns if JOIN_KEY.search(c[0]) or c[0] in EXTRA_JOIN_KEYS}
    for key in sorted(keys):
        owners = [t for t in schema.tables if t.pk == [key]] or [t for t in schema.tables if t.pk[:1] == [key]]
        for owner in owners:
            for t in schema.tables:
                if t is owner or not any(c[0] == key for c in t.columns) or (t.name, key) in declared:
                    continue
                if t in owners and t.name > owner.name:
                    continue   # two owners of one key: draw the line once
                if (t.name, key, owner.name) in done:
                    continue
                done.add((t.name, key, owner.name))
                schema.edges.append((t.name, key, owner.name, key, False))


def findNotes(schema):
    """Engineering observations, generated: things a reader of the schema should know."""
    n = schema.notes
    real = [t for t in schema.tables if not t.planned]
    for t in real:
        if not t.pk:
            tail = ' (a site copy: rows are replaced as a whole on every publish)' if t.name == 'ingestionRuns' else ''
            if len(t.columns) > 1 and not t.indexes and not tail:
                n.append(f'`{t.name}` has neither a primary key nor an index: lookups scan the whole table.')
            else:
                n.append(f'`{t.name}` has no primary key' + tail + '.')
        for c in t.columns:
            if not c[1]:
                n.append(f'`{t.name}.{c[0]}` has no declared type.')
    if real and not any(t.foreignKeys for t in real):
        n.append('No foreign keys are declared' + ('; the dashed lines are joins by convention only.' if schema.edges else '.'))
    types = {}
    for t in real:
        for c in t.columns:
            if JOIN_KEY.search(c[0]) or c[0] in EXTRA_JOIN_KEYS:
                types.setdefault(c[0], {}).setdefault((c[1] or 'ANY').upper(), []).append(t.name)
    for key, kinds in sorted(types.items()):
        if len(kinds) > 1:
            n.append(f'Join key `{key}` has different declared types: ' + '; '.join(
                f'{k} in {", ".join(sorted(v))}' for k, v in sorted(kinds.items())) + '.')


# --- A tiny drawing model ----------------------------------------------------------

FONT_SIZE, CHAR_W, ROW_H, HEAD_H, PAD = 12, 7.22, 18, 30, 10
GAP_X, GAP_Y, MARGIN = 100, 34, 30
COLOURS = {'ingestion': ('#FF9900', '#000000'), 'site': ('#9999FF', '#000000'), 'inbox': ('#CC99CC', '#000000'),
           'legacy': ('#BBBBBB', '#000000'), 'planned': ('#FFFFFF', '#555555'), 'other': ('#FFCC99', '#000000')}
INK, MUTED, PAPER = '#1A1A1A', '#666666', '#FFFFFF'


class Scene:
    def __init__(self, width=0, height=0):
        self.width, self.height, self.items = width, height, []

    def rect(self, x, y, w, h, fill=PAPER, stroke=INK, dash=False, radius=6, strokeWidth=1.2):
        self.items.append(('rect', x, y, w, h, fill, stroke, dash, radius, strokeWidth))

    def text(self, x, y, s, size=FONT_SIZE, bold=False, fill=INK, anchor='start', italic=False):
        self.items.append(('text', x, y, s, size, bold, fill, anchor, italic))

    def path(self, points, dash=False, stroke=INK, arrow=False, dot=False, width=1.4):
        self.items.append(('path', points, dash, stroke, arrow, dot, width))

    # -- SVG --
    def svg(self):
        out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.width:.0f}" height="{self.height:.0f}" '
               f'viewBox="0 0 {self.width:.0f} {self.height:.0f}" font-family="DejaVu Sans Mono, Consolas, Menlo, monospace">',
               f'<rect width="100%" height="100%" fill="{PAPER}"/>']
        for it in self.items:
            if it[0] == 'rect':
                _, x, y, w, h, fill, stroke, dash, radius, sw = it
                out.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="{radius}" fill="{fill}" '
                           f'stroke="{stroke}" stroke-width="{sw}"' + (' stroke-dasharray="6 4"' if dash else '') + '/>')
            elif it[0] == 'text':
                _, x, y, s, size, bold, fill, anchor, italic = it
                out.append(f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" fill="{fill}" text-anchor="{anchor}"'
                           + (' font-weight="bold"' if bold else '') + (' font-style="italic"' if italic else '')
                           + f'>{escape(s)}</text>')
            else:
                _, pts, dash, stroke, arrow, dot, width = it
                d = bezierPath(pts)
                out.append(f'<path d="{d}" fill="none" stroke="{stroke}" stroke-width="{width}"'
                           + (' stroke-dasharray="7 5"' if dash else '') + '/>')
                if arrow:
                    out.append(f'<polygon points="{arrowHead(pts)}" fill="{stroke}"/>')
                if dot:
                    out.append(f'<circle cx="{pts[0][0]:.1f}" cy="{pts[0][1]:.1f}" r="3.2" fill="{stroke}"/>')
        out.append('</svg>')
        return '\n'.join(out) + '\n'

    # -- PNG (Pillow) --
    def png(self, path, scale=2):
        from PIL import Image, ImageDraw, ImageFont
        fonts = findFonts()
        if not fonts:
            return False
        image = Image.new('RGB', (int(self.width * scale), int(self.height * scale)), PAPER)
        draw = ImageDraw.Draw(image)
        cache = {}

        def font(size, bold):
            key = (size, bold)
            if key not in cache:
                cache[key] = ImageFont.truetype(fonts[1 if bold else 0], int(round(size * scale)))
            return cache[key]

        for it in self.items:
            if it[0] == 'rect':
                _, x, y, w, h, fill, stroke, dash, radius, sw = it
                box = [x * scale, y * scale, (x + w) * scale, (y + h) * scale]
                draw.rounded_rectangle(box, radius=radius * scale, fill=fill, outline=None if dash else stroke,
                                       width=max(1, int(sw * scale)))
                if dash:
                    dashedRect(draw, box, stroke, scale)
            elif it[0] == 'text':
                _, x, y, s, size, bold, fill, anchor, italic = it
                f = font(size, bold)
                width = draw.textlength(s, font=f)
                px = x * scale - (width / 2 if anchor == 'middle' else width if anchor == 'end' else 0)
                draw.text((px, y * scale), s, font=f, fill=fill, anchor='ls')
            else:
                _, pts, dash, stroke, arrow, dot, width = it
                line = sampleBezier(pts)
                scaled = [(px * scale, py * scale) for px, py in line]
                if dash:
                    dashedLine(draw, scaled, stroke, max(1, int(width * scale)), 7 * scale, 5 * scale)
                else:
                    draw.line(scaled, fill=stroke, width=max(1, int(width * scale)), joint='curve')
                if arrow:
                    head = [tuple(float(v) * scale for v in p.split(',')) for p in arrowHead(pts).split()]
                    draw.polygon(head, fill=stroke)
                if dot:
                    r = 3.2 * scale
                    draw.ellipse([pts[0][0] * scale - r, pts[0][1] * scale - r, pts[0][0] * scale + r, pts[0][1] * scale + r], fill=stroke)
        image.save(path, 'PNG', optimize=True)
        return True


def escape(s):
    return s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def findFonts():
    try:
        import matplotlib
        base = os.path.join(matplotlib.get_data_path(), 'fonts', 'ttf')
        regular, bold = os.path.join(base, 'DejaVuSansMono.ttf'), os.path.join(base, 'DejaVuSansMono-Bold.ttf')
        if os.path.exists(regular) and os.path.exists(bold):
            return regular, bold
    except Exception:
        pass
    for regular, bold in (('C:/Windows/Fonts/consola.ttf', 'C:/Windows/Fonts/consolab.ttf'),
                          ('/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf',
                           '/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf')):
        if os.path.exists(regular) and os.path.exists(bold):
            return regular, bold
    return None


def bezierPath(pts):
    if len(pts) == 4:
        (x0, y0), (x1, y1), (x2, y2), (x3, y3) = pts
        return f'M{x0:.1f},{y0:.1f} C{x1:.1f},{y1:.1f} {x2:.1f},{y2:.1f} {x3:.1f},{y3:.1f}'
    return 'M' + ' L'.join(f'{x:.1f},{y:.1f}' for x, y in pts)


def sampleBezier(pts, steps=40):
    if len(pts) != 4:
        return list(pts)
    (x0, y0), (x1, y1), (x2, y2), (x3, y3) = pts
    out = []
    for i in range(steps + 1):
        t = i / steps
        a, b, c, d = (1 - t) ** 3, 3 * t * (1 - t) ** 2, 3 * t ** 2 * (1 - t), t ** 3
        out.append((a * x0 + b * x1 + c * x2 + d * x3, a * y0 + b * y1 + c * y2 + d * y3))
    return out


def arrowHead(pts, size=9):
    line = sampleBezier(pts)
    (x1, y1), (x2, y2) = line[-min(4, len(line))], line[-1]
    angle = math.atan2(y2 - y1, x2 - x1)
    left = (x2 - size * math.cos(angle - 0.4), y2 - size * math.sin(angle - 0.4))
    right = (x2 - size * math.cos(angle + 0.4), y2 - size * math.sin(angle + 0.4))
    return f'{x2:.1f},{y2:.1f} {left[0]:.1f},{left[1]:.1f} {right[0]:.1f},{right[1]:.1f}'


def dashedLine(draw, pts, colour, width, dash, gap):
    carry, on = 0.0, True
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        length = math.hypot(x1 - x0, y1 - y0)
        pos = 0.0
        while pos < length:
            step = min((dash if on else gap) - carry, length - pos)
            if on:
                draw.line([(x0 + (x1 - x0) * pos / length, y0 + (y1 - y0) * pos / length),
                           (x0 + (x1 - x0) * (pos + step) / length, y0 + (y1 - y0) * (pos + step) / length)],
                          fill=colour, width=width)
            pos += step
            carry += step
            if carry >= (dash if on else gap) - 1e-6:
                on, carry = not on, 0.0


def dashedRect(draw, box, colour, scale):
    x0, y0, x1, y1 = box
    for a, b in (((x0, y0), (x1, y0)), ((x1, y0), (x1, y1)), ((x1, y1), (x0, y1)), ((x0, y1), (x0, y0))):
        dashedLine(draw, [a, b], colour, max(1, int(1.2 * scale)), 6 * scale, 4 * scale)


# --- One database ---------------------------------------------------------------------

def displayType(column):
    return column[1] or 'ANY'


def boxSize(table, marks):
    rows = [(marks(table, c), c[0], displayType(c)) for c in table.columns]
    nameW = max([len(r[1]) for r in rows] + [len(table.name) - 8, 4])
    typeW = max([len(r[2]) for r in rows] + [3])
    width = PAD * 2 + CHAR_W * (3 + nameW + 2 + typeW)
    width = max(width, PAD * 2 + CHAR_W * (len(table.name) + (10 if table.planned else 0)), 150)
    extra = 1 if table.withoutRowid and not table.planned else 0
    return rows, width, HEAD_H + ROW_H * (len(rows) + extra) + 8


def layoutOrder(schema):
    """Tables in breadth-first order of the relationship graph, most connected first."""
    degree = {t.name: 0 for t in schema.tables}
    adjacent = {t.name: set() for t in schema.tables}
    for child, _, parent, _, _ in schema.edges:
        degree[child] += 1
        degree[parent] += 1
        adjacent[child].add(parent)
        adjacent[parent].add(child)
    order, seen = [], set()
    for start in sorted(degree, key=lambda n: (-degree[n], n)):
        if start in seen:
            continue
        queue = [start]
        seen.add(start)
        while queue:
            name = queue.pop(0)
            order.append(name)
            for nxt in sorted(adjacent[name] - seen, key=lambda n: (-degree[n], n)):
                seen.add(nxt)
                queue.append(nxt)
    return [schema.table(n) for n in order]


def drawSchema(schema):
    fill, ink = COLOURS[schema.kind]
    joinColumns = {(e[0], e[1]) for e in schema.edges if not e[4]} | {(e[2], e[3]) for e in schema.edges if not e[4]}
    fkColumns = {(t.name, f[0]) for t in schema.tables for f in t.foreignKeys}

    def marks(table, column):
        if column[3]:
            return 'PK'
        if (table.name, column[0]) in fkColumns:
            return 'FK'
        return 'LJ' if (table.name, column[0]) in joinColumns else '  '

    tables = layoutOrder(schema)
    sizes = {t.name: boxSize(t, marks) for t in tables}
    columnsCount = 1 if len(tables) == 1 else min(5, max(2, math.ceil(math.sqrt(len(tables) * 1.2))))
    heights = [0.0] * columnsCount
    placed = {}
    columnTables = [[] for _ in range(columnsCount)]
    for t in tables:
        c = heights.index(min(heights))
        columnTables[c].append(t)
        heights[c] += sizes[t.name][2] + GAP_Y
    top = 78
    x = MARGIN
    widths = []
    for c in range(columnsCount):
        w = max([sizes[t.name][1] for t in columnTables[c]] + [150])
        y = top
        for t in columnTables[c]:
            placed[t.name] = (x, y, w)
            y += sizes[t.name][2] + GAP_Y
        widths.append(w)
        x += w + GAP_X
    scene = Scene(max(x - GAP_X + MARGIN, 640), max(heights) + top + 54)

    statusText = {'file': 'from the database file', 'code': 'schema from code (file not on this machine)',
                  'planned': 'planned'}[schema.status]
    scene.rect(MARGIN, 14, scene.width - 2 * MARGIN, 44, fill=fill, stroke=fill, radius=14)
    scene.text(MARGIN + 16, 42, schema.fileName, size=18, bold=True, fill=ink)
    scene.text(scene.width - MARGIN - 16, 42, f'{schema.kind} database  |  {statusText}', size=12, fill=ink, anchor='end')

    positions = {}
    for t in tables:
        px, py, pw = placed[t.name]
        rows, _, height = sizes[t.name]
        colour = COLOURS['planned'] if t.planned else (fill, ink)
        scene.rect(px, py, pw, height, fill=PAPER, stroke=INK if not t.planned else MUTED, dash=t.planned)
        scene.rect(px, py, pw, HEAD_H, fill=colour[0] if not t.planned else '#EEEEEE', stroke=INK if not t.planned else MUTED,
                   dash=t.planned)
        scene.text(px + PAD, py + 20, t.name, size=13, bold=True, fill=colour[1])
        if t.planned:
            scene.text(px + pw - PAD, py + 20, 'planned', size=11, fill=MUTED, anchor='end', italic=True)
        nameW = max([len(r[1]) for r in rows] + [4])
        for i, (mark, cname, ctype) in enumerate(rows):
            ry = py + HEAD_H + ROW_H * i + 14
            if mark.strip():
                scene.text(px + PAD, ry, mark, size=11, bold=True, fill='#B35C00' if mark == 'PK' else '#2B4FB3')
            scene.text(px + PAD + CHAR_W * 3, ry, cname, bold=(mark == 'PK'))
            scene.text(px + PAD + CHAR_W * (3 + nameW + 2), ry, ctype, fill=MUTED)
            positions[(t.name, cname)] = (px, py + HEAD_H + ROW_H * i + ROW_H / 2, pw)
        if t.withoutRowid and not t.planned:
            scene.text(px + PAD, py + HEAD_H + ROW_H * len(rows) + 14, 'WITHOUT ROWID', size=10, fill=MUTED, italic=True)
    for child, ccol, parent, pcol, declared in schema.edges:
        a, b = positions.get((child, ccol)), positions.get((parent, pcol))
        if not a or not b:
            continue
        if abs(a[0] - b[0]) < 1:   # same column: loop out on the right-hand side
            x0, x3 = a[0] + a[2], b[0] + b[2]
            bulge = 48 + (hash((child, parent)) % 3) * 12
            pts = [(x0, a[1]), (x0 + bulge, a[1]), (x3 + bulge, b[1]), (x3, b[1])]
        elif a[0] < b[0]:
            x0, x3 = a[0] + a[2], b[0]
            mid = (x3 - x0) / 2
            pts = [(x0, a[1]), (x0 + mid, a[1]), (x3 - mid, b[1]), (x3, b[1])]
        else:
            x0, x3 = a[0], b[0] + b[2]
            mid = (x0 - x3) / 2
            pts = [(x0, a[1]), (x0 - mid, a[1]), (x3 + mid, b[1]), (x3, b[1])]
        scene.path(pts, dash=not declared, stroke='#2B4FB3' if declared else '#444444', arrow=True, dot=True)
    ly = scene.height - 22
    scene.path([(MARGIN, ly - 4), (MARGIN + 40, ly - 4)], stroke='#2B4FB3', arrow=True)
    scene.text(MARGIN + 50, ly, 'declared foreign key', size=11)
    scene.path([(MARGIN + 220, ly - 4), (MARGIN + 260, ly - 4)], dash=True, stroke='#444444', arrow=True)
    scene.text(MARGIN + 270, ly, 'logical join (by column name, not enforced)', size=11)
    scene.text(MARGIN + 560, ly, 'PK primary key   FK foreign key   LJ logical-join column   dot = child, arrow = parent', size=11, fill=MUTED)
    return scene


# --- Mermaid ------------------------------------------------------------------------------

def mermaidType(column):
    word = re.sub(r'\W+', '_', (column[1] or 'ANY').strip()).strip('_')
    return word or 'ANY'


def mermaid(schema):
    lines = ['erDiagram']
    for t in schema.tables:
        lines.append(f'    {t.name} {{')
        for c in t.columns:
            lines.append(f'        {mermaidType(c)} {c[0]}' + (' PK' if c[3] else ''))
        lines.append('    }')
    for child, ccol, parent, pcol, declared in schema.edges:
        link = '--' if declared else '..'
        label = f'{ccol} (declared FK)' if declared else f'{ccol} (logical join)'
        lines.append(f'    {child} }}o{link}|| {parent} : "{label}"')
    return '\n'.join(lines)


# --- The overview: how data moves --------------------------------------------------------------

# Site file -> the ingestion databases it is built from (scripts/publishSite.py). Checked against TYPES below.
SITE_INPUTS = {
    'orbital': ['SPACETRACK_DB', 'SATNOGS_DB', 'CELESTRAK_DB', 'GCAT_DB'],
    'news': ['NEWS_DB'], 'sky': ['SKY_DB'], 'groundSegment': ['GROUND_SEGMENT_DB'],
    'weather': ['SWPC_DB', 'GFZ_DB', 'DONKI_DB', 'GCR_DB', 'SILSO_DB', 'TEC_DB'],
}
# Ingestion database -> the outside world it takes data from, and the scripts that are not in runIngestion.SOURCES.
EXTERNAL = {
    'SPACETRACK_DB': 'Space-Track (NORAD catalogue)', 'CELESTRAK_DB': 'CelesTrak', 'SATNOGS_DB': 'SatNOGS',
    'GCAT_DB': "GCAT (J. McDowell's catalogue)", 'NEWS_DB': 'news RSS feeds', 'SWPC_DB': 'NOAA SWPC',
    'GFZ_DB': 'GFZ Potsdam (Kp, ap)', 'DONKI_DB': 'NASA CCMC DONKI',
    'GCR_DB': 'Oulu cosmic ray station', 'SILSO_DB': 'WDC-SILSO (Brussels)',
    'TEC_DB': 'CODE (Bern) and NOAA GloTEC',
    'GROUND_SEGMENT_DB': 'laptop: ground-segment workbook', 'SKY_DB': 'laptop: star catalogues (Hipparcos, Gaia)',
    'GEOIP_DB': 'DB-IP city file (laptop)',
}
EXTRA_SCRIPTS = {'GROUND_SEGMENT_DB': ['ingestionGroundSegment.py'], 'SKY_DB': ['buildSkyCatalogue.py'],
                 'GEOIP_DB': ['0_tools/buildGeoIPDb.py']}


def drawOverview(schemas):
    import runIngestion
    import publishSite
    constantOf = {getattr(dbPaths, c): c for c, _ in DATABASES}
    scriptsOf = {}
    for source, (script, dbFile, jobs, kinds) in runIngestion.SOURCES.items():
        scriptsOf.setdefault(constantOf.get(dbFile), []).append(script)
    for constant, extra in EXTRA_SCRIPTS.items():
        scriptsOf.setdefault(constant, []).extend(extra)
    problems = []
    for kind in SITE_INPUTS:
        if kind not in publishSite.TYPES:
            problems.append(f'overview: site kind {kind} is not in publishSite.TYPES')
    for kind in publishSite.TYPES:
        if kind not in SITE_INPUTS:
            problems.append(f'overview: publishSite.TYPES has {kind}, which the overview does not know')
    kindOf = {c: k for c, k in DATABASES}
    siteFile = {kind: constantOf[name] for kind, name in ((k, v) for k, v in publishSite.TYPES.items())}

    cx = [MARGIN, 270, 560, 860, 1070, 1330]    # x of the six columns
    box = {'w': [210, 250, 230, 170, 210, 190], 'h': 40}
    scene = Scene(1560, 0)
    scene.rect(MARGIN, 14, scene.width - 2 * MARGIN, 44, fill='#FFCC99', stroke='#FFCC99', radius=14)
    scene.text(MARGIN + 16, 42, 'LCARS-FAS data flow: sources, ingestion, publish, site, inbox', size=18, bold=True)
    heads = ['outside sources', 'scripts (cron via runIngestion.py)', 'ingestion databases', 'publish step',
             'site databases', 'web server']
    for i, h in enumerate(heads):
        scene.text(cx[i], 84, h, size=12, bold=True, fill=MUTED)
    nodes = {}

    def node(col, y, label, fill, key, sub=None, dash=False, h=None):
        h = h or box['h']
        scene.rect(cx[col], y, box['w'][col], h, fill=fill, stroke=INK, dash=dash)
        scene.text(cx[col] + 8, y + 17, label, size=11, bold=True)
        if sub:
            scene.text(cx[col] + 8, y + 32, sub, size=10, fill=MUTED)
        nodes[key] = (cx[col], y + h / 2, box['w'][col])

    ingestion = [c for c, k in DATABASES if k == 'ingestion']
    y = 100
    for c in ingestion:
        node(0, y, EXTERNAL.get(c, 'outside source'), '#FFFFFF', ('ext', c), dash=True)
        scripts = ', '.join(s.replace('0_tools/', '') for s in scriptsOf.get(c, ['(no script found)']))
        node(1, y, scripts[:36], '#FFE0B3', ('script', c), sub=scripts[36:72] or None)
        node(2, y, getattr(dbPaths, c), COLOURS['ingestion'][0], ('db', c))
        scene.path([(cx[0] + box['w'][0], y + 20), (cx[1], y + 20)], arrow=True)
        scene.path([(cx[1] + box['w'][1], y + 20), (cx[2], y + 20)], arrow=True)
        y += 58
    sites = list(SITE_INPUTS)
    siteY = {}
    pubY = 100
    node(3, pubY, 'publishSite.py', '#FFE0B3', ('publish',), sub='build, check, atomic swap', h=52)
    sy = 100
    for kind in sites:
        c = siteFile[kind]
        node(4, sy, getattr(dbPaths, c), COLOURS['site'][0], ('site', c))
        siteY[kind] = sy
        sy += 58
    for kind, inputs in SITE_INPUTS.items():
        for c in inputs:
            a, b = nodes[('db', c)], nodes[('publish',)]
            scene.path([(a[0] + a[2], a[1]), (a[0] + a[2] + 140, a[1]), (b[0] - 60, b[1] + (sites.index(kind) - 2) * 6),
                        (b[0], b[1] + (sites.index(kind) - 2) * 6)], stroke='#555555', arrow=True, width=1.0)
        a, b = nodes[('publish',)], nodes[('site', siteFile[kind])]
        scene.path([(a[0] + a[2], a[1] + (sites.index(kind) - 2) * 6), (a[0] + a[2] + 40, a[1] + (sites.index(kind) - 2) * 6),
                    (b[0] - 40, b[1]), (b[0], b[1])], stroke='#555555', arrow=True, width=1.0)
    node(5, 100, 'server.py', '#CCE5CC', ('server',), sub='WSGI app: pages and /api', h=60)
    for kind in sites:
        a, b = nodes[('site', siteFile[kind])], nodes[('server',)]
        scene.path([(a[0] + a[2], a[1]), (a[0] + a[2] + 30, a[1]), (b[0] - 30, b[1] + (sites.index(kind) - 2) * 6),
                    (b[0], b[1] + (sites.index(kind) - 2) * 6)], stroke='#555555', arrow=True, width=1.0)
    iy = sy + 40
    scene.text(cx[4], iy - 8, 'written by visitors (via the server)', size=11, bold=True, fill=MUTED)
    for c, k in DATABASES:
        if k == 'inbox':
            node(4, iy, getattr(dbPaths, c), COLOURS['inbox'][0], ('inbox', c))
            b = nodes[('server',)]
            scene.path([(b[0], 160), (b[0] - 30, iy + 20), (cx[4] + box['w'][4] + 20, iy + 20),
                        (cx[4] + box['w'][4], iy + 20)], dash=True, stroke='#555555', arrow=True, width=1.0)
            iy += 58
    node(5, iy - 116, 'visitCounter.py', '#CCE5CC', ('counter',), sub='logins by city; reads ingestionGeoIP', h=48)
    a = nodes[('db', 'GEOIP_DB')]
    c1 = nodes[('counter',)]
    scene.path([(a[0] + a[2], a[1] + 12), (a[0] + a[2] + 60, a[1] + 12), (c1[0] - 60, c1[1] + 18), (c1[0], c1[1] + 18)],
               dash=True, stroke='#555555', arrow=True, width=1.0)
    ly = iy + 10
    scene.text(cx[4], ly, 'legacy, pre-refactor (still read as a fallback until step 15)', size=11, bold=True, fill=MUTED)
    ly += 14
    for c, k in DATABASES:
        if k == 'legacy':
            node(4, ly, getattr(dbPaths, c), COLOURS['legacy'][0], ('legacy', c))
            ly += 52
    scene.height = max(y, sy, ly) + 80
    notes = ['solid arrows: scripts write (left) and publishSite reads (right); dashed: written or read at run time by the website',
             'runIngestion.py takes the writers\' lock, runs one ingestion script, then publishes the site file(s) it feeds, only if the run changed something']
    for i, line in enumerate(notes):
        scene.text(MARGIN, scene.height - 40 + i * 16, line, size=11, fill=MUTED)
    return scene, problems


# --- Writing everything --------------------------------------------------------------------------

INFO = {
    'SPACETRACK_DB': ('The NORAD satellite catalogue (via Space-Track): the newest general-perturbations element set for every tracked object, one row per object, plus the run history. The only source of orbital elements for the site.',
                      'scripts/ingestionSpaceTrack.py (cron 00:00 and 12:00 server time)', 'scripts/publishSite.py (orbital)', 'LIVE and DEV', 'rebuilt by the next full pass (nothing is lost if deleted, but history of runs is)', 'planned: gpHistory, one row per object per day, for drag work.'),
    'CELESTRAK_DB': ('CelesTrak group memberships (which satellites belong to which named group), the radar cross-section (RCS) figures kept for good, and when each group was last fetched. Disabled in FAS for now (CELESTRAK_ENABLED=0 on the server), so mostly static.',
                     'scripts/ingestionCelesTrak.py (every third day)', 'scripts/publishSite.py (orbital groups)', 'LIVE and DEV', 'refetched by the job; RCS figures are kept across rebuilds', ''),
    'SATNOGS_DB': ('SatNOGS transmitters (radio downlinks and uplinks) and the TLE feed used only as an ID crosswalk (designators).',
                   'scripts/ingestionSatNOGS.py (cron 00:30 and 12:30)', 'scripts/publishSite.py (orbital radio)', 'LIVE and DEV', 'refetched by the job', ''),
    'GCAT_DB': ("Jonathan McDowell's General Catalog of Artificial Space Objects: objects, payloads, organisations, launches, decays and derived brightness estimates, with the files' fetch record.",
                'scripts/ingestGcat.py (Sundays 03:00); scripts/estimateBrightness.py fills gcatBrightness', 'scripts/publishSite.py, scripts/orbitStats.py, scripts/enrichEirp.py', 'LIVE and DEV', 'refetched weekly (about 30 MB of source files)', ''),
    'NEWS_DB': ('Space news articles from 18 RSS feeds, their topic tags and the topic counts the site shows.',
                'scripts/readNews.py (every 30 min), scripts/tagNews.py, scripts/pruneNews.py', 'scripts/publishSite.py (news)', 'LIVE and DEV', 'refilled by the feeds; old articles pruned', ''),
    'GROUND_SEGMENT_DB': ('Ground-segment sites (stations, teleports) for the GRND SGMNT map. A reference database built on the laptop from the master workbook.',
                          'scripts/ingestionGroundSegment.py (laptop)', 'scripts/publishSite.py (groundSegment), server.py (legacy fallback)', 'LIVE (uploaded by the deploy) and DEV', 'rebuilt on the laptop from grndSgmntAssets_master.xlsx and deployed as a file', ''),
    'SKY_DB': ('The fixed sky for GRD VIEW: bright stars, constellation lines, Milky Way outline and deep-sky objects. A reference database built on the laptop.',
               'scripts/buildSkyCatalogue.py (laptop)', 'scripts/publishSite.py (sky), server.py', 'LIVE (uploaded by the deploy) and DEV', 'rebuilt on the laptop from the Hipparcos and Gaia match (10 arcsec radius) and deployed as a file', ''),
    'GEOIP_DB': ('Lookup from visitor address ranges to cities (DB-IP city lite), used to count logins by city without keeping addresses.',
                 '0_tools/buildGeoIPDb.py (laptop, from the DB-IP CSV)', 'scripts/visitCounter.py', 'built on the laptop; whether it is on LIVE was not verified here', 'rebuilt from a new DB-IP CSV', ''),
    'SWPC_DB': ('NOAA SWPC real-time space weather: solar wind and field at L1, GOES X-ray and protons, Kp, Dst, F10.7, forecasts, flare and radio events, and the newest OVATION and D-RAP maps. One long table of (series, time, value) plus events and maps.',
                'scripts/ingestionSWPC.py (jobs swpcFast every 15 min, swpcSlow hourly, swpcMaps hourly, swpcPrune daily)', 'scripts/publishSite.py (weather)', 'DEV only so far (not deployed)', '1-minute rows older than 90 days are deleted daily; other series are kept; refilled by the feeds (24 h of L1 and 7 days of GOES come from one first run)', ''),
    'GFZ_DB': ('GFZ Potsdam geomagnetic indices: Kp, ap, daily Ap, Hp30, Hp60, F10.7 observed and adjusted, and the international sunspot number.',
               'scripts/ingestionGFZ.py (hourly; --backfill 90 once for history)', 'scripts/publishSite.py (weather)', 'DEV only so far (not deployed)', 'refetched; preliminary values are replaced by definitive ones, never the reverse', ''),
    'DONKI_DB': ('NASA CCMC DONKI events: CME, HSS, GST, SEP, FLR and IPS, each stored whole as the source JSON.',
                 'scripts/ingestionDONKI.py (hourly, last 7 days; --backfill 90 once for history)', 'scripts/publishSite.py (weather)', 'DEV only so far (not deployed)', 'refetched; revised events replace older versions', ''),
    'GCR_DB': ('Neutron-monitor count rates (galactic cosmic rays) from the Oulu cosmic ray station\'s own online query: Oulu and Dome C, pressure-corrected and raw counts and air pressure, hourly, plus the monthly record since 1964. Credit: the Oulu cosmic ray station site and the Sodankyla Geophysical Observatory.',
               'scripts/ingestionGCR.py (job gcr hourly, gcrMonthly monthly; --backfill DAYS once for history)', 'scripts/publishSite.py (weather)', 'DEV only so far (not deployed)', 'refetched; nothing is deleted (hourly data are about 1.6 MB a year per station)', ''),
    'SILSO_DB': ('WDC-SILSO monthly mean sunspot number since 1749 (mean, standard deviation, observations; definitive or provisional). CC BY-NC 4.0, credit WDC-SILSO, Royal Observatory of Belgium, Brussels.',
                 'scripts/ingestionSILSO.py (monthly; a HEAD request checks Last-Modified first)', 'scripts/publishSite.py (weather)', 'DEV only so far (not deployed)', 'refetched when the file changes; provisional months become definitive about a quarter later', ''),
    'TEC_DB': ('Global total electron content (TEC) maps, 7 days: CODE (Astronomical Institute, University of Bern) hourly maps observed (rapid, previous day) and predicted 1, 2 and 5 days ahead, 71 x 73 cells; NOAA SWPC GloTEC every 3 hours, 72 x 72 cells with TEC, anomaly, NmF2, hmF2. Each map is a gzipped compact JSON; global-maximum summaries are in samples. Credit: CODE, Dach et al. (2026), DOI 10.48620/97772; NOAA SWPC.',
               'scripts/ingestionTEC.py (job tecCode daily 09:15 UTC, tecGlotec every 3 hours)', 'scripts/publishSite.py (weather)', 'DEV only so far (not deployed)', 'maps older than 7 days are deleted; a CODE file already held is never fetched again', ''),
    'SITE_ORBITAL_DB': ('What the website reads for everything orbital: the object catalogue with elements, groups, radio links, EIRP and brightness, the ON-ORBIT and LAUNCHES statistics, the GCAT tables the site uses, and every source\'s run history.',
                        'scripts/publishSite.py (rebuilt from scratch and swapped in whole, with the previous file kept as .prev)', 'server.py', 'LIVE and DEV', 'republished after every changing orbital ingestion run', ''),
    'SITE_NEWS_DB': ('Copy of the news tables the site reads.', 'scripts/publishSite.py', 'server.py', 'LIVE and DEV', 'republished after a changing news run', ''),
    'SITE_SKY_DB': ('Copy of the sky catalogue the site reads.', 'scripts/publishSite.py', 'server.py', 'LIVE and DEV', 'republished from the sky reference database', ''),
    'SITE_GROUND_SEGMENT_DB': ('Copy of the ground-segment table the site reads.', 'scripts/publishSite.py', 'server.py', 'LIVE and DEV', 'republished from the reference database', ''),
    'SITE_WEATHER_DB': ('Everything the WEATHER panels read: full series, three days of the high-rate series at native resolution and 90 days as hourly means, events, the newest global maps, and derived series (F10.7A, storm scale). Visitors never touch the ingestion databases.',
                        'scripts/publishSite.py (publishWeather; after every changing SWPC, GFZ or DONKI run)', 'server.py (/api/weather/now, series, events, map, aurora-at)', 'DEV only so far (not deployed; the file is created by the first publish)', 'rebuilt from scratch each publish', ''),
    'BUG_REPORTS_DB': ('Bug reports submitted by visitors (no address kept, a salted visitor hash for rate limits).',
                       'server.py (/api/bug-report)', '0_tools/bugs.py copies them into the bug log (bugsDB.xlsx)', 'created on the first report on each host', 'not rebuilt; it is the only copy of the reports', ''),
    'USAGE_DB': ('Logins per day and city (counts only), for ABOUT > USAGE.', 'scripts/visitCounter.py (one POST per browser session)', 'server.py (/api/usage), 0_tools/seedUsageSample.py (writes sample rows on DEV)', 'created on the first visit on each host', 'not rebuilt; counts accumulate', ''),
    'ORBITAL_DB': ('Pre-refactor orbital database: objects, group memberships and the CelesTrak fetch log. Replaced by siteOrbital.db; the server falls back to it where no site file exists.',
                   'scripts/ingestOrbitalData.py, ingestSatcat.py, ingestSatnogsRf.py, enrichEirp.py (legacy pipeline)', 'server.py (legacy fallback)', 'LIVE until the legacy fallback is removed (plan step 15), and DEV', 'obsolete; to be removed in step 15 of dbRefactorPlan.md', ''),
    'STATS_DB': ('Pre-refactor ON-ORBIT and LAUNCHES statistics tables (now inside siteOrbital.db).', 'scripts/orbitStats.py (legacy)', 'server.py (legacy fallback)', 'LIVE until step 15, and DEV', 'obsolete; to be removed in step 15', ''),
}


def sizeText(schema):
    if not schema.path:
        return 'not on this machine'
    mb = os.path.getsize(schema.path) / 1e6
    return f'{mb:.2f} MB on this machine' if mb >= 0.01 else '<0.01 MB on this machine'


def main(argv=None):
    parser = argparse.ArgumentParser(description='Draw every LCARS-FAS database from its real schema.')
    parser.add_argument('--out', default=DEFAULT_OUT)
    parser.add_argument('--db-dir', default=dbPaths.DB_DIR, help='folder holding the database files (read-only)')
    parser.add_argument('--no-png', action='store_true')
    args = parser.parse_args(argv)
    os.makedirs(args.out, exist_ok=True)
    schemas = [loadSchema(c, k, args.db_dir) for c, k in DATABASES]
    pngOk = not args.no_png
    if pngOk:
        try:
            import PIL  # noqa: F401
            pngOk = findFonts() is not None
        except ImportError:
            pngOk = False
        if not pngOk:
            print('PNG skipped: Pillow or a monospace TTF was not found')
    written = []

    def save(scene, base):
        svgPath = os.path.join(args.out, base + '.svg')
        with open(svgPath, 'w', encoding='utf-8', newline='\n') as f:
            f.write(scene.svg())
        written.append(svgPath)
        if pngOk:
            pngPath = os.path.join(args.out, base + '.png')
            scene.png(pngPath)
            written.append(pngPath)

    for s in schemas:
        save(drawSchema(s), s.fileName)
    overview, problems = drawOverview(schemas)
    save(overview, 'overview')

    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    md = ['# LCARS-FAS database schemas (Mermaid)', '',
          f'Generated by `0_tools/dbDiagrams.py` from the real schemas on {today} UTC. Do not edit by hand; run the tool again.',
          'Solid lines are declared foreign keys; there are none, so every line is a logical join inferred from a shared join-key column name (written `..`).', '']
    for s in schemas:
        md += [f'## {s.fileName}', '', f'{s.kind} database; {"; ".join(s.sources)}.', '', '```mermaid', mermaid(s), '```', '']
        index = [(t.name, i) for t in s.tables for i in t.indexes]
        if index:
            md += ['Indexes (besides the primary keys):', ''] + [f'- `{n}`: `{i[0]}` on ({", ".join(i[2])})' + (' unique' if i[1] else '') for n, i in index] + ['']
    with open(os.path.join(args.out, 'schemas.md'), 'w', encoding='utf-8', newline='\n') as f:
        f.write('\n'.join(md))
    written.append(os.path.join(args.out, 'schemas.md'))

    readme = ['# LCARS-FAS databases', '',
              f'Generated by `0_tools/dbDiagrams.py` on {today} UTC from the real database files (read-only) or, where a database file is not on this machine, from the CREATE statements in the code. Run `python 0_tools/dbDiagrams.py` to regenerate everything here; do not edit these files by hand.', '',
              'Conventions: `ingestion<Source>.db` holds what a source gave us; `site<Type>.db` is what the website reads, rebuilt whole by `scripts/publishSite.py`; `inbox<Name>.db` is written by visitors through the server. Visitors never touch an ingestion database. All times are UTC.', '',
              '## Overview', '', '![How data moves between the databases](overview.png)', '',
              '(SVG: [overview.svg](overview.svg).) The Mermaid source for every diagram is in [schemas.md](schemas.md).', '']
    total = 0
    for s in schemas:
        total += len([t for t in s.tables if not t.planned])
        purpose, writer, readers, where, rebuilt, extra = INFO.get(s.constant, ('(no description yet: add it to INFO in dbDiagrams.py)', '', '', '', '', ''))
        readme += [f'## {s.fileName}', '', f'![{s.fileName}]({s.fileName}.png) ([SVG]({s.fileName}.svg))', '',
                   f'{purpose} **Written by:** {writer}. **Read by:** {readers}. **Where:** {where}. **Rebuilt:** {rebuilt}. **Size:** {sizeText(s)}. '
                   f'**Tables:** {len([t for t in s.tables if not t.planned])}'
                   + (f' (plus planned: {", ".join(t.name for t in s.tables if t.planned)})' if any(t.planned for t in s.tables) else '')
                   + f'. **Schema source:** {"; ".join(s.sources)}.' + (f' {extra}' if extra else ''), '']
        if s.notes:
            readme += ['Schema notes (generated):', ''] + [f'- {n}' for n in s.notes] + ['']
    readme += ['## Not yet designed', '',
               'Everything in `0_documentation/plans/spaceWeatherChartsPlan.md` that is stored has a database; the Space-Track history table (`gpHistory`) is planned.', '']
    if problems:
        readme += ['## Overview checks', ''] + [f'- {p}' for p in problems] + ['']
    with open(os.path.join(args.out, 'README.md'), 'w', encoding='utf-8', newline='\n') as f:
        f.write('\n'.join(readme))
    written.append(os.path.join(args.out, 'README.md'))
    tables = sum(len([t for t in s.tables if not t.planned]) for s in schemas)
    print(f'{len(schemas)} databases, {tables} tables, {len(written)} files written to {args.out}')
    for s in schemas:
        print(f'  {s.fileName:28} {s.status:5} {len(s.tables):2} tables, {len(s.edges):2} joins, {len(s.notes)} notes')
    for p in problems:
        print('  PROBLEM:', p)
    return 1 if problems else 0


if __name__ == '__main__':
    sys.exit(main())
