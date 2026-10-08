import hashlib
import json
import shutil
import sqlite3
import sys
from collections import namedtuple
from contextlib import closing

import pytest

from samuged import work_identity_offline as wio
from samuged import work_identity_offline_catalogue as wic
from samuged.dataset import file_digest
from test_musicbrainz_fullexport import a, artist, build_archive, link_type, q, rel, row, sums, w

# Composers: 1 Beethoven (identity), 2 Schubert (name only), 3 and 4 Johann Strauss (namesakes), 5 Kiss (group),
# 6 Bach (identity, no works), 7 an unrelated artist that is never selected.
ARTISTS = [artist(1, 'Ludwig van Beethoven', 'Beethoven, Ludwig van'), artist(2, 'Franz Schubert', 'Schubert, Franz'),
           artist(3, 'Johann Strauss', 'Strauss, Johann'), artist(4, 'Johann Strauss', 'Strauss, Johann'),
           artist(5, 'Kiss', 'Kiss', 2), artist(6, 'Johann Sebastian Bach', 'Bach, Johann Sebastian'),
           artist(7, 'Unrelated Artist', 'Artist, Unrelated')]
WORK_TITLES = [
    'Piano Sonata No. 14 in C-sharp minor, Op. 27 No. 2',
    'Piano Sonata No. 14 in C-sharp minor, Op. 27 No. 2: I. Adagio sostenuto',
    'Piano Sonata No. 14 in C-sharp minor, Op. 27 No. 2: II. Allegretto',
    'Piano Sonata No. 14 in C-sharp minor, Op. 27 No. 2: III. Presto agitato',
    'Piano Sonata No. 1 in F minor, Op. 2 No. 1',
    'Piano Sonata No. 3 in C major, Op. 2 No. 3',
    'Piano Sonata No. 21 in C major, Op. 53 "Waldstein"',
    'Thirty-two Variations in C minor, WoO 80',
    'Piano Sonata in B-flat major, D. 960',
    'Waltz, Op. 1',
    'Unrelated Sonatina, Op. 27 No. 2',
    'Radetzky March, Op. 228',
    'Strauss Potpourri',
    'Detroit Rock City',
    'Piano Sonata No. 14 in C-sharp minor, Op. 27 No. 2 (arr. Strings)',
    'Tantum ergo, D. 962',
]


def work(n, name, kind=1):
    return row(n, w(n), name, kind, '', 0, None)


def link(n, kind):
    return row(n, kind, *[None]*6, 0, None, 'f')


def alias(n, work_id, name):
    return row(n, work_id, name, 'en', 0, '2020-01-01 00:00:00+00', None, name)


def attribute(n, work_id, kind, allowed=None, text=None):
    return row(n, work_id, kind, allowed, text)


WORKS = [work(n, name) for n, name in enumerate(WORK_TITLES, 1)]
LINKS = [link(1001, 168), link(1002, 170), link(1003, 278), link(1004, 999), link(1005, 279)]
LINK_TYPES = [link_type(168, 'artist', 'work', 'composer'), link_type(170, 'artist', 'work', 'dedication'),
              link_type(278, 'work', 'work', 'parts'), link_type(999, 'artist', 'artist', 'member of band'),
              link_type(279, 'work', 'work', 'arrangement')]
# entity0 artist, entity1 work. Work 1 also has a dedication from artist 7, which must be ignored.
# The last row is a dedication of the unrelated artist. The truncation test cuts this table and nothing else.
ARTIST_WORKS = [rel(1, 1001, 1, 1), rel(2, 1001, 1, 2), rel(3, 1001, 1, 3), rel(4, 1001, 1, 4), rel(5, 1001, 1, 5),
                rel(6, 1001, 1, 6), rel(7, 1001, 1, 7), rel(8, 1001, 1, 8), rel(9, 1001, 2, 9), rel(10, 1001, 3, 10),
                rel(11, 1001, 4, 12), rel(12, 1002, 7, 1), rel(13, 1001, 7, 11), rel(14, 1001, 5, 14),
                rel(15, 1001, 1, 15), rel(16, 1001, 2, 16), rel(17, 1002, 7, 14)]
# entity0 parent work, entity1 part work. Work 13 is a parent without a composer relation.
# Work 15 is an arrangement of work 1 (entity0 original, entity1 arrangement).
WORK_WORKS = [rel(1, 1003, 1, 2), rel(2, 1003, 1, 3), rel(3, 1003, 1, 4), rel(4, 1003, 13, 12), rel(5, 1005, 1, 15)]
ALIASES = [alias(1, 7, 'Waldstein Sonata'), alias(2, 16, 'Tantum ergo Mass')]
ATTRIBUTE_TYPES = [row(1, 'Opus'), row(2, 'Key'), row(3, 'D')]
ALLOWED_VALUES = [row(101, 2, 'C-sharp minor'), row(102, 2, 'B-flat major'), row(103, 2, 'C major'), row(104, 2, 'F minor')]
ATTRIBUTES = [attribute(1, 1, 1, None, '27 no. 2'), attribute(2, 1, 2, 101), attribute(3, 2, 1, None, '27 no. 2'),
              attribute(4, 3, 1, None, '27 no. 2'), attribute(5, 4, 1, None, '27 no. 2'), attribute(6, 5, 1, None, '2 no. 1'),
              attribute(7, 5, 2, 104), attribute(8, 6, 1, None, '2 no. 3'), attribute(9, 6, 2, 103),
              attribute(10, 7, 1, None, '53'), attribute(11, 9, 3, None, '960'), attribute(12, 9, 2, 102),
              attribute(13, 10, 1, None, '1'), attribute(14, 12, 1, None, '228')]
