import gzip
import json
import sqlite3

import pytest

from samuged import work_identity_merge as wim
from samuged.dataset import file_digest
from samuged.work_identity_offline import SCHEMA as WORKS_SCHEMA
from samuged.work_identity_offline_recordings import SCHEMA as RECORDINGS_SCHEMA

API_SCHEMA = '''
CREATE TABLE queue(source_key TEXT PRIMARY KEY, source_sha256 TEXT, dataset_id TEXT, title TEXT, creator TEXT,
    query_kind TEXT, status TEXT, error TEXT, updated_on TEXT);
CREATE TABLE work_candidates(source_key TEXT REFERENCES queue, work_id TEXT, recording_id TEXT, title TEXT,
    evidence_json TEXT, match_status TEXT CHECK(match_status='candidate'), PRIMARY KEY(source_key,work_id,recording_id));
'''
ASSESSMENT_SCHEMA = '''
CREATE TABLE provenance(policy TEXT, inputs_json TEXT, created_on TEXT,
    identity_verified INTEGER CHECK(identity_verified=0), rights_clearance TEXT CHECK(rights_clearance='not_established'));
CREATE TABLE assessments(source_key TEXT, work_id TEXT, provider TEXT, tier TEXT, signals_json TEXT,
    policy TEXT, assessed_on TEXT, PRIMARY KEY(source_key,work_id,provider));
CREATE TABLE source_summary(source_key TEXT PRIMARY KEY, dataset_id TEXT, best_tier TEXT,
    distinct_works INTEGER, providers_json TEXT, review_priority INTEGER, reasons_json TEXT,
    identity_status TEXT CHECK(identity_status='unverified_assessment_only'),
    rights_clearance TEXT CHECK(rights_clearance='not_established'));
'''
W1, W2, W3 = 'work-1', 'work-2', 'work-3'


def api_evidence(work_id, title, writers, iswcs=()):
    return dict(provider='musicbrainz', policy='work-candidates-v3',
        match_basis=dict(title_agreement='recording_title_normalized', creator_agreement='normalized_tokens',
                         source_identity_verified=False),
        work=dict(id=work_id, title=title, iswcs=list(iswcs),
                  relations=[dict(type=r, artist=dict(id=i, name=n)) for r, i, n in writers]))


def dump_evidence(work_id, title, writers):
    return dict(provider='musicbrainz_json_dump', policy='work-candidates-v3-dump',
        match_basis=dict(title_agreement='alias_normalized',
                         creator_agreement=[dict(name=writers[0][2], role='composer', agreement='initials_candidate')],
                         source_identity_verified=False),
        work=dict(id=work_id, title=title, iswcs=['T-1'],
                  artist_relations=[dict(type=r, artist=dict(id=i, name=n)) for r, i, n in writers]
                  + [dict(type='performer', artist=dict(id='p', name='Performer'))]))


def recording_evidence(work_id, title, writers):
    return dict(provider='musicbrainz_fullexport', policy='work-candidates-v3-fullexport',
        match_basis=dict(title_agreement='recording_title_normalized', creator_agreement='normalized_tokens',
                         source_identity_verified=False),
        work=dict(gid=work_id, title=title, type=17,
                  relations=[dict(type=r, artist=dict(id=i, name=n)) for r, i, n in writers]),
        identity_verified=False, rights_clearance='not_established')


def default_sources():
    """(key, sha, dataset, title, creator, query_kind, api_status)."""
    return [('k1', 'h1', 'lakh', 'Song', 'Band', 'recording', 'candidate'),
            ('k2', 'h2', 'pdmx', 'Air', 'Composer', 'work', 'pending'),
            ('k3', 'h3', 'maestro', None, None, 'work', 'missing_labels'),
            ('k4', 'h4', 'lakh', 'Other', 'Band', 'recording', 'no_candidate')]


