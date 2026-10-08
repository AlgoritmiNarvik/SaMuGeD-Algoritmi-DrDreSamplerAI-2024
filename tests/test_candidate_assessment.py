import json
import shutil
import sqlite3
from collections import namedtuple

import pytest

from samuged import work_identity_offline_catalogue as woc
from samuged import work_identity_offline_recordings as wor
from samuged.candidate_assessment import CATALOGUE, creator_kind, main, parser, prepare, summary, packet, notice_check
from samuged.dataset import file_digest
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
    's12': ('m12', [], []),
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


FULLEXPORT = 'musicbrainz_fullexport'
# Full export candidates as (work, recording, creator agreement): s1 agrees with API and dump, s3 is disjoint
# from the API, s11 nests inside the dump superset and s12 is full export only with two recordings of one work.
RECORDINGS = {'s1': [(WORK, 'r1', 'normalized_tokens')], 's3': [(SECOND, 'r2', 'normalized_tokens')],
              's11': [(WORK, 'r3', 'normalized_tokens')],
              's12': [(WORK, 'r4', 'initials_candidate'), (WORK, 'r5', 'initials_candidate')]}


def recording_evidence(work_id, recording_id, agreement, title='Song', creator='Bach'):
    """Evidence in the shape written by work_identity_offline_recordings.match."""
    basis = dict(source_creator_basis='catalog_artist', query_title=title, query_creator=creator,
        title_agreement='recording_title_normalized', creator_agreement=agreement,
        credited_artists=[dict(name=creator, gid='a1', agreement=agreement)],
        recording=dict(gid=recording_id, name=title, credit=creator), recording_namesake_count=3,
        matching_recording_count=1, matching_recordings_truncated=False, linked_work_count=1, linked_works_truncated=False,
        distinct_work_candidates=1, multiple_work_candidates=False, musical_comparison='not_performed',
        source_identity_verified=False)
    work = dict(gid=work_id, title=title, type='Song', relations=[dict(type='composer', artist=dict(id='a1', name=creator))])
    return dict(provider=wor.PROVIDER, policy=wor.POLICY, metadata_license='CC0-1.0', method=wor.METHOD,
        dump=dict(export_name='20261007-002147'), match_basis=basis, work=work, musical_work_license_status='unknown',
        rights_holder_status='not_established', **wor.UNVERIFIED)


def recordings_index(tmp_path, work, candidates=RECORDINGS):
    path = tmp_path/'recordings.sqlite'
    with sqlite3.connect(path) as db:
        db.executescript(wor.SCHEMA)
        db.execute("ATTACH DATABASE ? AS w", (str(work),))
        db.execute("""INSERT INTO queue SELECT source_key,source_sha256,dataset_id,title,creator,'recording','candidate','candidate','now'
            FROM w.queue WHERE source_key IN (%s)""" % ','.join('?'*len(candidates)), list(candidates))
        for key, items in candidates.items():
            for work_id, recording_id, agreement in items:
                db.execute('INSERT INTO work_candidates VALUES (?,?,?,?,?,?)', (key, work_id, recording_id, 'Song',
                           json.dumps(recording_evidence(work_id, recording_id, agreement)), 'candidate'))
    return path