CATALOGUE = dict(artist=ARTISTS, l_artist_work=ARTIST_WORKS, l_work_work=WORK_WORKS, link=LINKS, link_type=LINK_TYPES,
                 work=WORKS, work_alias=ALIASES, work_attribute=ATTRIBUTES, work_attribute_type=ATTRIBUTE_TYPES,
                 work_attribute_type_allowed_value=ALLOWED_VALUES, release=[row(1, 'Ignored', 'x')])

# key, title, creator, title_status. Rows M01 to M15 are MAESTRO rows, the others must never be processed.
MAESTRO = [
    ('M01', 'Sonata No. 14 in C-sharp Minor, Op. 27 No. 2, I. Adagio', 'Ludwig van Beethoven', 'usable'),
    ('M02', 'Thirty-Two Variations in C Minor, WoO 80', 'Ludwig van Beethoven', 'usable'),
    ('M03', 'Sonata "Waldstein"', 'Ludwig van Beethoven', 'usable'),
    ('M04', 'Sonata Op. 2', 'Ludwig van Beethoven', 'usable'),
    ('M05', 'Sonata in B-flat Major, D960', 'Franz Schubert', 'usable'),
    ('M06', 'Sonata in D Major, Op. 27 No. 2', 'Ludwig van Beethoven', 'usable'),
    ('M07', 'Waltz Op. 1', 'Johann Strauss', 'usable'),
    ('M08', 'Für Elise', 'Ludwig van Beethoven', 'usable'),
    ('M09', 'Sonata Op. 999', 'Ludwig van Beethoven', 'usable'),
    ('M10', 'Chaconne, BWV 1004', 'Johann Sebastian Bach / Ferruccio Busoni', 'usable'),
    ('M11', None, 'Ludwig van Beethoven', 'missing'),
    ('M12', 'Sonata Op. 27', 'Ludwig van Beethoven', 'suspect_encoding'),
    ('M13', 'Sonata Op. 27 No. 2', '', 'usable'),
    ('M14', 'Detroit Rock City', 'Kiss', 'usable'),
    ('M15', 'Sonata in A Major, D. 962', 'Franz Schubert', 'usable'),
]
OTHER = [
    ('L01', 'Piano Sonata No. 14 in C-sharp minor, Op. 27 No. 2', 'Ludwig van Beethoven', 'lakh', 'recording'),
    ('P01', 'Sonata Op. 27 No. 2', 'Ludwig van Beethoven', 'pdmx', 'work'),
]
EXPECTED = {
    'M01': ('candidate', 'candidate'), 'M02': ('candidate', 'candidate'), 'M03': ('candidate', 'candidate'),
    'M04': ('candidate', 'candidate'), 'M05': ('candidate', 'candidate'), 'M06': ('candidate', 'candidate'),
    'M07': ('no_candidate', 'composer_not_identified'), 'M08': ('no_candidate', 'no_catalogue_number'),
    'M09': ('no_candidate', 'catalogue_number_without_work'), 'M10': ('no_candidate', 'catalogue_number_without_work'),
    'M11': ('missing_labels', 'missing_title'), 'M12': ('missing_labels', 'title_not_usable'),
    'M13': ('missing_labels', 'missing_creator'), 'M14': ('no_candidate', 'composer_not_identified'),
    'M15': ('candidate', 'candidate'),
}
SOURCE_MATCHES = {  # composer_components, composers_resolved, catalogue_keys_json, matched_work_count, parent_work_count, truncated
    'M01': (1, 1, '["op27", "op27no2"]', 5, 1, 0), 'M02': (1, 1, '["woo80"]', 1, 1, 0), 'M03': (1, 1, '[]', 1, 1, 0),
    'M04': (1, 1, '["op2"]', 2, 2, 0), 'M05': (1, 1, '["d960"]', 1, 1, 0), 'M06': (1, 1, '["op27", "op27no2"]', 5, 1, 0),
    'M07': (1, 0, '[]', 0, 0, 0), 'M08': (1, 1, '[]', 0, 0, 0), 'M09': (1, 1, '["op999"]', 0, 0, 0),
    'M10': (2, 1, '["bwv1004"]', 0, 0, 0), 'M14': (1, 0, '[]', 0, 0, 0), 'M15': (1, 1, '["d962"]', 1, 1, 0),
}


def catalogue_index(path):
    with closing(sqlite3.connect(path)) as db:
        db.execute('CREATE TABLE queue(source_key TEXT,source_sha256 TEXT,dataset_id TEXT,title TEXT,creator TEXT,query_kind TEXT,'
                   'status TEXT,error TEXT,updated_on TEXT)')
        db.execute('CREATE TABLE track_metadata(source_key TEXT,title_status TEXT,creator_status TEXT,creator_basis TEXT,'
                   'gaps_json TEXT,evidence_json TEXT)')
        db.executemany('INSERT INTO queue VALUES (?,?,?,?,?,?,?,?,?)',
                       [(k, 'h'+k, 'maestro', t, c, 'work', 'no_candidate', None, 'x') for k, t, c, _ in MAESTRO]
                       + [(k, 'h'+k, d, t, c, q_kind, 'no_candidate', None, 'x') for k, t, c, d, q_kind in OTHER])
        statuses = [(k, s) for k, _, _, s in MAESTRO] + [(k, 'usable') for k, *_ in OTHER]
        db.executemany('INSERT INTO track_metadata VALUES (?,?,?,?,?,?)',
                       [(k, s, None, 'catalog_artist', '[]', '{}') for k, s in statuses])
        db.commit()


