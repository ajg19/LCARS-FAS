"""Tests for scripts/groupRules.py -- decision A's precedence (CelesTrak
when available, the recent-launch rule, our own rules) on synthetic
objects; no databases."""

import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'scripts'))
import groupRules as gr  # noqa: E402

NOW = datetime(2026, 10, 21, 12, tzinfo=timezone.utc)
FRESH = '2026-10-20T00:00:00Z'   # a CelesTrak fetch 1.5 days old
STALE = '2026-09-01T00:00:00Z'   # 50 days old


def obj(norad, name='SAT', objectType='PAY', launch='2020-01-01', decay=None, inGcat=True,
        owner=None, program=None, category=None, tOp=None):
    return {'noradID': norad, 'name': name, 'objectType': objectType, 'launchDate': launch,
            'decayDate': decay, 'inGcat': inGcat, 'ownerCode': owner, 'program': program,
            'category': category, 'tOp': tOp}


def test_active_rule_uses_gcat_operations_end():
    members = gr.ruleMembers([obj(1), obj(2, tOp='2024-05')], NOW)
    assert members['active'] == {1}


def test_recent_launch_is_active_even_without_gcat():
    members = gr.ruleMembers([obj(1, inGcat=False, launch='2026-09-01'),
                              obj(2, inGcat=False, launch='2026-01-01')], NOW)
    assert members['active'] == {1}


def test_only_payloads_in_orbit_count():
    members = gr.ruleMembers([obj(1, objectType='R/B'), obj(2, decay='2026-10-01')], NOW)
    assert members['active'] == set()


def test_weak_groups_are_celestrak_only():
    # Decided 2026-10-21: no rule until CelesTrak is back.
    for group in ('stations', 'orbcomm', 'sbas', 'gnss', 'sarsat', 'ses', 'intelsat', 'telesat', 'sar', 'spire'):
        assert group not in gr.RULE_GROUPS
    objects = [obj(1, category='SS'), obj(2, owner='ORBC')]
    assert gr.groupMembers(objects, {'stations': (FRESH, {1})}, NOW)['stations'] == {1}
    assert 'stations' not in gr.groupMembers(objects, {'stations': (STALE, {1})}, NOW)
    assert 'orbcomm' not in gr.groupMembers(objects, {}, NOW)


def test_constellation_needs_active_and_matches_gcat_or_name():
    members = gr.ruleMembers([
        obj(1, owner='SPXS'),                                      # GCAT owner
        obj(2, name='STARLINK-99999', inGcat=False, launch='2026-10-01'),  # not in GCAT: name
        obj(3, owner='SPXS', tOp='2025-01'),                        # ended: not active
        obj(4, name='STARLINK-1', owner='OTHER'),                   # in GCAT: name ignored
    ], NOW)
    assert members['starlink'] == {1, 2}


def test_celestrak_definitive_for_objects_launched_before_its_fetch():
    objects = [obj(1), obj(2)]                                     # both active by our rule
    result = gr.groupMembers(objects, {'active': (FRESH, {1})}, NOW)
    assert result['active'] == {1}


def test_our_rules_for_objects_launched_after_the_fetch():
    objects = [obj(1), obj(2, inGcat=False, launch='2026-10-21')]
    result = gr.groupMembers(objects, {'active': (FRESH, {1})}, NOW)
    assert result['active'] == {1, 2}


def test_stale_celestrak_falls_back_to_rules():
    objects = [obj(1), obj(2)]
    result = gr.groupMembers(objects, {'active': (STALE, {1})}, NOW)
    assert result['active'] == {1, 2}


def test_group_without_rule_only_while_celestrak_available():
    objects = [obj(1)]
    assert gr.groupMembers(objects, {'weather': (FRESH, {1})}, NOW)['weather'] == {1}
    assert 'weather' not in gr.groupMembers(objects, {'weather': (STALE, {1})}, NOW)


def test_celestrak_members_outside_the_catalogue_are_dropped():
    result = gr.groupMembers([obj(1)], {'active': (FRESH, {1, 999})}, NOW)
    assert result['active'] == {1}


def test_agreement():
    objects = [obj(1), obj(2), obj(3, tOp='2020')]
    rows = {r[0]: r for r in gr.agreement(objects, {'active': (FRESH, {1, 3})}, NOW)}
    group, ours, theirs, both, percent = rows['active']
    assert (ours, theirs, both) == (2, 2, 1)
    assert percent == 33.3
