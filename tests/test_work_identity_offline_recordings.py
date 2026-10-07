import gzip
import json
import sqlite3
from collections import namedtuple

import pytest

from samuged import musicbrainz_fullexport as mfe
from samuged import work_identity_offline_recordings as wor
from samuged.dataset import file_digest
from test_musicbrainz_fullexport import a, build_archive, q, r, sums, w, work_index


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr('samuged.musicbrainz_dump.shutil.disk_usage', lambda p: namedtuple('U', 'total used free')(0, 0, 20*1024**3))
    monkeypatch.setattr('samuged.musicbrainz_fullexport.shutil.which', lambda name: None)
    export = tmp_path/'20261007-002147'; export.mkdir()
    build_archive(export/'mbdump.tar.bz2'); sums(export)
    index = tmp_path/'v04.sqlite'
    work_index(index)
    subset = tmp_path/'recordings.sqlite'
    mfe.prepare(export, index, subset)
    return index, subset, tmp_path/'offline_recordings.sqlite'


def candidates(path, key):
    return {(wk, rec): json.loads(e) for wk, rec, e in q(path, 'SELECT work_id,recording_id,evidence_json FROM work_candidates WHERE source_key=?', key)}


def test_candidates_mirror_api_recording_rule(env):
    index, subset, out = env
    before = [file_digest(p) for p in (index, subset)]
    result = wor.prepare(index, subset, out)
    assert [file_digest(p) for p in (index, subset)] == before  # the API index and the subset are never written
    assert result['identity_verified'] is False and result['rights_clearance'] == 'not_established'
    assert {k: (s, x) for k, s, x in q(out, 'SELECT source_key,status,reason FROM queue')} == {
        'L01': ('candidate', 'candidate'), 'L02': ('candidate', 'candidate'), 'L03': ('candidate', 'candidate'),
        'L04': ('no_candidate', 'agreeing_recordings_without_work'), 'L05': ('no_candidate', 'recordings_without_creator_agreement'),
        'L06': ('no_candidate', 'no_recording_with_title'), 'L07': ('missing_labels', 'missing_title'),
        'L08': ('missing_labels', 'title_not_usable'), 'L09': ('missing_labels', 'missing_creator')}
    assert q(out, "SELECT DISTINCT query_kind FROM queue") == [('recording',)]  # the pdmx work row is not processed
    one = candidates(out, 'L01')
    assert set(one) == {(w(1), r(1)), (w(1), r(7)), (w(4), r(7))}  # the disagreeing Back\Slash credit is excluded
    e = one[w(1), r(1)]
    assert (e['provider'], e['policy'], e['metadata_license']) == ('musicbrainz_fullexport', 'work-candidates-v3-fullexport', 'CC0-1.0')
    assert e['metadata_license_url'] == 'https://musicbrainz.org/doc/About/Data_License'
    assert e['method'] == 'normalized_labels_names_or_initials_and_dump_relationship_not_MIDI_identity'
    assert e['dump']['export_name'] == '20261007-002147' and e['dump']['schema_sequence'] == 31 and len(e['dump']['archive_sha256']) == 64
    b = e['match_basis']
    assert b['title_agreement'] == 'recording_title_normalized' and b['creator_agreement'] == 'normalized_tokens'
    assert b['recording'] == dict(gid=r(1), name='Home\tFree', credit='Jerry Goldsmith')
    assert b['credited_artists'] == [dict(name='Jerry Goldsmith', gid=a(1), agreement='normalized_tokens')]
    assert (b['recording_namesake_count'], b['matching_recording_count'], b['linked_work_count']) == (3, 2, 1)
    assert b['matching_recordings_truncated'] is False and b['linked_works_truncated'] is False
    assert b['distinct_work_candidates'] == 2 and b['multiple_work_candidates'] is True
    assert b['musical_comparison'] == 'not_performed' and b['source_identity_verified'] is False
    assert b['source_creator_basis'] == 'catalog_artist' and b['query_title'] == 'Home Free'
    assert e['work']['gid'] == w(1) and e['work']['title'] == 'Home Free'
    assert e['work']['relations'] == [dict(type='composer', artist=dict(id=a(1), name='Jerry Goldsmith'))]  # Other Writer disagrees
    assert (e['musical_work_license_status'], e['rights_holder_status']) == ('unknown', 'not_established')
    assert e['identity_verified'] is False and e['rights_clearance'] == 'not_established'
    initials = candidates(out, 'L02')[w(1), r(1)]['match_basis']
    assert initials['creator_agreement'] == 'initials_candidate' and initials['credited_artists'][0]['agreement'] == 'initials_candidate'
    kiss = candidates(out, 'L03')
    assert set(kiss) == {(w(2), r(3))} and kiss[w(2), r(3)]['work']['relations'] == []  # empty writer list is allowed
    assert q(out, "SELECT * FROM source_matches WHERE source_key='L04'") == [('L04', 1, 1, 0, 0, 0, 0)]
    assert q(out, "SELECT * FROM source_matches WHERE source_key='L05'") == [('L05', 3, 0, 0, 0, 0, 0)]
    assert q(out, "SELECT count(*) FROM source_matches WHERE source_key IN ('L07','L08','L09')") == [(0,)]


