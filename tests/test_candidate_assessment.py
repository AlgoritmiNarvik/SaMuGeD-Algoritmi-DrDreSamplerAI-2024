import json
import shutil
import sqlite3
from collections import namedtuple

import pytest

from samuged.candidate_assessment import prepare, summary, packet, notice_check
from samuged.work_identity import Client, run

WORK = '00000000-0000-0000-0000-000000000001'
SECOND = '00000000-0000-0000-0000-000000000003'
THIRD = '00000000-0000-0000-0000-000000000004'
TUNE = [{'text': '(C) 1994 Tune 1000 Corporation ;1965 Jobete Music Co., Inc.', 'track': 0, 'tick': 0}]
# key: (musical hash, notices, API candidates as (work, basis changes))
SOURCES = {
    's1': ('m1', [{'text': 'Copyright 1990 J. Bach', 'track': 0, 'tick': 0}], [(WORK, {})]),
    's2': ('m2', [], [(WORK, {}), (SECOND, {})]),
    's3': ('m3', [{'text': 'All rights reserved 1997', 'track': 0, 'tick': 0}], [(WORK, {'title_agreement': 'alias_normalized'})]),
    's4': ('m4', TUNE, [(WORK, {})]),
    's5': ('m1', [], [(WORK, {})]),
    's6': ('m6', [], [(THIRD, {})]),
    's7': ('m6', [], [(WORK, {})]),
    's8': ('m8', [], [(WORK, {})]),
    's9': ('m9', [], []),
    's10': ('m10', [], [(WORK, {'title_agreement': 'recording_title_normalized', 'creator_agreement': 'initials_candidate'})]),
    's11': ('m11', [], [(WORK, {})]),
}
# Offline dump candidates: s1 agrees, s8 is disjoint, s9 is dump only with many namesakes, s11 is a superset.
OFFLINE = {'s1': [(WORK, 1)], 's8': [(SECOND, 1)], 's9': [(WORK, 7)], 's11': [(WORK, 1), (SECOND, 1)]}


def build(tmp_path, monkeypatch):
    from test_work_identity import setup
    usage, _, work = setup(tmp_path, monkeypatch)
    def get(self, entity, identifier=None, query=None):
        payload = dict(id=identifier or WORK, title='Song', relations=[
            dict(type='composer', artist=dict(name='Bach', id=WORK))])
        return ({'works': [payload]} if query else payload), {'url': 'https://musicbrainz.org/work/'+WORK}
    monkeypatch.setattr(Client, 'get', get)
    assert run(work)['work_candidates'] == 1
    meta = tmp_path/'meta.sqlite'; shutil.copyfile(usage, meta)
    with sqlite3.connect(work) as w, sqlite3.connect(meta) as m:
        base_key, _, _, _, base_json, _ = w.execute('SELECT * FROM work_candidates').fetchone()
        base = json.loads(base_json)
        w.execute('DELETE FROM work_candidates')
        for key, (music, notices, candidates) in SOURCES.items():
            for table, db in (('queue', w), ('records', m), ('source_rights', m)):
                db.execute(f'CREATE TEMP TABLE IF NOT EXISTS t_{table} AS SELECT * FROM {table} WHERE 0')
                db.execute(f'DELETE FROM temp.t_{table}')
                db.execute(f'INSERT INTO temp.t_{table} SELECT * FROM {table} WHERE source_key=?', (base_key,))
                db.execute(f'UPDATE temp.t_{table} SET source_key=?', (key,))
                if table != 'source_rights':
                    db.execute(f'UPDATE temp.t_{table} SET source_sha256=?', ('sha-'+key,))
                db.execute(f'INSERT INTO {table} SELECT * FROM temp.t_{table}')
            m.execute('UPDATE records SET musical_sha256=?,candidate_group=? WHERE source_key=?', (music, 'g-'+music, key))
            m.execute('UPDATE source_rights SET copyright_notices_json=? WHERE source_key=?', (json.dumps(notices), key))
            for work_id, change in candidates:
                evidence = json.loads(base_json); evidence['match_basis'].update(change)
                evidence['work']['id'] = work_id
                w.execute('INSERT INTO work_candidates VALUES (?,?,?,?,?,?)', (key, work_id, '', 'Song', json.dumps(evidence), 'candidate'))
        for db in (w, m):
            for table in ('queue', 'records', 'source_rights'):
                if db.execute('SELECT 1 FROM sqlite_master WHERE name=?', (table,)).fetchone():
                    db.execute(f'DELETE FROM {table} WHERE source_key=?', (base_key,))
    offline = tmp_path/'offline.sqlite'; shutil.copyfile(work, offline)
    with sqlite3.connect(offline) as o:
        o.execute('DELETE FROM work_candidates')
        for key, rows in OFFLINE.items():
            for work_id, namesakes in rows:
                evidence = dict(base, provider='musicbrainz_json_dump', policy='work-candidates-v3-dump')
                evidence['match_basis'] = dict(base['match_basis'], title_namesake_count=namesakes, title_alias_namesake_count=9)
                evidence['work'] = dict(base['work'], id=work_id)
                o.execute('INSERT INTO work_candidates VALUES (?,?,?,?,?,?)', (key, work_id, '', 'Song', json.dumps(evidence), 'candidate'))
    subset = tmp_path/'subset.sqlite'
    with sqlite3.connect(subset) as db:
        db.execute('CREATE TABLE title_namesakes(normalized_title TEXT PRIMARY KEY, work_count INTEGER, alias_count INTEGER)')
        db.execute("INSERT INTO title_namesakes VALUES ('song',1,0)")
    return work, meta, offline