def test_recordings_index_as_third_provider(tmp_path, monkeypatch):
    work, meta, offline = build(tmp_path, monkeypatch)
    subset = tmp_path/'subset.sqlite'
    recordings = recordings_index(tmp_path, work)
    before = [p.read_bytes() for p in (work, meta, offline, subset, recordings)]
    out = tmp_path/'assessment.sqlite'
    prepare(work, meta, out, offline_index=offline, subset=subset, recordings_index=recordings)
    assert [p.read_bytes() for p in (work, meta, offline, subset, recordings)] == before
    found, best = rows(out)
    api, dump = 'musicbrainz', 'musicbrainz_json_dump'
    # Three providers propose the same work: agreement, and the full export row reaches the full tier like an API row.
    one = found['s1', WORK, FULLEXPORT]
    assert one[0] == 'single_work_full_agreement' and one[1]['provider_cross_check'] == 'providers_agree'
    assert one[1]['providers'] == sorted([api, dump, FULLEXPORT]) and one[1]['origin'] == 'recordings_index'
    assert one[1]['writers'] == ['Bach'] and one[1]['title_agreement'] == 'recording_title_normalized'
    assert one[1]['creator_agreement_kind'] == 'normalized_tokens' and one[1]['recording_ids'] == ['r1']
    assert one[1]['namesake_source'] == 'subset' and one[1]['notice_check'] == 'corroborates'
    assert found['s1', WORK, api][1]['provider_cross_check'] == 'providers_agree' and best['s1'] == ('single_work_full_agreement', 1)
    # API against full export disjoint is a conflict.
    three = found['s3', SECOND, FULLEXPORT][1]
    assert three['provider_cross_check'] == 'providers_differ' and three['providers'] == [FULLEXPORT]
    assert found['s3', WORK, api][1]['provider_cross_check'] == 'providers_differ' and best['s3'] == ('conflict', 0)
    # Two providers nest inside the dump superset: overlap, nested, no conflict.
    eleven = found['s11', WORK, FULLEXPORT][1]
    assert eleven['provider_cross_check'] == 'providers_overlap' and eleven['provider_sets_nested'] is True
    assert eleven['providers'] == sorted([api, dump, FULLEXPORT]) and best['s11'] == ('multiple_works', 6)
    # A full export only source with two recordings of one work collapses into one weaker assessment.
    twelve = found['s12', WORK, FULLEXPORT]
    assert twelve[0] == 'single_work_weaker_agreement' and twelve[1]['provider_cross_check'] == 'single_provider'
    assert twelve[1]['creator_agreement_kind'] == 'initials_candidate' and twelve[1]['recording_ids'] == ['r4', 'r5']
    assert [k for k in found if k[0] == 's12'] == [('s12', WORK, FULLEXPORT)] and best['s12'] == ('single_work_weaker_agreement', 4)
    with sqlite3.connect(out) as db:
        inputs = json.loads(db.execute('SELECT inputs_json FROM provenance').fetchone()[0])
        assert inputs['recordings_index'] == dict(path=str(recordings), sha256=file_digest(recordings))
        assert set(inputs) == {'work_index', 'metadata', 'offline_index', 'subset', 'recordings_index'}
        assert json.loads(db.execute("SELECT providers_json FROM source_summary WHERE source_key='s1'").fetchone()[0]) == \
            sorted([api, dump, FULLEXPORT])
        assert 'creator agrees by initials only' in json.loads(
            db.execute("SELECT reasons_json FROM source_summary WHERE source_key='s12'").fetchone()[0])
    counts = summary(out)
    assert counts['providers'] == {api: 11, dump: 5, FULLEXPORT: 4} and counts['sources'] == 12
    assert counts['provider_cross_check']['providers_differ'] == 4  # s8 API and dump, s3 API and full export


def test_three_providers_differ_when_one_pair_is_disjoint(tmp_path, monkeypatch):
    work, meta, offline = build(tmp_path, monkeypatch)
    # s11: API {WORK}, dump {WORK, SECOND}, full export {SECOND}: API and full export are disjoint.
    recordings = recordings_index(tmp_path, work, {'s11': [(SECOND, 'r1', 'normalized_tokens')]})
    out = tmp_path/'a.sqlite'; prepare(work, meta, out, offline_index=offline, recordings_index=recordings)
    found, best = rows(out)
    assert {s['provider_cross_check'] for (k, _, _), (_, s) in found.items() if k == 's11'} == {'providers_differ'}
    assert best['s11'] == ('conflict', 0)