def make_indexes(root, sources=None, *, candidates=True):
    """Build tiny API, dump works, dump recordings and assessment indexes with their real table shapes."""
    sources = sources or default_sources()
    paths = dict(work_index=root/'work_identity_v05.sqlite', offline_index=root/'offline.sqlite',
                 recordings_index=root/'recordings.sqlite', assessment=root/'assessment.sqlite')
    with sqlite3.connect(paths['work_index']) as db:
        db.executescript(API_SCHEMA)
        db.executemany('INSERT INTO queue VALUES (?,?,?,?,?,?,?,NULL,?)', [(*s, 'now') for s in sources])
        if candidates:
            db.execute('INSERT INTO work_candidates VALUES (?,?,?,?,?,?)', (sources[0][0], W1, 'rec-api', 'Song',
                json.dumps(api_evidence(W1, 'Song', [('composer', 'a1', 'Ann Writer')], ['T-9'])), 'candidate'))
    with sqlite3.connect(paths['offline_index']) as db:
        db.executescript(WORKS_SCHEMA)
        status = {'candidate': 'no_candidate', 'pending': 'candidate', 'missing_labels': 'missing_labels',
                  'no_candidate': 'no_namesake'}
        db.executemany('INSERT INTO queue VALUES (?,?,?,?,?,?,?,NULL,?)',
                       [(k, h, d, t, c, q, status[s] if candidates else 'no_candidate', 'now') for k, h, d, t, c, q, s in sources])
        if candidates:
            db.execute('INSERT INTO work_candidates VALUES (?,?,?,?,?,?)', (sources[1][0], W3, None, 'Air',
                json.dumps(dump_evidence(W3, 'Air', [('composer', 'a3', 'J. S. Bach')])), 'candidate'))
    with sqlite3.connect(paths['recordings_index']) as db:
        db.executescript(RECORDINGS_SCHEMA)
        for k, h, d, t, c, q, s in sources:
            if q == 'recording':
                state = ('candidate', 'candidate') if candidates and k == sources[0][0] else ('no_candidate', 'no_recording_with_title')
                db.execute('INSERT INTO queue VALUES (?,?,?,?,?,?,?,?,?)', (k, h, d, t, c, q, *state, 'now'))
        if candidates:
            for work, rec, writers in ((W1, 'rec-1', [('composer', 'a1', 'Ann Writer'), ('lyricist', 'a2', 'Bo Lyric')]),
                                       (W1, 'rec-2', [('composer', 'a1', 'Ann Writer')]), (W2, 'rec-3', [])):
                db.execute('INSERT INTO work_candidates VALUES (?,?,?,?,?,?)', (sources[0][0], work, rec, 'Song',
                    json.dumps(recording_evidence(work, 'Song (recording)', writers)), 'candidate'))
    with sqlite3.connect(paths['assessment']) as db:
        db.executescript(ASSESSMENT_SCHEMA)
        if candidates:
            key = sources[0][0]
            db.executemany('INSERT INTO assessments VALUES (?,?,?,?,?,?,?)', [
                (key, W1, 'musicbrainz', 'single_work_full_agreement', '{}', 'candidate-assessment-v1', 'now'),
                (key, W1, 'musicbrainz_fullexport', 'multiple_works', '{}', 'candidate-assessment-v1', 'now'),
                (key, W2, 'musicbrainz_fullexport', 'multiple_works', '{}', 'candidate-assessment-v1', 'now')])
            db.execute('INSERT INTO source_summary VALUES (?,?,?,?,?,?,?,?,?)', (key, 'lakh', 'multiple_works', 2,
                '["musicbrainz","musicbrainz_fullexport"]', 4, '["2 distinct work candidates"]',
                'unverified_assessment_only', 'not_established'))
    paths['metadata'] = root/'usage_metadata.jsonl.gz'
    with gzip.open(paths['metadata'], 'wt') as stream:
        for s in sources:
            stream.write(json.dumps(dict(source_key=s[0], source_sha256=s[1]))+'\n')
    return paths


def run(tmp_path, **changes):
    paths = make_indexes(tmp_path, **changes)
    out = tmp_path/'work_identity_v06.jsonl.gz'
    receipt = wim.prepare(paths['work_index'], paths['offline_index'], paths['recordings_index'], paths['assessment'],
                          out, metadata=paths['metadata'])
    rows = [json.loads(line) for line in gzip.open(out, 'rt')]
    return paths, out, receipt, rows


def test_merge_row_shape_and_candidates(tmp_path):
    paths, out, receipt, rows = run(tmp_path)
    assert [r['source_key'] for r in rows] == ['k1', 'k2', 'k3', 'k4']
    assert all(tuple(r) == wim.FIELDS for r in rows)
    one = rows[0]
    assert (one['api_status'], one['dump_works_status'], one['dump_recordings_status'], one['dump_recordings_reason']) == \
        ('candidate', 'no_candidate', 'candidate', 'candidate')
    assert [c['work_id'] for c in one['candidates']] == [W1, W2]
    first = one['candidates'][0]
    assert tuple(first) == wim.CANDIDATE_FIELDS
    assert first['providers'] == ['musicbrainz', 'musicbrainz_fullexport']
    assert first['work_title'] == 'Song (recording)' and first['iswcs'] == ['T-9']
    assert first['writers'] == [dict(role='composer', artist_id='a1', name='Ann Writer'),
                                dict(role='lyricist', artist_id='a2', name='Bo Lyric')]
    assert first['best_tier'] == 'single_work_full_agreement'  # best across providers
    assert (first['title_agreement'], first['creator_agreement']) == ('recording_title_normalized', 'normalized_tokens')
    assert one['candidates'][1]['best_tier'] == 'multiple_works' and one['candidates'][1]['writers'] == []
    assert (one['best_tier'], one['review_priority'], one['assessment_reasons']) == ('multiple_works', 4, ['2 distinct work candidates'])
    assert one['identity_status'] == 'candidate_unverified' and one['rights_clearance'] == 'not_established'
    dump = rows[1]['candidates'][0]
    assert dump['providers'] == ['musicbrainz_json_dump'] and dump['best_tier'] is None
    assert dump['writers'] == [dict(role='composer', artist_id='a3', name='J. S. Bach')]  # the performer is not a writer
    assert (dump['title_agreement'], dump['creator_agreement']) == ('alias_normalized', 'initials_candidate')
    assert rows[1]['dump_recordings_status'] is None and rows[1]['api_status'] == 'pending'
    empty = rows[2]
    assert empty['candidates'] == [] and empty['identity_status'] == 'unresolved' and empty['best_tier'] is None
    assert empty['assessment_reasons'] == [] and empty['policy'] == 'work-identity-merge-v1'


