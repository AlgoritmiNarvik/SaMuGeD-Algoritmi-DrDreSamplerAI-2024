import csv
import gzip
import json
import sqlite3

import pytest

from samuged.dataset import file_digest
from samuged.identity_quality import prepare, export, risk_flags
from samuged.track_metadata import prepare as audit, FIELDS
from samuged.work_identity import phrase_evidence, search_candidates


def fixture(tmp_path, monkeypatch):
    from test_work_identity import setup
    meta, catalog, work = setup(tmp_path, monkeypatch)
    csv_path = tmp_path/'pdmx.csv'
    with csv_path.open('w', newline='') as stream:
        csv.DictWriter(stream, fieldnames=['mid', *FIELDS]).writeheader()
    audited = tmp_path/'audit.sqlite'
    audit(meta, catalog, csv_path, work, audited)
    return meta, catalog, audited


def test_risks_expose_ambiguous_labels_without_identity_claim():
    risks = risk_flags('Untitled 2', 'J. S. Bach', creator_basis='upstream_artist_role_unverified',
        title_creators=2, query_forms=2)
    assert set(risks) == {'identity_title_generic', 'identity_creator_initials',
        'identity_creator_hint_unverified', 'identity_title_multiple_creators',
        'identity_normalization_collision'}
    assert 'identity_creator_missing' in risk_flags('Song', None, creator_basis='unresolved')


def test_complete_quality_search_export_and_phrase_inheritance(tmp_path, monkeypatch):
    meta, catalog, audited = fixture(tmp_path, monkeypatch)
    # Catalog binding stays unchanged; search labels are independent, unverified hints.
    with sqlite3.connect(audited) as db:
        db.execute("UPDATE queue SET title='Frédéric song',creator='J. S. Bach'")
    before = file_digest(audited)
    output = tmp_path/'quality.sqlite'
    receipt = prepare(audited, meta, catalog, output)
    assert receipt['sources'] == 1 and file_digest(audited) == before
    rows = search_candidates(output, text='Frederic', risk='identity_creator_initials')
    assert len(rows) == 1
    evidence = rows[0]['identity_quality']
    assert evidence['source_path'] and evidence['overall_clearance_status'] == 'not_established'
    assert search_candidates(output, risk='unknown') == []
    inherited = phrase_evidence(catalog, meta, output)[0]
    assert inherited['identity_quality'] == evidence and inherited['work_id'] is None
    zipped = tmp_path/'portable.gz'
    assert export(output, zipped)['sources'] == 1
    with gzip.open(zipped, 'rt') as stream:
        portable = json.loads(stream.readline())
    assert portable['identity_quality'] == evidence
    assert portable['identity_reviews'] == portable['rights_observations'] == []
    with pytest.raises(FileExistsError):prepare(audited, meta, catalog, output)
    with pytest.raises(ValueError, match='quality audit'):search_candidates(audited, risk='anything')


def test_changed_source_hash_rejects_join(tmp_path, monkeypatch):
    meta, catalog, audited = fixture(tmp_path, monkeypatch)
    with sqlite3.connect(audited) as db:
        db.execute("UPDATE queue SET source_sha256='different'")
    output = tmp_path/'bad.sqlite'
    with pytest.raises(ValueError, match='source binding'):prepare(audited, meta, catalog, output)
    assert not output.exists()


def test_same_title_different_creators_and_normalization_collisions(tmp_path, monkeypatch):
    meta, catalog, audited = fixture(tmp_path, monkeypatch)
    def duplicate(db, table, key):
        names = [x[1] for x in db.execute('PRAGMA table_info('+table+')')]
        values = list(db.execute('SELECT * FROM '+table+' LIMIT 1').fetchone())
        values[names.index('source_key')] = key
        db.execute('INSERT INTO '+table+' VALUES ('+','.join('?' for _ in values)+')', values)
    with sqlite3.connect(catalog) as db:
        duplicate(db, 'sources', 'second'); duplicate(db, 'sources', 'third')
    with sqlite3.connect(meta) as db:
        for key in ('second', 'third'):
            duplicate(db, 'records', key); duplicate(db, 'source_rights', key)
        db.execute('UPDATE provenance SET catalog_sha256=?', (file_digest(catalog),))
    with sqlite3.connect(audited) as db:
        for key in ('second', 'third'):
            duplicate(db, 'queue', key); duplicate(db, 'track_metadata', key)
        db.execute('UPDATE provenance SET metadata_sha256=?', (file_digest(meta),))
        db.execute("UPDATE queue SET title='Été',creator='Writer Name'")
        db.execute("UPDATE queue SET title='Ete' WHERE source_key='second'")
        db.execute("UPDATE queue SET creator='Different Writer' WHERE source_key='third'")
    output = tmp_path/'collisions.sqlite'
    result = prepare(audited, meta, catalog, output)
    assert result['risks']['identity_title_multiple_creators'] == 3
    assert result['risks']['identity_normalization_collision'] == 2
    assert len(search_candidates(output, risk='identity_normalization_collision')) == 2
    assert all(x['work_id'] is None for x in search_candidates(output, text='Ete'))


def test_full_creator_search_ignores_accents_and_word_order(tmp_path, monkeypatch):
    meta, catalog, audited = fixture(tmp_path, monkeypatch)
    with sqlite3.connect(audited) as db:
        db.execute("UPDATE queue SET creator='Frédéric Chopin'")
    output = tmp_path/'accent.sqlite'
    prepare(audited, meta, catalog, output)
    assert len(search_candidates(output, text='Frederic Chopin')) == 1
    assert len(search_candidates(output, text='Chopin Frederic')) == 1
    assert search_candidates(output, text="' OR 1=1 --") == []
