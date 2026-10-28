"""Tests for 0_tools/dbDiagrams.py: schema reading from a throwaway database,
logical-join detection, Mermaid output and a full run into a temporary folder.
Nothing is written under 0_documentation/."""

import os
import sqlite3
import sys
import xml.dom.minidom

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, '0_tools'))
import dbDiagrams as dd  # noqa: E402


@pytest.fixture
def sample(tmp_path):
    path = tmp_path / 'sample.db'
    conn = sqlite3.connect(path)
    conn.executescript('''
        CREATE TABLE objects (noradID INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE groupMembers (groupName TEXT NOT NULL, noradID INTEGER NOT NULL, PRIMARY KEY (groupName, noradID));
        CREATE TABLE groups (groupName TEXT PRIMARY KEY, fetchedAt TEXT) WITHOUT ROWID;
        CREATE TABLE notes (noradID INTEGER, text TEXT, child INTEGER REFERENCES objects(noradID));
        CREATE INDEX notesByNorad ON notes (noradID);
    ''')
    schema = dd.Schema('SWPC_DB', 'ingestion')
    dd.readConnection(conn, schema)
    conn.close()
    dd.findEdges(schema)
    dd.findNotes(schema)
    return schema


def test_tables_columns_keys_and_indexes_are_read(sample):
    objects = sample.table('objects')
    assert objects.pk == ['noradID'] and [c[0] for c in objects.columns] == ['noradID', 'name']
    assert sample.table('groups').withoutRowid
    assert sample.table('groupMembers').pk == ['groupName', 'noradID']
    assert sample.table('notes').indexes == [('notesByNorad', False, ['noradID'])]
    assert sample.table('notes').foreignKeys == [('child', 'objects', 'noradID')]


def test_declared_keys_are_solid_and_name_based_joins_are_logical(sample):
    edges = {(c, col, p): declared for c, col, p, _, declared in sample.edges}
    assert edges[('notes', 'child', 'objects')] is True
    assert edges[('groupMembers', 'noradID', 'objects')] is False     # whole primary key of objects
    assert edges[('groupMembers', 'groupName', 'groups')] is False
    assert edges[('notes', 'noradID', 'objects')] is False


def test_notes_flag_missing_primary_keys_and_declared_nothing(sample):
    assert any('`notes` has no primary key' in n for n in sample.notes)


def test_mermaid_has_every_table_and_a_dotted_logical_line(sample):
    text = dd.mermaid(sample)
    assert text.startswith('erDiagram') and 'objects {' in text and 'INTEGER noradID PK' in text
    assert 'groupMembers }o..|| objects : "noradID (logical join)"' in text
    assert 'notes }o--|| objects : "child (declared FK)"' in text


def test_scene_renders_valid_svg(sample):
    svg = dd.drawSchema(sample).svg()
    root = xml.dom.minidom.parseString(svg).documentElement
    assert root.tagName == 'svg' and 'objects' in svg and 'PK' in svg
    assert 'stroke-dasharray' in svg   # a logical join


def test_full_run_writes_svg_mermaid_and_readme(tmp_path):
    if not os.path.isdir(dd.dbPaths.DB_DIR):
        pytest.skip('no databases/ folder on this machine')
    assert dd.main(['--out', str(tmp_path), '--no-png']) == 0
    names = os.listdir(tmp_path)
    assert {'README.md', 'schemas.md', 'overview.svg', 'ingestionSWPC.db.svg', 'siteWeather.db.svg'} <= set(names)
    assert not any(n.endswith('.png') for n in names)
    for n in names:
        if n.endswith('.svg'):
            xml.dom.minidom.parse(os.path.join(tmp_path, n))
    readme = open(os.path.join(tmp_path, 'README.md'), encoding='utf-8').read()
    for constant, _ in dd.DATABASES:
        assert getattr(dd.dbPaths, constant) in readme