def test_recordings_index_binding_and_provider_origin(tmp_path, monkeypatch):
    work, meta, offline = build(tmp_path, monkeypatch)
    recordings = recordings_index(tmp_path, work)
    with sqlite3.connect(recordings) as db:
        db.execute("UPDATE queue SET source_sha256='other' WHERE source_key='s12'")
    with pytest.raises(ValueError, match='binding'):
        prepare(work, meta, tmp_path/'a.sqlite', recordings_index=recordings)
    with sqlite3.connect(recordings) as db:
        db.execute("UPDATE queue SET source_sha256='sha-s12' WHERE source_key='s12'")
        db.execute("UPDATE work_candidates SET evidence_json=json_set(evidence_json,'$.provider','musicbrainz_json_dump')")
    with pytest.raises(ValueError, match='both candidate indexes'):
        prepare(work, meta, tmp_path/'b.sqlite', offline_index=offline, recordings_index=recordings)
    with sqlite3.connect(recordings) as db:
        db.execute("UPDATE work_candidates SET evidence_json=json_set(evidence_json,'$.match_basis.source_identity_verified',json('true'))")
    with pytest.raises(ValueError, match='unverified'):
        prepare(work, meta, tmp_path/'c.sqlite', recordings_index=recordings)
    assert not list(tmp_path.glob('[abc].sqlite'))


def test_packet_checks_recordings_index(tmp_path, monkeypatch):
    work, meta, _ = build(tmp_path, monkeypatch)
    recordings = recordings_index(tmp_path, work)
    out = tmp_path/'a.sqlite'; prepare(work, meta, out, recordings_index=recordings)
    target = tmp_path/'packet.json'
    packet(out, work, target, recordings_index=recordings, tier='conflict')
    document = json.loads(target.read_text())
    s3 = next(s for s in document['sources'] if s['source_key'] == 's3')
    assert {c['provider'] for c in s3['candidates']} == {'musicbrainz', FULLEXPORT}
    with sqlite3.connect(recordings) as db:
        db.execute("UPDATE queue SET title='Changed' WHERE source_key='s1'")
    with pytest.raises(ValueError, match='recordings_index does not match'):
        packet(out, work, tmp_path/'bad.json', recordings_index=recordings)
    plain = tmp_path/'plain.sqlite'; prepare(work, meta, plain)
    with pytest.raises(ValueError, match='recordings_index does not match'):
        packet(plain, work, tmp_path/'bad.json', recordings_index=recordings)
    assert not (tmp_path/'bad.json').exists()


def test_cli_recordings_index_flag(tmp_path, monkeypatch, capsys):
    args = parser().parse_args(['prepare', '--work-index', 'w', '--metadata', 'm', '--output', 'o', '--recordings-index', 'r'])
    assert str(args.recordings_index) == 'r' and args.offline_index is None
    args = parser().parse_args(['packet', '--assessment', 'a', '--work-index', 'w', '--output', 'o', '--recordings-index', 'r'])
    assert str(args.recordings_index) == 'r'
    work, meta, _ = build(tmp_path, monkeypatch)
    recordings = recordings_index(tmp_path, work)
    out = tmp_path/'a.sqlite'
    main(['prepare', '--work-index', str(work), '--metadata', str(meta), '--output', str(out),
          '--recordings-index', str(recordings)])
    assert json.loads(capsys.readouterr().out)['assessments'] == 15
    main(['summary', '--assessment', str(out)])
    assert json.loads(capsys.readouterr().out)['providers'] == {'musicbrainz': 11, FULLEXPORT: 4}


CATALOGUE_BASIS = dict(title_agreement='catalogue_number_attribute', creator_agreement='composer_identity',
    catalogue_key='op27no2', catalogue_key_specific=True, key_agreement='agrees', title_namesake_count=1)


def catalogue_evidence(work_id, change):
    """Evidence in the shape written by work_identity_offline_catalogue.match, with the match basis changed by `change`."""
    basis = dict(CATALOGUE_BASIS, source_identity_verified=False)
    basis.update(change)
    work = dict(gid=work_id, title='Sonata', type=17, relations=[dict(type='composer', artist=dict(id='c1', name='Ludwig van Beethoven'))])
    return dict(provider=CATALOGUE, policy=woc.POLICY, match_basis=basis, work=work, **woc.UNVERIFIED)