def rows(path):
    with sqlite3.connect(path) as db:
        result = {}
        for key, work, provider, tier, signals in db.execute('SELECT source_key,work_id,provider,tier,signals_json FROM assessments'):
            result[key, work, provider] = (tier, json.loads(signals))
        best = {k: (t, p) for k, t, p in db.execute('SELECT source_key,best_tier,review_priority FROM source_summary')}
        return result, best


def test_tiers_signals_and_inputs_unchanged(tmp_path, monkeypatch):
    work, meta, offline = build(tmp_path, monkeypatch)
    subset = tmp_path/'subset.sqlite'
    before = [p.read_bytes() for p in (work, meta, offline, subset)]
    out = tmp_path/'assessment.sqlite'
    result = prepare(work, meta, out, offline_index=offline, subset=subset)
    assert [p.read_bytes() for p in (work, meta, offline, subset)] == before
    assert result['identity_status'] == 'unverified_assessment_only' and result['rights_clearance'] == 'not_established'
    found, best = rows(out)
    api, dump = 'musicbrainz', 'musicbrainz_json_dump'
    assert best['s1'] == ('single_work_full_agreement', 1)
    assert best['s2'] == ('multiple_works', 6) and best['s3'] == best['s10'] == ('single_work_weaker_agreement', 4)
    # A notice naming another party is a reason to read it, never a conflict on its own.
    assert best['s4'] == ('single_work_full_agreement', 2) and best['s6'] == best['s7'] == best['s8'] == ('conflict', 0)
    assert best['s9'] == ('single_work_weaker_agreement', 4) and best['s5'] == ('single_work_full_agreement', 2)
    s1 = found['s1', WORK, api][1]
    assert s1['notice_check'] == 'corroborates' and s1['notice_tokens'] == ['bach'] and s1['writers'] == ['Bach']
    assert s1['duplicate_check'] == 'duplicates_agree' and s1['duplicate_count'] == 1 and s1['candidate_group'] == 'g-m1'
    assert s1['provider_cross_check'] == 'providers_agree' and found['s1', WORK, dump][1]['namesake_count'] == 1
    # Alias only namesakes are recorded but do not lower the tier.
    assert found['s1', WORK, dump][0] == 'single_work_full_agreement' and found['s1', WORK, dump][1]['title_alias_namesake_count'] == 9
    assert found['s2', SECOND, api][1]['distinct_works'] == 2 and found['s2', WORK, api][1]['notice_check'] == 'no_notice'
    assert found['s3', WORK, api][1]['notice_check'] == 'uninformative'
    four = found['s4', WORK, api][1]
    assert four['notice_check'] == 'names_other_party' and {'tune', 'jobete'} <= set(four['notice_tokens'])
    assert found['s6', THIRD, api][1]['duplicate_check'] == 'duplicates_conflict'
    assert found['s8', WORK, api][1]['provider_cross_check'] == 'providers_differ'
    assert found['s8', SECOND, dump][1]['distinct_works_all_providers'] == 2
    # A dump superset is expected because the dump checks every namesake: no conflict.
    eleven = found['s11', WORK, api][1]
    assert eleven['provider_cross_check'] == 'providers_overlap' and eleven['provider_sets_nested'] is True
    assert best['s11'] == ('multiple_works', 6)
    nine = found['s9', WORK, dump][1]
    assert nine['namesake_count'] == 7 and nine['provider_cross_check'] == 'single_provider' and nine['origin'] == 'offline_index'
    assert found['s10', WORK, api][1]['creator_agreement_kind'] == 'initials_candidate'
    with sqlite3.connect(out) as db:
        assert db.execute('SELECT DISTINCT identity_status,rights_clearance FROM source_summary').fetchall() == [('unverified_assessment_only', 'not_established')]
        inputs = json.loads(db.execute('SELECT inputs_json FROM provenance').fetchone()[0])
        assert set(inputs) == {'work_index', 'metadata', 'offline_index', 'subset'}
        assert 'one provider found a subset of the other' in json.loads(db.execute("SELECT reasons_json FROM source_summary WHERE source_key='s11'").fetchone()[0])
        assert 'works share this title' in ' '.join(json.loads(db.execute("SELECT reasons_json FROM source_summary WHERE source_key='s9'").fetchone()[0]))
    with sqlite3.connect(work) as db:
        assert db.execute('SELECT count(*) FROM reviews').fetchone()[0] == 0