def test_multi_artist_credit_records_per_artist_agreement(env):
    index, subset, _ = env
    with sqlite3.connect(subset) as db:
        ref = wor.Reference(db)
        state, reason, rows, source = wor.match(('L04', 'h', 'lakh', 'Lonely Song', 'Paul Stanley', 'usable', None), ref, {})
    assert (state, reason, rows) == ('no_candidate', 'recordings_without_creator_agreement', [])  # a partial credit does not agree
    with sqlite3.connect(subset) as db:  # Give the recording a work to see the per artist evidence.
        db.execute(f"INSERT INTO recording_works VALUES (4,2,'{r(4)}','{w(2)}','performance')")
    with sqlite3.connect(subset) as db:
        state, reason, rows, source = wor.match(('L04', 'h', 'lakh', 'Lonely Song', 'Gene Simmons, Paul Stanley', 'usable', None),
                                               wor.Reference(db), {})
    basis = json.loads(rows[0][4])['match_basis']
    assert basis['creator_agreement'] == 'normalized_tokens' and basis['source_creator_basis'] == 'original_catalog_labels_unverified'
    assert [(x['name'], x['gid'], x['agreement']) for x in basis['credited_artists']] == [
        ('Paul Stanley', a(3), None), ('Gene Simmons', a(4), None)]
    assert json.loads(rows[0][4])['work']['relations'] == []  # each writer is compared with the full creator, as in the API


def test_bounds_are_flagged_and_counted(env, monkeypatch):
    index, subset, out = env
    monkeypatch.setattr(wor, 'RECORDINGS', 1)
    monkeypatch.setattr(wor, 'WORKS', 1)
    wor.prepare(index, subset, out)
    one = candidates(out, 'L01')
    assert set(one) == {(w(1), r(1))}  # lowest recording gid first
    b = one[w(1), r(1)]['match_basis']
    assert b['matching_recordings_truncated'] is True and b['matching_recording_count'] == 2
    assert q(out, "SELECT truncated,recordings_truncated,works_truncated FROM source_matches WHERE source_key='L01'") == [(1, 1, 0)]
    s = wor.status(out)
    assert (s['truncated_sources'], s['recordings_truncated_sources'], s['works_truncated_sources']) == (2, 2, 0)
    out.unlink()
    monkeypatch.setattr(wor, 'RECORDINGS', 50)
    wor.prepare(index, subset, out)
    seven = candidates(out, 'L01')[w(1), r(7)]['match_basis']
    assert seven['linked_work_count'] == 2 and seven['linked_works_truncated'] is True
    assert set(candidates(out, 'L01')) == {(w(1), r(1)), (w(1), r(7))}
    assert q(out, "SELECT recordings_truncated,works_truncated FROM source_matches WHERE source_key='L01'") == [(0, 1)]