def catalogue_index(tmp_path, work, candidates):
    """Catalogue sidecar with the queue rows of the work index. Candidates map a source key to (work id, basis changes)."""
    path = tmp_path/'catalogue.sqlite'
    with sqlite3.connect(path) as db:
        db.executescript(woc.SCHEMA)
        db.execute("ATTACH DATABASE ? AS w", (str(work),))
        db.execute("""INSERT INTO queue SELECT source_key,source_sha256,dataset_id,title,creator,'work','candidate','candidate','now'
            FROM w.queue WHERE source_key IN (%s)""" % ','.join('?'*len(candidates)), list(candidates))
        for key, items in candidates.items():
            for work_id, change in items:
                db.execute('INSERT INTO work_candidates VALUES (?,?,?,?,?,?)', (key, work_id, '', 'Sonata',
                           json.dumps(catalogue_evidence(work_id, change)), 'candidate'))
    return path


def test_catalogue_index_as_fourth_provider(tmp_path, monkeypatch):
    work, meta, offline = build(tmp_path, monkeypatch)
    subset = tmp_path/'subset.sqlite'
    catalogue = catalogue_index(tmp_path, work, {'s1': [(WORK, {})], 's12': [(WORK, {})]})
    before = [p.read_bytes() for p in (work, meta, offline, subset, catalogue)]
    out = tmp_path/'assessment.sqlite'
    prepare(work, meta, out, offline_index=offline, subset=subset, catalogue_index=catalogue)
    assert [p.read_bytes() for p in (work, meta, offline, subset, catalogue)] == before
    found, best = rows(out)
    api, dump = 'musicbrainz', 'musicbrainz_json_dump'
    # Attribute form, composer identity, a specific key that agrees and one namesake reach the full tier.
    one = found['s12', WORK, CATALOGUE]
    assert one[0] == 'single_work_full_agreement' and best['s12'] == ('single_work_full_agreement', 2)
    assert one[1]['origin'] == 'catalogue_index' and one[1]['providers'] == [CATALOGUE]
    assert one[1]['title_agreement'] == 'catalogue_number_attribute' and one[1]['creator_agreement_kind'] == 'composer_identity'
    assert one[1]['key_agreement'] == 'agrees' and one[1]['catalogue_key'] == 'op27no2' and one[1]['catalogue_key_specific'] is True
    assert one[1]['namesake_count'] == 1 and one[1]['namesake_source'] == 'evidence' and one[1]['recording_ids'] == []
    # Four providers agree on the work of s1 and the catalogue row keeps the tier.
    agree = found['s1', WORK, CATALOGUE][1]
    assert agree['provider_cross_check'] == 'providers_agree' and agree['providers'] == sorted([api, dump, CATALOGUE])
    assert best['s1'] == ('single_work_full_agreement', 1) and summary(out)['providers'][CATALOGUE] == 2
    with sqlite3.connect(out) as db:
        inputs = json.loads(db.execute('SELECT inputs_json FROM provenance').fetchone()[0])
        assert inputs['catalogue_index'] == dict(path=str(catalogue), sha256=file_digest(catalogue))
        assert set(inputs) == {'work_index', 'metadata', 'offline_index', 'subset', 'catalogue_index'}


@pytest.mark.parametrize('change,reason', [
    (dict(key_agreement='disagrees'), 'work key differs from the title key'),
    (dict(catalogue_key='op27', catalogue_key_specific=False), 'catalogue number is a bare opus without a number inside the opus'),
    (dict(title_agreement='catalogue_number_title', form_agreement='disagrees'), 'work form differs from the title form'),
    (dict(title_agreement='nickname_quoted', catalogue_key_specific=False), 'title agrees through a quoted nickname only'),
    (dict(creator_agreement='composer_name_single_namesake'), 'composer identified by name with a single namesake')])