def offline_index(path):
    with closing(sqlite3.connect(path)) as db:
        db.executescript(wio.SCHEMA)
        db.executemany('INSERT INTO creator_identities(creator_key,status,artist_id,artist_name,artist_type) VALUES (?,?,?,?,?)', [
            ('beethoven ludwig van', 'disambiguated_by_work_relation', a(1), 'Ludwig van Beethoven', 'Person'),
            ('bach johann sebastian', 'single_person_candidate', a(6), 'Johann Sebastian Bach', 'Person')])
        db.commit()


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr('samuged.musicbrainz_dump.shutil.disk_usage', lambda p: namedtuple('U', 'total used free')(0, 0, 20*1024**3))
    monkeypatch.setattr('samuged.musicbrainz_fullexport.shutil.which', lambda name: None)
    export = tmp_path/'20261007-002147'; export.mkdir()
    build_archive(export/'mbdump.tar.bz2', tables=CATALOGUE); sums(export)
    index, offline = tmp_path/'work_identity_v04.sqlite', tmp_path/'work_identity_offline_v01.sqlite'
    catalogue_index(index); offline_index(offline)
    return export, index, offline, tmp_path/'musicbrainz_catalogue_v01.sqlite'


@pytest.fixture
def prepared(env):
    export, index, offline, sub = env
    wic.subset(export, index, offline, sub)
    out = sub.with_name('work_identity_offline_catalogue_v01.sqlite')
    wic.prepare(index, offline, sub, out)
    return out


def test_subset_keeps_composers_works_and_relations(env):
    export, index, offline, sub = env
    before = file_digest(index), file_digest(offline)
    result = wic.subset(export, index, offline, sub)
    assert (file_digest(index), file_digest(offline)) == before
    assert result['policy'] == wic.SUBSET_POLICY and result['identity_verified'] is False
    assert q(sub, 'SELECT name,selected_by FROM composers ORDER BY artist_id') == [
        ('Ludwig van Beethoven', 'gid'), ('Franz Schubert', 'name'), ('Johann Strauss', 'name'),
        ('Johann Strauss', 'name'), ('Johann Sebastian Bach', 'gid')]  # Kiss (group) and the unrelated artist are not kept
    assert {g for (g,) in q(sub, 'SELECT gid FROM works')} == {w(n) for n in (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 13, 15, 16)}
    assert set(q(sub, 'SELECT work_id,artist_id FROM work_composers')) == {
        (1, 1), (2, 1), (3, 1), (4, 1), (5, 1), (6, 1), (7, 1), (8, 1), (9, 2), (10, 3), (12, 4), (15, 1), (16, 2)}
    assert q(sub, 'SELECT DISTINCT role FROM work_composers') == [('composer',)]  # dedication is ignored
    assert set(q(sub, 'SELECT parent_id,part_id FROM work_parts')) == {(1, 2), (1, 3), (1, 4), (13, 12)}
    assert set(q(sub, 'SELECT work0,work1,link_type FROM work_links')) == {
        (1, 2, 'parts'), (1, 3, 'parts'), (1, 4, 'parts'), (13, 12, 'parts'), (1, 15, 'arrangement')}
    assert q(sub, 'SELECT work_id,name FROM work_aliases ORDER BY work_id') == [(7, 'Waldstein Sonata'), (16, 'Tantum ergo Mass')]
    assert q(sub, "SELECT attribute_type,value FROM work_attributes WHERE work_id=1 ORDER BY 1") == [
        ('Key', 'C-sharp minor'), ('Opus', '27 no. 2')]  # the key comes from an allowed value, not free text
    policy, dump, inputs, count, verified, rights = q(
        sub, 'SELECT policy,dump_json,inputs_json,composer_count,identity_verified,rights_clearance FROM provenance')[0]
    dump, inputs = json.loads(dump), json.loads(inputs)
    assert (policy, count, verified, rights) == (wic.SUBSET_POLICY, 6, 0, 'not_established')
    assert dump['export_name'] == '20261007-002147' and dump['archive'] == 'mbdump.tar.bz2'
    assert dump['sha256'] == hashlib.sha256((export/'mbdump.tar.bz2').read_bytes()).hexdigest()
    assert (dump['replication_sequence'], dump['schema_sequence'], dump['timestamp']) == (189552, 31, '2026-10-07 00:21:48.263241+00')
    assert dump['signature_status'] == 'signature_missing' and dump['decompressor'] == 'python-tarfile-bz2'
    assert dump['truncated'] is False and dump['lines_read']['artist'] == 7 and 'release' not in dump['lines_read']
    assert inputs['work_index']['sha256'] == before[0] and inputs['offline_index']['sha256'] == before[1]
    assert inputs['composer_names'] == {'beethoven ludwig van': a(1), 'franz schubert': None, 'johann strauss': None,
                                        'kiss': None, 'bach johann sebastian': a(6), 'busoni ferruccio': None}