def test_subset_namesakes_and_api_only(tmp_path, monkeypatch):
    work, meta, _ = build(tmp_path, monkeypatch)
    subset = tmp_path/'subset.sqlite'
    with sqlite3.connect(subset) as db:
        db.execute("UPDATE title_namesakes SET work_count=2,alias_count=9")
    out = tmp_path/'a.sqlite'; prepare(work, meta, out, subset=subset)
    found, best = rows(out)
    assert found['s1', WORK, 'musicbrainz'][1]['namesake_count'] == 2
    assert found['s1', WORK, 'musicbrainz'][1]['title_alias_namesake_count'] == 9
    assert found['s1', WORK, 'musicbrainz'][1]['namesake_source'] == 'subset'
    assert best['s1'] == ('single_work_full_agreement', 1) and best['s8'][0] == 'single_work_full_agreement'
    with sqlite3.connect(subset) as db:
        db.execute("UPDATE title_namesakes SET work_count=4")
    prepare(work, meta, tmp_path/'b.sqlite', subset=subset)
    assert rows(tmp_path/'b.sqlite')[1]['s1'] == ('single_work_weaker_agreement', 3)
    assert 's9' not in best


@pytest.mark.parametrize('notices,writers,expected', [
    ([], ['Bach'], 'no_notice'),
    ([{'text': '  '}], ['Bach'], 'no_notice'),
    ([{'text': 'Sequenced by Johann Sebastian Bach'}], ['Johann Sebastian Bach'], 'corroborates'),
    ([{'text': 'Copyright (c) 1995 MIDI file, all rights reserved'}], ['Bach'], 'uninformative'),
    ([{'text': '(C) 1993 Roland Corporation'}], ['Bach'], 'names_other_party'),
    ([{'text': 'copyright by someone lowercase'}], ['Bach'], 'uninformative')])
def test_notice_check(notices, writers, expected):
    assert notice_check(notices, writers)[0] == expected


def test_source_binding_failure(tmp_path, monkeypatch):
    work, meta, offline = build(tmp_path, monkeypatch)
    with sqlite3.connect(meta) as db:
        db.execute("UPDATE records SET source_sha256='other' WHERE source_key='s9'")
    out = tmp_path/'a.sqlite'
    with pytest.raises(ValueError, match='binding'):
        prepare(work, meta, out, offline_index=offline)
    assert not out.exists() and not list(tmp_path.glob('.a.sqlite.*'))
    prepare(work, meta, out)  # s9 has API candidates only in the dump index.
    with sqlite3.connect(offline) as db:
        db.execute("UPDATE work_candidates SET evidence_json=json_set(evidence_json,'$.provider','musicbrainz')")
    with pytest.raises(ValueError, match='both candidate indexes'):
        prepare(work, tmp_path/'meta.sqlite', tmp_path/'b.sqlite', offline_index=offline)


def test_verified_candidate_is_refused(tmp_path, monkeypatch):
    work, meta, _ = build(tmp_path, monkeypatch)
    with sqlite3.connect(work) as db:
        db.execute("UPDATE work_candidates SET evidence_json=json_set(evidence_json,'$.match_basis.source_identity_verified',json('true')) WHERE source_key='s1'")
    with pytest.raises(ValueError, match='unverified'):
        prepare(work, meta, tmp_path/'a.sqlite')


def test_existing_output_and_storage_reserve(tmp_path, monkeypatch):
    work, meta, _ = build(tmp_path, monkeypatch)
    out = tmp_path/'a.sqlite'; out.write_text('keep')
    with pytest.raises(FileExistsError):
        prepare(work, meta, out)
    assert out.read_text() == 'keep'
    out.unlink()
    monkeypatch.setattr('samuged.candidate_assessment.shutil.disk_usage', lambda p: namedtuple('Usage', 'total used free')(0, 0, 10*1024**3))
    with pytest.raises(ValueError, match='reserve'):
        prepare(work, meta, out)
    assert not out.exists()