def test_catalogue_candidate_stays_weaker(tmp_path, monkeypatch, change, reason):
    work, meta, _ = build(tmp_path, monkeypatch)
    catalogue = catalogue_index(tmp_path, work, {'s12': [(WORK, change)]})
    out = tmp_path/'a.sqlite'; prepare(work, meta, out, catalogue_index=catalogue)
    found, best = rows(out)
    assert found['s12', WORK, CATALOGUE][0] == 'single_work_weaker_agreement' and best['s12'] == ('single_work_weaker_agreement', 4)
    with sqlite3.connect(out) as db:
        assert reason in json.loads(db.execute("SELECT reasons_json FROM source_summary WHERE source_key='s12'").fetchone()[0])


def test_surname_subset_stays_weaker(tmp_path, monkeypatch):
    work, meta, _ = build(tmp_path, monkeypatch)
    subset = tmp_path/'subset.sqlite'
    recordings = recordings_index(tmp_path, work, {'s12': [(WORK, 'r9', 'surname_subset')]})
    out = tmp_path/'a.sqlite'; prepare(work, meta, out, subset=subset, recordings_index=recordings)
    found, best = rows(out)
    tier, signals = found['s12', WORK, FULLEXPORT]
    assert tier == 'single_work_weaker_agreement' and signals['creator_agreement_kind'] == 'surname_subset'
    assert best['s12'] == ('single_work_weaker_agreement', 4)
    with sqlite3.connect(out) as db:
        assert 'creator agrees by surname only (single artist credit)' in json.loads(
            db.execute("SELECT reasons_json FROM source_summary WHERE source_key='s12'").fetchone()[0])
    # Control: the same row with a full credit agreement reaches the full tier, so the creator kind is the only difference.
    control = tmp_path/'control'; control.mkdir()
    full = recordings_index(control, work, {'s12': [(WORK, 'r9', 'normalized_tokens')]})
    prepare(work, meta, control/'a.sqlite', subset=subset, recordings_index=full)
    assert rows(control/'a.sqlite')[1]['s12'] == ('single_work_full_agreement', 2)


@pytest.mark.parametrize('value,kind', [
    ('composer_identity', 'composer_identity'), ('surname_subset', 'surname_subset'), ('unknown_kind', None), (None, None),
    ([dict(agreement='initials_candidate'), dict(agreement='composer_identity')], 'composer_identity')])
def test_creator_kind_follows_strength_order(value, kind):
    assert creator_kind(value) == kind


def test_catalogue_binding_and_provider_origin(tmp_path, monkeypatch):
    work, meta, _ = build(tmp_path, monkeypatch)
    catalogue = catalogue_index(tmp_path, work, {'s12': [(WORK, {})]})
    with sqlite3.connect(catalogue) as db:
        db.execute("UPDATE queue SET source_sha256='other' WHERE source_key='s12'")
    with pytest.raises(ValueError, match='binding'):
        prepare(work, meta, tmp_path/'a.sqlite', catalogue_index=catalogue)
    with sqlite3.connect(catalogue) as db:
        db.execute("UPDATE queue SET source_sha256='sha-s12' WHERE source_key='s12'")
        db.execute("UPDATE work_candidates SET evidence_json=json_set(evidence_json,'$.provider','musicbrainz')")
    with pytest.raises(ValueError, match='both candidate indexes'):
        prepare(work, meta, tmp_path/'b.sqlite', catalogue_index=catalogue)
    with sqlite3.connect(catalogue) as db:
        db.execute("UPDATE work_candidates SET evidence_json=json_set(evidence_json,'$.provider',?,'$.match_basis.source_identity_verified',json('true'))",
                   (CATALOGUE,))
    with pytest.raises(ValueError, match='unverified'):
        prepare(work, meta, tmp_path/'c.sqlite', catalogue_index=catalogue)
    assert not list(tmp_path.glob('[abc].sqlite'))