def test_subset_status_counts(env):
    export, index, offline, sub = env
    wic.subset(export, index, offline, sub)
    status = wic.subset_status(sub)
    assert (status['composers'], status['composers_by_gid'], status['composer_names']) == (5, 2, 6)
    assert (status['works'], status['work_composers'], status['work_aliases'], status['work_attributes'],
            status['work_parts']) == (14, 13, 2, 14, 4)
    assert status['work_links'] == {'parts': 4, 'arrangement': 1}
    assert status['attribute_types'] == {'Opus': 9, 'Key': 4, 'D': 1}
    assert status['identity_verified'] is False and status['rights_clearance'] == 'not_established'


def test_subset_refuses_existing_output_and_bad_archive(env):
    export, index, offline, sub = env
    sub.write_text('keep')
    with pytest.raises(FileExistsError):
        wic.subset(export, index, offline, sub)
    assert sub.read_text() == 'keep'
    sub.unlink()
    (export/'SHA256SUMS').write_text('0'*64+' *mbdump.tar.bz2\n')
    with pytest.raises(ValueError, match='archive sha256 mismatch'):
        wic.subset(export, index, offline, sub)
    assert not sub.exists() and [p.name for p in sub.parent.iterdir() if p.name.startswith('tmp')] == []


def test_subset_limit_marks_truncation_and_dump_block_refuses(env):
    export, index, offline, sub = env
    with pytest.raises(ValueError, match='positive'):
        wic.subset(export, index, offline, sub, limit=0)
    # 16 works fit the limit, so only the 17 artist work rows are cut. The cut row is a dedication.
    result = wic.subset(export, index, offline, sub, limit=16)
    assert result['dump']['truncated'] is True and result['dump']['lines_read']['l_artist_work'] == 16
    assert result['dump']['lines_read']['work'] == 16
    with closing(sqlite3.connect(sub)) as db:
        with pytest.raises(ValueError, match='truncated'):
            wic.dump_block(db, file_digest(index), file_digest(offline))


def test_prepare_queue_statuses_and_reasons(prepared):
    got = {k: (s, reason) for k, s, reason in q(prepared, 'SELECT source_key,status,reason FROM queue')}
    assert got == EXPECTED  # the lakh and pdmx rows are not processed


def test_prepare_candidates_and_evidence(prepared):
    rows = q(prepared, 'SELECT source_key,work_id,title,evidence_json FROM work_candidates ORDER BY source_key,work_id')
    assert [(k, wid) for k, wid, _, _ in rows] == [
        ('M01', w(1)), ('M02', w(8)), ('M03', w(7)), ('M04', w(5)), ('M04', w(6)), ('M05', w(9)), ('M06', w(1)), ('M15', w(16))]
    ev = {(k, wid): json.loads(e) for k, wid, _, e in rows}
    m01 = ev[('M01', w(1))]
    basis = m01['match_basis']
    assert basis['title_agreement'] == 'catalogue_number_attribute'
    assert (basis['catalogue_key'], basis['catalogue_key_specific']) == ('op27no2', True)
    assert (basis['source_key'], basis['work_key'], basis['key_agreement']) == ('c sharp minor', 'c sharp minor', 'agrees')
    assert basis['creator_agreement'] == 'composer_identity'
    assert basis['composer'] == dict(gid=a(1), name='Ludwig van Beethoven', component='Ludwig van Beethoven',
                                     identity_status='disambiguated_by_work_relation')
    # The movements and the arrangement are reduced away. The parent is the candidate.
    assert basis['matched_part_titles'] == sorted(
        ['Piano Sonata No. 14 in C-sharp minor, Op. 27 No. 2: I. Adagio sostenuto',
         'Piano Sonata No. 14 in C-sharp minor, Op. 27 No. 2: II. Allegretto',
         'Piano Sonata No. 14 in C-sharp minor, Op. 27 No. 2: III. Presto agitato',
         'Piano Sonata No. 14 in C-sharp minor, Op. 27 No. 2 (arr. Strings)'])
    assert basis['derived_or_part_works_dropped'] == 4 and basis['multiple_work_candidates'] is False
    # The gids of the works reduced away, in the same set as the titles above (the movements and the arrangement).
    assert basis['related_work_ids'] == [w(2), w(3), w(4), w(15)]
    assert (basis['form_agreement'], basis['source_forms'], basis['work_forms']) == ('agrees', ['sonata'], ['sonata'])
    assert m01['work'] == dict(gid=w(1), title='Piano Sonata No. 14 in C-sharp minor, Op. 27 No. 2', type=1,
                               relations=[dict(type='composer', artist=dict(id=a(1), name='Ludwig van Beethoven'))])
    assert m01['provider'] == 'musicbrainz_fullexport_catalogue' and m01['policy'] == 'work-candidates-v4-catalogue'
    assert m01['method'] == 'composer_identity_and_catalogue_number_agreement_not_MIDI_identity'
    assert (m01['identity_verified'], m01['rights_clearance']) == (False, 'not_established')
    assert (m01['musical_work_license_status'], m01['rights_holder_status'], m01['metadata_license']) == (
        'unknown', 'not_established', 'CC0-1.0')
    assert basis['musical_comparison'] == 'not_performed' and basis['source_identity_verified'] is False
    assert m01['dump']['export_name'] == '20261007-002147' and m01['dump']['schema_sequence'] == 31
    assert ev[('M02', w(8))]['match_basis']['title_agreement'] == 'catalogue_number_title'
    assert ev[('M02', w(8))]['match_basis']['catalogue_key'] == 'woo80'
    m03 = ev[('M03', w(7))]['match_basis']
    assert (m03['title_agreement'], m03['catalogue_key'], m03['catalogue_key_specific']) == ('nickname_quoted', 'waldstein', False)
    for wid in (w(5), w(6)):  # bare opus, two separate works each carrying the number in its title
        basis = ev[('M04', wid)]['match_basis']
        assert basis['related_work_ids'] == [] and basis['matched_part_titles'] == []
        assert (basis['title_agreement'], basis['catalogue_key'], basis['catalogue_key_specific']) == (
            'catalogue_number_attribute', 'op2', False)
        assert (basis['title_namesake_count'], basis['multiple_work_candidates'], basis['key_agreement']) == (2, True, 'unknown')
    m05 = ev[('M05', w(9))]['match_basis']
    assert (m05['creator_agreement'], m05['key_agreement'], m05['catalogue_key']) == (
        'composer_name_single_namesake', 'agrees', 'd960')
    assert m05['composer']['identity_status'] == 'single_person_namesake' and m05['composer']['gid'] == a(2)
    m06 = ev[('M06', w(1))]['match_basis']
    assert (m06['key_agreement'], m06['source_key'], m06['work_key']) == ('disagrees', 'd major', 'c sharp minor')
    m15 = ev[('M15', w(16))]['match_basis']  # a disagreeing form stays a candidate
    assert (m15['title_agreement'], m15['catalogue_key'], m15['creator_agreement']) == (
        'catalogue_number_title', 'd962', 'composer_name_single_namesake')
    assert (m15['form_agreement'], m15['source_forms'], m15['work_forms']) == ('disagrees', ['sonata'], ['mass'])