def test_receipt_and_status_counts(tmp_path):
    paths, out, receipt, rows = run(tmp_path)
    stored = json.loads(wim.receipt_path(out).read_text())
    assert stored['rows'] == 4 and stored['candidates'] == 3
    assert stored['counts']['api_status'] == {'candidate': 1, 'missing_labels': 1, 'no_candidate': 1, 'pending': 1}
    assert stored['counts']['dump_recordings_status'] == {'None': 2, 'candidate': 1, 'no_candidate': 1}
    assert stored['counts']['identity_status'] == {'candidate_unverified': 2, 'unresolved': 2}
    assert stored['counts']['candidate_providers'] == {'musicbrainz+musicbrainz_fullexport': 1,
                                                       'musicbrainz_fullexport': 1, 'musicbrainz_json_dump': 1}
    assert set(stored['inputs']) == {'work_index', 'offline_index', 'recordings_index', 'assessment', 'metadata'}
    assert stored['inputs']['assessment']['sha256'] == file_digest(paths['assessment'])
    assert stored['output_sha256'] == file_digest(out)
    assert stored['identity_verified'] is False and stored['rights_clearance'] == 'not_established'
    result = wim.status(out)
    assert result['receipt_matches'] is True and result['counts'] == stored['counts']


def test_inputs_are_not_written_and_output_is_not_replaced(tmp_path):
    paths = make_indexes(tmp_path)
    before = {k: file_digest(p) for k, p in paths.items()}
    out = tmp_path/'export.jsonl.gz'
    wim.prepare(*(paths[k] for k in ('work_index', 'offline_index', 'recordings_index', 'assessment')), out,
                metadata=paths['metadata'])
    assert {k: file_digest(p) for k, p in paths.items()} == before
    with pytest.raises(FileExistsError):
        wim.prepare(*(paths[k] for k in ('work_index', 'offline_index', 'recordings_index', 'assessment')), out,
                    metadata=paths['metadata'])


def test_source_hash_mismatch_stops_without_output(tmp_path):
    paths = make_indexes(tmp_path)
    with sqlite3.connect(paths['recordings_index']) as db:
        db.execute("UPDATE queue SET source_sha256='other' WHERE source_key='k1'")
    out = tmp_path/'export.jsonl.gz'
    with pytest.raises(ValueError, match='dump recordings source hash'):
        wim.prepare(*(paths[k] for k in ('work_index', 'offline_index', 'recordings_index', 'assessment')), out,
                    metadata=paths['metadata'])
    assert not out.exists() and not wim.receipt_path(out).exists()


def test_metadata_must_cover_the_queue(tmp_path):
    paths = make_indexes(tmp_path)
    with gzip.open(paths['metadata'], 'wt') as stream:
        stream.write(json.dumps(dict(source_key='k1', source_sha256='h1'))+'\n')
    with pytest.raises(ValueError, match='metadata source hash'):
        wim.prepare(*(paths[k] for k in ('work_index', 'offline_index', 'recordings_index', 'assessment')),
                    tmp_path/'export.jsonl.gz', metadata=paths['metadata'])


def test_verified_candidate_is_refused(tmp_path):
    paths = make_indexes(tmp_path)
    with sqlite3.connect(paths['offline_index']) as db:
        evidence = dump_evidence(W3, 'Air', [('composer', 'a3', 'Bach')])
        evidence['match_basis']['source_identity_verified'] = True
        db.execute('UPDATE work_candidates SET evidence_json=?', (json.dumps(evidence),))
    with pytest.raises(ValueError, match='unverified'):
        wim.prepare(*(paths[k] for k in ('work_index', 'offline_index', 'recordings_index', 'assessment')),
                    tmp_path/'export.jsonl.gz', metadata=paths['metadata'])


def test_status_detects_a_changed_export(tmp_path):
    paths, out, receipt, rows = run(tmp_path)
    with gzip.open(out, 'wt') as stream:
        for r in rows[:3]:
            stream.write(json.dumps(r)+'\n')
    assert wim.status(out)['receipt_matches'] is False