def test_status_and_provenance(env):
    index, subset, out = env
    wor.prepare(index, subset, out)
    s = wor.status(out)
    assert s['sources'] == 9 and s['queue_status'] == {'candidate': 3, 'no_candidate': 3, 'missing_labels': 3}
    assert s['reasons']['agreeing_recordings_without_work'] == 1 and s['reasons']['no_recording_with_title'] == 1
    assert (s['work_candidates'], s['candidate_sources'], s['distinct_works'], s['distinct_recordings']) == (7, 3, 3, 3)
    assert s['truncated_sources'] == 0
    inputs, dump, selection, flags = q(out, 'SELECT inputs_json,dump_json,selection_json,identity_verified||rights_clearance FROM provenance')[0]
    assert json.loads(inputs)['work_index']['sha256'] == file_digest(index) and flags == '0not_established'
    assert json.loads(inputs)['subset']['sha256'] == file_digest(subset) and json.loads(dump)['replication_sequence'] == 189552
    assert json.loads(selection) == dict(query_kind='recording', limit=None, truncated=False, sources=9,
                                         max_recordings_per_source=50, max_works_per_recording=20)


def test_limit(env):
    index, subset, out = env
    result = wor.prepare(index, subset, out, limit=2)
    assert q(out, 'SELECT source_key FROM queue') == [('L01',), ('L02',)] and result['selection']['truncated'] is True
    with pytest.raises(ValueError, match='positive'):
        wor.prepare(index, subset, out.with_name('x.sqlite'), limit=0)


def test_refusals(env, tmp_path, monkeypatch):
    index, subset, out = env
    other = tmp_path/'other.sqlite'
    work_index(other, queue=[('L01', 'Home Free', 'Jerry Goldsmith', 'usable')])
    with pytest.raises(ValueError, match='another work index'):
        wor.prepare(other, subset, out)
    export = tmp_path/'20261007-002147'
    small = tmp_path/'small.sqlite'
    mfe.prepare(export, index, small, limit=3)
    with pytest.raises(ValueError, match='truncated'):
        wor.prepare(index, small, out)
    out.write_text('keep')
    with pytest.raises(FileExistsError):
        wor.prepare(index, subset, out)
    assert out.read_text() == 'keep'
    out.unlink()
    monkeypatch.setattr('samuged.work_identity_offline.shutil.disk_usage', lambda p: namedtuple('U', 'total used free')(0, 0, 10*1024**3))
    with pytest.raises(ValueError, match='reserve'):
        wor.prepare(index, subset, out)
    assert not out.exists() and [p.name for p in tmp_path.iterdir() if p.name.startswith('tmp')] == []


def test_export_round_trip(env, tmp_path, monkeypatch):
    index, subset, out = env
    wor.prepare(index, subset, out)
    target = tmp_path/'export.jsonl.gz'
    result = wor.export(out, target)
    assert result['lines'] == 9 and result['identity_verified'] is False
    with gzip.open(target, 'rt', encoding='utf-8') as f:
        lines = {x['source_key']: x for x in map(json.loads, f)}
    one = lines['L01']
    assert one['status'] == 'candidate' and one['dump_name'] == '20261007-002147' and one['policy'] == wor.POLICY
    assert one['matches'] == dict(title_recording_count=3, agreeing_recording_count=2, linked_work_count=3, truncated=False)
    assert {(c['work_id'], c['recording_id']) for c in one['candidates']} == set(candidates(out, 'L01'))
    assert one['candidates'][0]['credit'] == 'Jerry Goldsmith' and one['rights_clearance'] == 'not_established'
    assert lines['L07']['matches'] is None and lines['L07']['reason'] == 'missing_title'
    with pytest.raises(FileExistsError):
        wor.export(out, target)
    monkeypatch.setattr(wor, 'MB', 100)
    with pytest.raises(ValueError, match='max size'):
        wor.export(out, tmp_path/'small.jsonl.gz', max_output_mb=1)
    assert not (tmp_path/'small.jsonl.gz').exists()