def test_prepare_source_matches(prepared):
    assert {r[0]: r[1:] for r in q(prepared, 'SELECT * FROM source_matches')} == SOURCE_MATCHES


def test_prepare_status_counts_and_provenance(prepared):
    s = wic.status(prepared)
    assert s['sources'] == 15 and s['identity_verified'] is False and s['rights_clearance'] == 'not_established'
    assert s['queue_status'] == {'candidate': 7, 'no_candidate': 5, 'missing_labels': 3}
    assert s['reasons'] == {'candidate': 7, 'composer_not_identified': 2, 'no_catalogue_number': 1,
                            'catalogue_number_without_work': 2, 'missing_title': 1, 'title_not_usable': 1, 'missing_creator': 1}
    assert (s['work_candidates'], s['candidate_sources'], s['single_candidate_sources'], s['distinct_works']) == (8, 7, 6, 7)
    assert s['title_agreement'] == {'catalogue_number_attribute': 5, 'catalogue_number_title': 2, 'nickname_quoted': 1}
    assert s['key_agreement'] == {'agrees': 2, 'disagrees': 1, 'unknown': 5}
    assert s['form_agreement'] == {'agrees': 7, 'disagrees': 1}
    assert s['creator_agreement'] == {'composer_identity': 6, 'composer_name_single_namesake': 2}
    assert s['truncated_sources'] == 0
    policy, verified, rights, selection = q(
        prepared, 'SELECT policy,identity_verified,rights_clearance,selection_json FROM provenance')[0]
    assert (policy, verified, rights) == ('work-candidates-v4-catalogue', 0, 'not_established')
    assert json.loads(selection) == dict(dataset='maestro', query_kind='work', limit=None, truncated=False, sources=15,
                                         max_parent_works=20, composer_names=6, composer_names_identified=2)


def test_prepare_inputs_unchanged_and_other_inputs_refused(env):
    export, index, offline, sub = env
    wic.subset(export, index, offline, sub)
    before = file_digest(index), file_digest(offline), file_digest(sub)
    out = sub.with_name('catalogue_v01.sqlite')
    wic.prepare(index, offline, sub, out)
    assert (file_digest(index), file_digest(offline), file_digest(sub)) == before
    inputs = json.loads(q(out, 'SELECT inputs_json FROM provenance')[0][0])
    assert inputs['subset']['sha256'] == before[2] and inputs['work_index']['sha256'] == before[0]
    other = index.with_name('other_v04.sqlite')
    shutil.copy(index, other)
    with closing(sqlite3.connect(other)) as db:
        db.execute("INSERT INTO queue VALUES ('X1','hX1','lakh','Other','Other','recording','no_candidate',NULL,'x')")
        db.commit()
    refused = sub.with_name('refused.sqlite')
    with pytest.raises(ValueError, match='subset was built from other inputs'):
        wic.prepare(other, offline, sub, refused)
    assert not refused.exists()


def test_prepare_limit_and_parent_cap(env, monkeypatch):
    export, index, offline, sub = env
    wic.subset(export, index, offline, sub)
    limited = sub.with_name('limited.sqlite')
    result = wic.prepare(index, offline, sub, limited, limit=3)
    assert result['selection']['truncated'] is True and result['sources'] == 3
    assert {k for (k,) in q(limited, 'SELECT source_key FROM queue')} == {'M01', 'M02', 'M03'}
    with pytest.raises(ValueError, match='positive'):
        wic.prepare(index, offline, sub, sub.with_name('zero.sqlite'), limit=0)
    capped = sub.with_name('capped.sqlite')
    monkeypatch.setattr(wic, 'MAX_PARENTS', 1)
    wic.prepare(index, offline, sub, capped)
    assert q(capped, "SELECT work_id FROM work_candidates WHERE source_key='M04'") == [(w(5),)]
    basis = json.loads(q(capped, "SELECT evidence_json FROM work_candidates WHERE source_key='M04'")[0][0])['match_basis']
    assert basis['parents_truncated'] is True
    assert q(capped, "SELECT truncated,parent_work_count FROM source_matches WHERE source_key='M04'") == [(1, 2)]
    assert wic.status(capped)['truncated_sources'] == 1