def test_packet_checks_catalogue_index(tmp_path, monkeypatch):
    work, meta, _ = build(tmp_path, monkeypatch)
    catalogue = catalogue_index(tmp_path, work, {'s12': [(WORK, {})]})
    out = tmp_path/'a.sqlite'; prepare(work, meta, out, catalogue_index=catalogue)
    target = tmp_path/'packet.json'
    packet(out, work, target, catalogue_index=catalogue)
    assert [c['work_id'] for s in json.loads(target.read_text())['sources'] for c in s['candidates'] if c['provider'] == CATALOGUE] == [WORK]
    with sqlite3.connect(catalogue) as db:
        db.execute("UPDATE queue SET title='Changed' WHERE source_key='s12'")
    with pytest.raises(ValueError, match='catalogue_index does not match'):
        packet(out, work, tmp_path/'bad.json', catalogue_index=catalogue)
    plain = tmp_path/'plain.sqlite'; prepare(work, meta, plain)
    with pytest.raises(ValueError, match='catalogue_index does not match'):
        packet(plain, work, tmp_path/'bad.json', catalogue_index=catalogue)
    assert not (tmp_path/'bad.json').exists()


def test_cli_catalogue_index_flag(tmp_path, monkeypatch, capsys):
    args = parser().parse_args(['prepare', '--work-index', 'w', '--metadata', 'm', '--output', 'o', '--catalogue-index', 'c'])
    assert str(args.catalogue_index) == 'c' and args.recordings_index is None
    args = parser().parse_args(['packet', '--assessment', 'a', '--work-index', 'w', '--output', 'o', '--catalogue-index', 'c'])
    assert str(args.catalogue_index) == 'c'
    work, meta, _ = build(tmp_path, monkeypatch)
    catalogue = catalogue_index(tmp_path, work, {'s12': [(WORK, {})]})
    out = tmp_path/'a.sqlite'
    main(['prepare', '--work-index', str(work), '--metadata', str(meta), '--output', str(out), '--catalogue-index', str(catalogue)])
    assert json.loads(capsys.readouterr().out)['assessments'] == 12  # Eleven API rows from the fixture and one catalogue row.
    main(['summary', '--assessment', str(out)])
    assert json.loads(capsys.readouterr().out)['providers'] == {'musicbrainz': 11, CATALOGUE: 1}
    target = tmp_path/'packet.json'
    main(['packet', '--assessment', str(out), '--work-index', str(work), '--output', str(target), '--catalogue-index', str(catalogue)])
    assert [c['work_id'] for s in json.loads(target.read_text())['sources'] for c in s['candidates'] if c['provider'] == CATALOGUE] == [WORK]


def test_related_part_counts_as_the_catalogue_work(tmp_path, monkeypatch):
    """A dump candidate for the first movement and a catalogue candidate for the sonata that lists that movement
    among its related works are one work: no conflict, one distinct work, both rows reach the full tier."""
    work, meta, offline = build(tmp_path, monkeypatch)
    subset = tmp_path/'subset.sqlite'
    movement = SECOND  # s8 has the offline dump candidate SECOND and the API candidate WORK
    catalogue = catalogue_index(tmp_path, work, {'s8': [(THIRD, dict(related_work_ids=[movement, WORK]))]})
    out = tmp_path/'assessment.sqlite'
    prepare(work, meta, out, offline_index=offline, subset=subset, catalogue_index=catalogue)
    found, best = rows(out)
    assert best['s8'][0] == 'single_work_full_agreement'
    parent = found['s8', THIRD, CATALOGUE][1]
    assert parent['canonical_work'] is None and parent['distinct_works_all_providers'] == 1
    assert parent['provider_cross_check'] == 'providers_agree' and parent['providers'] == sorted(['musicbrainz', 'musicbrainz_json_dump', CATALOGUE])
    part = found['s8', movement, 'musicbrainz_json_dump'][1]
    assert part['canonical_work'] == THIRD and part['tier'] == 'single_work_full_agreement'
    assert 'candidate is a part or version of another candidate work and counts as that work' in json.loads(
        sqlite3.connect(out).execute("SELECT reasons_json FROM source_summary WHERE source_key='s8'").fetchone()[0])