def test_summary_and_packet(tmp_path, monkeypatch):
    work, meta, offline = build(tmp_path, monkeypatch)
    out = tmp_path/'a.sqlite'; prepare(work, meta, out, offline_index=offline, subset=tmp_path/'subset.sqlite')
    counts = summary(out)
    assert counts['sources'] == 11 and counts['assessments'] == 16
    assert counts['best_tier']['local'] == {'conflict': 3, 'multiple_works': 2,
        'single_work_full_agreement': 3, 'single_work_weaker_agreement': 3}
    assert counts['notice_check'] == {'corroborates': 2, 'names_other_party': 1, 'no_notice': 12, 'uninformative': 1}
    assert counts['duplicate_check'] == {'duplicates_agree': 3, 'duplicates_conflict': 2, 'no_duplicates': 11}
    target = tmp_path/'packet.json'
    result = packet(out, work, target, offline_index=offline, limit=3)
    document = json.loads(target.read_text())
    assert result['sources'] == 3 and 'Nothing here is an accepted identity' in document['header']['notice']
    assert document['header']['identity_verified'] is False
    assert [s['best_tier'] for s in document['sources']] == ['conflict']*3
    assert [s['source_key'] for s in document['sources']] == sorted(s['source_key'] for s in document['sources'])
    first = document['sources'][0]
    assert first['source_title'] == 'Song' and first['source_creator'] == 'Bach'
    candidate = first['candidates'][0]
    assert candidate['musicbrainz_url'] == 'https://musicbrainz.org/work/'+candidate['work_id']
    assert candidate['writers'] == ['Bach'] and candidate['work_title'] == 'Song' and 'tier' in candidate
    with pytest.raises(FileExistsError):
        packet(out, work, target)
    weaker = tmp_path/'weaker.json'
    packet(out, work, weaker, tier='single_work_weaker_agreement')
    assert {s['best_tier'] for s in json.loads(weaker.read_text())['sources']} == {'single_work_weaker_agreement'}
    for bad in (dict(limit=0), dict(limit=1001), dict(limit=True), dict(tier='accepted')):
        with pytest.raises(ValueError):
            packet(out, work, tmp_path/'bad.json', **bad)
    with sqlite3.connect(work) as db:
        db.execute("UPDATE queue SET title='Changed' WHERE source_key='s1'")
    with pytest.raises(ValueError, match='provenance'):
        packet(out, work, tmp_path/'bad.json')
    assert not (tmp_path/'bad.json').exists()


def test_unknown_namesake_count_is_not_full_agreement(tmp_path, monkeypatch):
    work, meta, offline = build(tmp_path, monkeypatch)
    out = tmp_path/'a.sqlite'; prepare(work, meta, out, offline_index=offline)
    found, best = rows(out)
    assert found['s5', WORK, 'musicbrainz'][1]['namesake_count'] is None
    assert found['s5', WORK, 'musicbrainz'][0] == 'single_work_weaker_agreement' and best['s5'] == ('single_work_weaker_agreement', 4)
    # The dump row carries its own namesake count and may still reach the full tier.
    assert found['s1', WORK, 'musicbrainz_json_dump'][0] == 'single_work_full_agreement' and best['s1'] == ('single_work_full_agreement', 1)
    with sqlite3.connect(out) as db:
        assert 'namesake count unknown' in json.loads(db.execute("SELECT reasons_json FROM source_summary WHERE source_key='s5'").fetchone()[0])


def test_work_index_lock_blocks_concurrent_runner(tmp_path, monkeypatch):
    import fcntl
    work, meta, _ = build(tmp_path, monkeypatch)
    out = tmp_path/'a.sqlite'
    with work.with_suffix('.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(ValueError, match='work index lock held'):
            prepare(work, meta, out)
    assert not out.exists()
    prepare(work, meta, out)
    with work.with_suffix('.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)  # Released after the build.


def test_packet_rehashes_inputs_at_the_end(tmp_path, monkeypatch):
    import samuged.candidate_assessment as module
    work, meta, _ = build(tmp_path, monkeypatch)
    out = tmp_path/'a.sqlite'; prepare(work, meta, out)
    original, seen = module.file_digest, set()
    def digest(path):
        if path == out and path in seen:
            return 'changed'
        seen.add(path)
        return original(path)
    monkeypatch.setattr(module, 'file_digest', digest)
    target = tmp_path/'packet.json'
    with pytest.raises(ValueError, match='input changed'):
        packet(out, work, target)
    assert not target.exists() and not list(tmp_path.glob('.packet.json.*'))