def test_reduce_keeps_highest_matched_ancestor_within_three_levels(tmp_path):
    with closing(sqlite3.connect(tmp_path/'tree.sqlite')) as db:
        db.executescript(wic.SUBSET_SCHEMA)
        db.executemany('INSERT INTO works(work_id,gid,name,type) VALUES (?,?,?,?)', [(n, w(n), f'work {n}', 1) for n in range(1, 8)])
        # Chain 1 to 2 to 4 to 5 to 6 to 7, with 3 as a second parent of 1. Work 7 is derived from work 3.
        db.executemany('INSERT INTO work_parts(parent_id,part_id) VALUES (?,?)', [(2, 1), (3, 1), (4, 2), (5, 4), (6, 5), (7, 6)])
        db.execute("INSERT INTO work_links VALUES (3, 7, 'arrangement')")
        ref = wic.Reference(db, {})
        assert ref.ancestors(1) == {2, 3, 4, 5}  # the fourth level (6) is out of reach
        assert ref.reduce({1, 5}) == ({5}, {1})
        assert ref.reduce({1, 6}) == ({1, 6}, set())
        assert ref.reduce({3, 7}) == ({3}, {7})  # the second element lists every removed work


def tree(path, works, parts=(), links=(), composer=None):
    """Hand built subset tables. Works are (id, name) pairs, every work is a composer work of artist 1 when composer is set."""
    db = sqlite3.connect(path)
    db.executescript(wic.SUBSET_SCHEMA)
    if composer:
        db.execute("INSERT INTO composers VALUES (1, ?, ?, ?, 1, 'gid')", (a(1), composer, composer))
    db.executemany('INSERT INTO works(work_id,gid,name,type) VALUES (?,?,?,?)', [(n, w(n), name, 1) for n, name in works])
    db.executemany('INSERT INTO work_parts(parent_id,part_id) VALUES (?,?)', parts)
    db.executemany('INSERT INTO work_links VALUES (?,?,?)', links)
    if composer:
        db.executemany('INSERT INTO work_composers VALUES (?,?,?)', [(n, 1, 'composer') for n, _ in works])
    db.commit()
    return db


def test_single_work_keeps_alias_equal_to_title_prefix(tmp_path):
    with closing(tree(tmp_path/'alias.sqlite', [(1, 'Étude in C major, op. 10 no. 1: Allegro')], composer='Frédéric Chopin')) as db:
        db.execute("INSERT INTO work_aliases VALUES (1, 'Étude in C major, op. 10 no. 1')")
        db.commit()
        ref = wic.Reference(db, {})
        assert ref.reduce({1}) == ({1}, set())  # its own alias is not a title of another work
        assert ref.reduce({1}, 'op10no1') == ({1}, set())
        state, _, rows, _ = wic.match(('E1', 'hE1', 'maestro', 'Étude in C major, op. 10 no. 1', 'Frédéric Chopin', 'usable', None),
                                       ref, {})
        assert state == 'candidate' and [r[1] for r in rows] == [w(1)]


def test_movement_with_alias_equal_to_whole_title_is_still_dropped(tmp_path):
    works = [(1, 'Étude in C major, op. 10 no. 1'), (2, 'Étude in C major, op. 10 no. 1: Alternative ending for the coda')]
    with closing(tree(tmp_path/'alias_movement.sqlite', works, composer='Frédéric Chopin')) as db:
        db.execute("INSERT INTO work_aliases VALUES (2, 'Étude in C major, op. 10 no. 1')")  # the movement's alias is the whole title
        db.commit()
        ref = wic.Reference(db, {})
        assert ref.reduce({1, 2}) == ({1}, {2})  # the whole work stays and the movement is removed


def test_related_work_ids_are_capped_at_one_hundred(tmp_path):
    parent, children = [(1, 'Set of Variations, Op. 1')], [(n, f'Set of Variations, Op. 1: Variation {n}') for n in range(2, 103)]
    parts = [(1, n) for n in range(2, 103)]
    with closing(tree(tmp_path/'cap.sqlite', parent + children, parts=parts, composer='Ludwig van Beethoven')) as db:
        state, _, rows, _ = wic.match(('C1', 'hC1', 'maestro', 'Set, Op. 1', 'Ludwig van Beethoven', 'usable', None),
                                      wic.Reference(db, {}), {})
    assert state == 'candidate' and [r[1] for r in rows] == [w(1)]
    basis = json.loads(rows[0][4])['match_basis']
    assert basis['derived_or_part_works_dropped'] == 101
    assert basis['related_work_ids'] == sorted(w(n) for n in range(2, 103))[:100]
    assert len(basis['matched_part_titles']) == 10


def test_is_movement_labels():
    assert wic.is_movement('Sonata no. 8, op. 13: II. Adagio cantabile', 'Ludwig van Beethoven')
    assert wic.is_movement('Étude in F major, op. 10 no. 8: Allegro', 'Frédéric Chopin')
    assert wic.is_movement('Carmen: Acte II', 'Georges Bizet')
    assert not wic.is_movement('The Well-Tempered Clavier, Book I: Prelude and Fugue no. 5 in D major, BWV 850.2/850',
                               'Johann Sebastian Bach')  # the tail carries a catalogue number of its own
    assert not wic.is_movement('Sonata for Piano no. 21 in C major, op. 53 “Waldstein”', 'Ludwig van Beethoven')
    assert not wic.is_movement('Sonata no. 8, op. 13', 'Ludwig van Beethoven')  # no colon, so no movement label


def test_reduce_drops_titles_under_a_kept_work_and_movements(tmp_path):
    works = [(1, 'Symphony No. 9'), (2, 'Symphony No. 9: Choral Symphony in the Sense of Joy'),
             (3, 'Sonata for Piano no. 8'), (4, 'Sonata no. 8, op. 13: II. Adagio cantabile')]
    with closing(tree(tmp_path/'titles.sqlite', works)) as db:
        ref = wic.Reference(db, {})
        assert ref.reduce({1, 2}) == ({1}, {2})  # "<kept title>: <something>" names a part of the kept work
        assert ref.reduce({3, 4}) == ({3}, {4})  # a movement form is dropped while a whole work remains
        assert ref.reduce({4}) == ({4}, set())  # a movement form stays when nothing else matched
        assert ref.reduce({2}) == ({2}, set())  # a colon title that is not a movement label stays


def test_reduce_bare_opus_keeps_the_set(tmp_path):
    works = [(5, 'Sonata, Op. 2'), (6, 'Sonata No. 1, Op. 2 No. 1'), (7, 'Sonata No. 3, Op. 2 No. 3')]
    with closing(tree(tmp_path/'opus.sqlite', works)) as db:
        ref = wic.Reference(db, {})
        assert ref.reduce({5, 6, 7}, 'op2') == ({5}, {6, 7})  # the set level work wins over its numbered pieces
        assert ref.reduce({6, 7}, 'op2') == ({6, 7}, set())  # without a set level work both numbered works stay
        assert ref.reduce({5, 6, 7}, 'op2no1') == ({5, 6, 7}, set())  # the rule is for bare opus keys only


def test_nickname_index_is_exact_or_prefix_and_quoted(tmp_path):
    works = [(1, 'Carmen'), (2, 'Carmen Medley'), (3, 'Carmen: Acte II'), (4, 'Carmen, Act IV (Opera)'),
             (5, 'Carmen from Act II'), (6, 'Carmen (Habanera)')]
    with closing(tree(tmp_path/'nick.sqlite', works, parts=[(1, 6)], composer='Georges Bizet')) as db:
        keys, names = wic.Reference(db, {}).lookup(1, 'composer')
        assert names['carmen'] == {1, 3, 4, 5}  # exact title, and the prefix before ':', ',', '(' or ' from '
        assert 2 not in names['carmen'] and names['carmen medley'] == {2}  # "Carmen Medley" is not "carmen"
        assert 6 not in names['carmen']  # a movement is not indexed for nicknames at all


def test_match_nickname_drops_movements_and_other_titles(tmp_path):
    works = [(1, 'Carmen'), (2, 'Carmen Medley'), (3, 'Carmen: Acte II')]
    with closing(tree(tmp_path/'match_nick.sqlite', works, composer='Georges Bizet')) as db:
        ref = wic.Reference(db, {})
        state, reason, rows, _ = wic.match(('N1', 'hN1', 'maestro', 'Opera "Carmen"', 'Georges Bizet', 'usable', None), ref, {})
        assert (state, reason) == ('candidate', 'candidate')
        assert [r[1] for r in rows] == [w(1)]  # "Carmen Medley" does not match, "Carmen: Acte II" is a movement of Carmen
        basis = json.loads(rows[0][4])['match_basis']
        assert (basis['title_agreement'], basis['catalogue_key_specific'], basis['derived_or_part_works_dropped']) == (
            'nickname_quoted', False, 1)


def test_match_keeps_matched_works_not_their_parents(tmp_path):
    with closing(sqlite3.connect(tmp_path/'match.sqlite')) as db:
        db.executescript(wic.SUBSET_SCHEMA)
        db.execute("INSERT INTO composers VALUES (1, ?, 'Ludwig van Beethoven', 'Beethoven, Ludwig van', 1, 'gid')", (a(1),))
        db.executemany('INSERT INTO works(work_id,gid,name,type) VALUES (?,?,?,?)', [
            (1, w(1), 'Piano Sonatas, complete set', 1),          # parent without a catalogue key
            (2, w(2), 'Piano Sonata, Op. 13', 1),                  # matched work
            (3, w(3), 'Piano Sonata, Op. 13 (arr. strings)', 1),   # arrangement of work 2
            (4, w(4), 'Grave, "Pathetique" movement', 1)])         # movement with the only nickname
        db.executemany('INSERT INTO work_parts(parent_id,part_id) VALUES (?,?)', [(1, 2), (2, 4)])
        db.execute("INSERT INTO work_links VALUES (2, 3, 'arrangement')")
        db.executemany('INSERT INTO work_composers VALUES (?,?,?)', [(1, 1, 'composer'), (2, 1, 'composer'),
                                                                     (3, 1, 'composer'), (4, 1, 'composer')])
        ref = wic.Reference(db, {})

        def row_of(key, title):
            return key, 'h'+key, 'maestro', title, 'Ludwig van Beethoven', 'usable', None
        state, reason, candidates, _ = wic.match(row_of('C1', 'Sonata, Op. 13'), ref, {})
        assert (state, reason) == ('candidate', 'candidate')
        assert [c[1] for c in candidates] == [w(2)]  # work 1 has no key in its title, so it is never a candidate
        assert json.loads(candidates[0][4])['match_basis']['derived_or_part_works_dropped'] == 1
        assert wic.match(row_of('C2', 'Sonata "Pathetique"'), ref, {})[:2] == ('no_candidate', 'catalogue_number_without_work')


def test_catalogue_keys_by_system_and_gate():
    assert wic.catalogue_keys('Piano Sonata, Op. 27 No. 2', 'Ludwig van Beethoven') == {'op27', 'op27no2'}
    assert wic.catalogue_keys('Sonata Op. 2', 'Ludwig van Beethoven') == {'op2'}
    assert wic.catalogue_keys('Sonata op. 8: No. 10', 'Ludwig van Beethoven') == {'op8', 'op8no10'}
    assert wic.catalogue_keys('Sonata Hob. XVI:52', 'Joseph Haydn') == {'hobxvi52'}
    assert wic.catalogue_keys('Sonata Hob. XVI:52', 'Ludwig van Beethoven') == set()
    assert wic.catalogue_keys('Etude S. 244/10', 'Franz Liszt') == {'s244', 's244no10'}
    assert wic.catalogue_keys('Etude S.139/5', 'Franz Liszt') == {'s139', 's139no5'}
    assert wic.catalogue_keys('Chaconne, BWV 1004', 'Johann Sebastian Bach') == {'bwv1004'}
    assert wic.catalogue_keys('Chaconne, BWV 1004', 'Ludwig van Beethoven') == set()
    assert wic.catalogue_keys('Sonata D960', 'Franz Schubert') == {'d960'}
    assert wic.catalogue_keys('Sonata D. 960', 'Ludwig van Beethoven') == set()
    assert wic.catalogue_keys('Sonata K. 331', 'Wolfgang Amadeus Mozart') == {'k331'}
    assert wic.catalogue_keys('Sonata K. 331', 'Ludwig van Beethoven') == set()
    assert wic.catalogue_keys('Variations, WoO 80', 'Ludwig van Beethoven') == {'woo80'}
    assert wic.catalogue_keys('Variations, WoO 80', 'Franz Schubert') == set()
    assert wic.catalogue_keys('Sonata in D Major', 'Ludwig van Beethoven') == set()


def test_attribute_keys_follow_the_same_gates():
    assert wic.attribute_keys('Opus', '27 no. 2', 'Ludwig van Beethoven') == {'op27', 'op27no2'}
    assert wic.attribute_keys('Key', 'C-sharp minor', 'Ludwig van Beethoven') == set()
    assert wic.attribute_keys('D', '960', 'Franz Schubert') == {'d960'}
    assert wic.attribute_keys('D', '960', 'Ludwig van Beethoven') == set()


def test_title_key_reads_key_and_accidentals():
    assert wic.title_key('Symphony No. 1 in F Major') == 'f major'
    assert wic.title_key('Sonata in D-sharp Minor') == 'd sharp minor'
    assert wic.title_key('Sonata in F# minor') == 'f sharp minor'
    assert wic.title_key('Sonata in Bb major') == 'b flat major'
    assert wic.title_key('Sonata in E♭ major') == 'e flat major'
    assert wic.title_key('Sonata in F♯ minor') == 'f sharp minor'
    assert wic.title_key('Sonata Op. 27 No. 2') is None


def test_nicknames_forms_and_specific_keys():
    assert wic.nicknames('Sonata "Waldstein"') == {'waldstein'}
    assert wic.nicknames('Sonata «Appassionata»') == {'appassionata'}
    assert wic.nicknames('Sonata "Abc"') == set() and wic.nicknames(None) == set()
    assert wic.usable_nicknames('Sonata "Waldstein"') == {'waldstein'}
    assert wic.usable_nicknames('Sonata "Elegy"') == set()  # shorter than six characters
    assert wic.usable_nicknames('Sonata "Molto vivace"') == set()  # a tempo marking
    assert wic.forms_in('Piano Sonata No. 1') == {'sonata'}
    assert wic.forms_in('Tantum ergo, D. 962') == set() and wic.forms_in('Tantum ergo Mass') == {'mass'}
    assert [wic.specific(k) for k in ('op2', 'op2no1', 's244', 's244no10', 'd960')] == [False, True, False, True, True]


def test_cli_commands(env, monkeypatch, capsys):
    def run(*args):
        monkeypatch.setattr(sys, 'argv', ['work_identity_offline_catalogue', *args])
        wic.main()
        return json.loads(capsys.readouterr().out)
    export, index, offline, sub = env
    out = sub.with_name('cli_catalogue.sqlite')
    built = run('subset', '--export', str(export), '--work-index', str(index), '--offline-index', str(offline), '--output', str(sub))
    assert {'policy', 'dump', 'composers', 'works', 'output_sha256', 'elapsed_seconds'} <= set(built)
    assert built['works'] == 14
    assert run('subset-status', '--subset', str(sub))['composers'] == 5
    prepared_status = run('prepare', '--work-index', str(index), '--offline-index', str(offline), '--subset', str(sub),
                          '--output', str(out))
    assert prepared_status['selection']['sources'] == 15 and prepared_status['work_candidates'] == 8
    assert run('status', '--index', str(out))['queue_status'] == {'candidate': 7, 'no_candidate': 5, 'missing_labels': 3}
