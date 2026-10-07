import gzip
import json
import sqlite3
from collections import defaultdict, namedtuple

import pytest

from samuged import musicbrainz_dump as mb
from samuged import work_identity_offline as wio
from samuged.candidate_assessment import read_candidates, writers_of
from samuged.dataset import file_digest
from samuged.work_identity import label


def uid(n): return f'2f0b1b3a-0000-4000-8000-{n:012d}'


SMITH, SMITH2, MIDWAY, LIVING, OLD, BROWN, BROWN2, KISS, OTHER = (uid(900+i) for i in range(9))
PEOPLE = {SMITH: ('John Smith', 'Smith, John', 'Person', '1920', '1990-02-01', True),
          SMITH2: ('John Smith', 'Smith, John', 'Person', '1950', None, None),
          MIDWAY: ('Bert Midway', 'Midway, Bert', 'Person', '1910', '1990', True),
          LIVING: ('Cara Living', 'Living, Cara', 'Person', '1970', None, False),
          OLD: ('Anna Oldfield', 'Oldfield, Anna', 'Person', '1840', '1900-05-01', True),
          BROWN: ('Peter Brown', 'Brown, Peter', 'Person', None, None, None),
          BROWN2: ('Peter Brown', 'Brown, Peter', 'Person', None, '1960', True),
          KISS: ('Kiss', 'Kiss', 'Group', '1973', None, False),
          OTHER: ('Other Writer', 'Writer, Other', 'Person', None, None, None)}


def rel(artist_id, role='composer'):
    name, sort, kind = PEOPLE[artist_id][:3]
    return {'target-type': 'artist', 'type': role, 'artist': {'id': artist_id, 'name': name, 'sort-name': sort, 'type': kind}}


def work(n, title, writers=(), aliases=(), performances=0, iswcs=()):
    perf = [{'target-type': 'recording', 'type': 'performance', 'recording': {'title': title}}]*performances
    return dict(id=uid(n), title=title, type='Song', iswcs=list(iswcs), aliases=[{'name': a} for a in aliases],
                relations=[rel(*w) if isinstance(w, tuple) else rel(w) for w in writers]+perf)


WORKS = [work(1, 'Home Free', [SMITH], performances=2, iswcs=['T-1']), work(2, 'Home Free', [OTHER], performances=5),
         work(3, 'Other Title', [OTHER], aliases=['Home Free'], performances=9), work(4, 'Blue Moon', [(SMITH, 'lyricist')]),
         work(5, 'Morgenlied', [MIDWAY], aliases=['Morning Song']), work(6, 'Rock Anthem', [(LIVING, 'writer')]),
         work(7, 'Rock Anthem', [(KISS, 'arranger')])]
WORKS += [work(100+i, 'Minuet', [MIDWAY] if i == 59 else [OTHER], performances=60-i) for i in range(60)]
# key, dataset, title, creator, title_status, creator_basis
QUEUE = [('s01', 'pdmx', 'Home Free', 'Smith, John', 'usable', 'catalog_composer'),
         ('s02', 'pdmx', 'Blue Moon', 'J. Smith', 'usable', 'upstream_artist_role_unverified'),
         ('s03', 'maestro', 'Morning song', 'Bert Midway', 'usable', 'catalog_composer'),
         ('s04', 'lakh', 'Rock Anthem', 'Cara Living', 'usable', 'catalog_artist'),
         ('s05', 'pdmx', 'Home free!', None, 'usable', 'unresolved'),
         ('s06', 'pdmx', 'Home Free', 'Peter Brown', 'usable', 'catalog_composer'),
         ('s07', 'lakh', 'Unknown Tune', 'Kiss', 'usable', 'catalog_artist'),
         ('s08', 'pdmx', None, 'Zed Nobody', 'missing', 'catalog_composer'),
         ('s09', 'pdmx', 'Home Free', 'Smith, John', 'suspect_encoding', 'catalog_composer'),
         ('s10', 'pdmx', 'Minuet', None, 'usable', 'unresolved'),
         ('s11', 'pdmx', 'Minuet', 'Bert Midway', 'usable', 'catalog_composer'),
         ('s12', 'lakh', 'Rock Anthem', 'M', 'usable', 'catalog_artist')]
CLAIMS = {'s05': 'Anna Oldfield (1840-1900)', 's10': 'Traditional', 's01': None}


def build_subset(path, index, scores, *, artists=True, truncated=False, works=None, work_sha=None, score_sha=None, drop_key=None):
    creators = {mb.name_key(c) for (c,) in q(index, 'SELECT creator FROM queue')}
    creators |= {mb.name_key(x) for (c,) in q(scores, 'SELECT composer_claim FROM score_metadata') for x in mb.creator_search_names(c)}
    creators = {k for k in creators if len(k.replace(' ', '')) >= 3} - {drop_key}
    inputs = {'/x/v04.sqlite': work_sha or file_digest(index), '/x/scores.sqlite': score_sha or file_digest(scores)}
    with sqlite3.connect(path) as db:
        db.executescript(mb.SCHEMA)
        db.executemany('INSERT INTO creator_set VALUES (?)', [(k,) for k in sorted(creators)])
        counts = defaultdict(lambda: [0, 0])
        for raw in works or WORKS:
            w = mb.project_work(raw); canon = label(w['title'])
            aliases = {label(a['name']) for a in w['aliases']} - {canon}
            db.execute('INSERT INTO works VALUES (?,?,?,?,?,?)', (w['id'], w['title'], canon, 'Song', None, json.dumps(w)))
            db.executemany('INSERT INTO work_titles VALUES (?,?,?)', [(canon, w['id'], 'title')]+[(a, w['id'], 'alias') for a in aliases])
            counts[canon][0] += 1
            for a in aliases:
                counts[a][1] += 1
        db.executemany('INSERT INTO title_namesakes VALUES (?,?,?)', [(t, *c) for t, c in counts.items()])
        names = defaultdict(lambda: [0, 0, 0])
        for artist_id, (name, sort, kind, begin, end, ended) in PEOPLE.items() if artists else ():
            db.execute('INSERT INTO artists VALUES (?,?,?,?,?,?,?,?,?,?)', (artist_id, name, sort, mb.name_key(name), kind, begin,
                       end, None if ended is None else int(ended), None, '{}'))
            db.executemany('INSERT INTO artist_names VALUES (?,?,?)', [(mb.name_key(name), artist_id, 'name'), (mb.name_key(sort), artist_id, 'sort_name')])
            names[mb.name_key(name)][0] += kind == 'Person'; names[mb.name_key(name)][1] += 1
        db.executemany('INSERT INTO name_namesakes VALUES (?,?,?,?)', [(k, *c) for k, c in names.items()])
        for archive in ['work.tar.xz'] + ['artist.tar.xz']*artists:
            entry = dict(archive=archive, sha256='ab'*32 if archive == 'work.tar.xz' else 'cd'*32, truncated=truncated)
            db.execute('INSERT INTO provenance VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)', (mb.POLICY, '20261003-001001',
                json.dumps([entry]), '2026-10-03 00:10:01', 123, 30, json.dumps(inputs), 1, 1,
                mb.LICENSE, mb.LICENSE_URL, 0, 'not_established', 'now', 0))


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr('samuged.work_identity_offline.shutil.disk_usage', lambda p: namedtuple('U', 'total used free')(0, 0, 20*1024**3))
    index = tmp_path/'v04.sqlite'
    with sqlite3.connect(index) as db:
        db.execute('CREATE TABLE queue(source_key TEXT,source_sha256 TEXT,dataset_id TEXT,title TEXT,creator TEXT,query_kind TEXT,status TEXT,error TEXT,updated_on TEXT)')
        db.execute('CREATE TABLE track_metadata(source_key TEXT,title_status TEXT,creator_status TEXT,creator_basis TEXT,gaps_json TEXT,evidence_json TEXT)')
        db.executemany('INSERT INTO queue VALUES (?,?,?,?,?,?,?,?,?)', [(k, 'h'+k, d, t, c, 'work', 'pending', None, 'x') for k, d, t, c, *_ in QUEUE])
        db.executemany('INSERT INTO track_metadata VALUES (?,?,?,?,?,?)', [(k, s, None, b, '[]', '{}') for k, _, _, _, s, b in QUEUE])
    scores = tmp_path/'scores.sqlite'
    with sqlite3.connect(scores) as db:
        db.execute('CREATE TABLE score_metadata(source_key TEXT,source_sha256 TEXT,score_id TEXT,source_url TEXT,composer_claim TEXT,review_required INTEGER,evidence_json TEXT)')
        db.executemany('INSERT INTO score_metadata VALUES (?,?,?,?,?,?,?)', [(k, 'h'+k, k, None, c, 1, '{}') for k, c in CLAIMS.items()])
    subset = tmp_path/'subset.sqlite'
    build_subset(subset, index, scores)
    return index, subset, scores, tmp_path/'offline.sqlite'


def q(path, sql, *args):
    with sqlite3.connect(path) as db:
        return db.execute(sql, args).fetchall()


def evidence(path, key):
    return {w: json.loads(e) for w, e in q(path, 'SELECT work_id,evidence_json FROM work_candidates WHERE source_key=?', key)}


def test_candidates_mirror_api_rules(env):
    index, subset, scores, out = env
    before = [p.read_bytes() for p in (index, subset, scores)]
    result = wio.prepare(index, subset, scores, out)
    assert [p.read_bytes() for p in (index, subset, scores)] == before
    assert result['identity_verified'] is False and result['rights_clearance'] == 'not_established'
    assert dict(q(out, 'SELECT source_key,status FROM queue')) == {
        's01': 'candidate', 's02': 'candidate', 's03': 'candidate', 's04': 'candidate', 's05': 'title_only_candidates',
        's06': 'no_candidate', 's07': 'no_namesake', 's08': 'missing_labels', 's09': 'missing_labels',
        's10': 'title_only_candidates', 's11': 'candidate', 's12': 'no_candidate'}
    assert q(out, "SELECT count(*) FROM queue WHERE error IS NOT NULL OR query_kind!='work'") == [(0,)]
    one = evidence(out, 's01')
    assert set(one) == {uid(1)}
    e = one[uid(1)]
    assert (e['provider'], e['policy'], e['metadata_license']) == ('musicbrainz_json_dump', 'work-candidates-v3-dump', 'CC0-1.0')
    assert e['dump'] == dict(dump_name='20261003-001001', timestamp='2026-10-03 00:10:01', replication_sequence=123,
                             schema_sequence=30, archive_sha256='ab'*32)
    b = e['match_basis']
    assert b['title_agreement'] == 'canonical_title_normalized' and b['creator_agreement'] == [
        dict(name='John Smith', role='composer', agreement='normalized_tokens', artist_id=SMITH)]
    assert (b['title_namesake_count'], b['title_alias_namesake_count'], b['linked_work_count']) == (2, 1, 3)
    assert b['distinct_work_candidates'] == 1 and b['multiple_work_candidates'] is False and 'namesakes_truncated' not in b
    assert b['source_identity_verified'] is False and b['musical_comparison'] == 'not_performed'
    assert b['source_creator_role'] == 'composer_label' and b['source_creator_basis'] == 'catalog_composer'
    assert e['work']['id'] == uid(1) and e['work']['iswcs'] == ['T-1'] and e['rights_holder_status'] == 'not_established'
    assert e['identity_verified'] is False and e['rights_clearance'] == 'not_established'
    initials = evidence(out, 's02')[uid(4)]['match_basis']
    assert initials['creator_agreement'][0]['agreement'] == 'initials_candidate' and initials['creator_agreement'][0]['role'] == 'lyricist'
    assert initials['source_creator_role'] == 'artist_label_role_unverified'
    assert evidence(out, 's03')[uid(5)]['match_basis']['title_agreement'] == 'alias_normalized'
    lakh = evidence(out, 's04')
    assert set(lakh) == {uid(6)} and lakh[uid(6)]['match_basis']['source_creator_role'] == 'performer_label'
    assert q(out, "SELECT DISTINCT recording_id,match_status FROM work_candidates") == [('', 'candidate')]
    assert set(evidence(out, 's11')) == {uid(159)}  # The lowest ranked namesake is examined too.


def test_output_is_readable_by_candidate_assessment(env):
    index, subset, scores, out = env
    wio.prepare(index, subset, scores, out)
    with sqlite3.connect('file::memory:', uri=True) as db:
        db.execute('ATTACH DATABASE ? AS o', (out.resolve().as_uri()+'?mode=ro',))
        rows = read_candidates(db, 'o', 'offline_index')
    assert {r['provider'] for r in rows} == {'musicbrainz_json_dump'} and len(rows) == 5
    assert writers_of(next(r for r in rows if r['key'] == 's01')['evidence']) == ['John Smith']


def test_title_only_rows(env):
    index, subset, scores, out = env
    wio.prepare(index, subset, scores, out)
    rows = q(out, "SELECT work_id,status,writers_json,evidence_json FROM title_only_candidates WHERE source_key='s05' ORDER BY rowid")
    assert [r[0] for r in rows] == [uid(2), uid(1), uid(3)]  # canonical by performances, then alias
    assert {r[1] for r in rows} == {'title_only_candidate_requires_review'}
    assert json.loads(rows[1][2]) == [dict(name='John Smith', role='composer', artist_id=SMITH)]
    e = json.loads(rows[1][3])
    assert e['iswc_present'] is True and e['performance_count'] == 2 and e['truncated'] is False and e['ambiguous_title'] is False
    assert e['identity_verified'] is False and e['rights_clearance'] == 'not_established' and e['dump']['replication_sequence'] == 123
    assert json.loads(rows[2][3])['title_agreement'] == 'alias_normalized'
    assert {r[0] for r in q(out, "SELECT status FROM title_only_candidates WHERE source_key='s06'")} == {'title_matches_other_writers_requires_review'}
    assert q(out, "SELECT count(*) FROM title_only_candidates WHERE source_key IN ('s01','s07','s08')") == [(0,)]
    capped = q(out, "SELECT evidence_json FROM title_only_candidates WHERE source_key='s10'")
    assert len(capped) == 50 and all(json.loads(e)['truncated'] and json.loads(e)['ambiguous_title'] for (e,) in capped)


def test_every_namesake_is_examined(env, tmp_path):
    index, _, scores, _ = env
    gavottes = [work(1000+i, 'Gavotte', [MIDWAY] if i == 249 else [OTHER], performances=300-i) for i in range(250)]
    subset = tmp_path/'gavotte.sqlite'
    build_subset(subset, index, scores, works=WORKS+gavottes)
    with sqlite3.connect(subset) as db:
        state, rows, _, ids = wio.match(('s13', 'h', 'pdmx', 'Gavotte', 'Bert Midway', 'usable', 'catalog_composer'), wio.Reference(db), {})
    assert state == 'candidate' and [r[1] for r in rows] == [uid(1249)] and ids == {MIDWAY}
    basis = json.loads(rows[0][4])['match_basis']
    assert basis['linked_work_count'] == 250 and 'namesakes_truncated' not in basis


def test_only_strong_candidates_disambiguate(env):
    index, subset, scores, out = env
    with sqlite3.connect(index) as db:  # Without s11 only the alias candidate of s03 remains.
        db.execute("UPDATE queue SET creator=NULL WHERE source_key='s11'")
    build_subset(subset.with_name('s.sqlite'), index, scores)
    wio.prepare(index, subset.with_name('s.sqlite'), scores, out)
    assert q(out, "SELECT status,artist_id FROM creator_identities WHERE creator_key='bert midway'") == [('single_person_candidate', MIDWAY)]


def test_weak_candidates_do_not_disambiguate(env):
    index, subset, scores, out = env
    with sqlite3.connect(subset) as db:
        ref = wio.Reference(db)
        initials = wio.match(('s02', 'h', 'pdmx', 'Blue Moon', 'J. Smith', 'usable', 'catalog_composer'), ref, {})
        alias = wio.match(('s03', 'h', 'maestro', 'Morning song', 'Bert Midway', 'usable', 'catalog_composer'), ref, {})
        strong = wio.match(('s01', 'h', 'pdmx', 'Home Free', 'Smith, John', 'usable', 'catalog_composer'), ref, {})
    assert initials[0] == alias[0] == strong[0] == 'candidate'
    assert initials[3] == alias[3] == set() and strong[3] == {SMITH}


def test_creator_identities_and_terms(env):
    index, subset, scores, out = env
    result = wio.prepare(index, subset, scores, out)
    ids = {k: (s, a) for k, s, a in q(out, 'SELECT creator_key,status,artist_id FROM creator_identities')}
    assert ids['john smith'] == ('disambiguated_by_work_relation', SMITH)
    assert ids['anna oldfield'] == ('single_person_candidate', OLD)
    assert ids['brown peter'] == ('ambiguous_persons', None) and ids['kiss'] == ('non_person_match', None)
    assert ids['nobody zed'] == ('no_match', None) and ids['cara living'][0] == 'disambiguated_by_work_relation'
    assert 'm' not in ids and result['selection']['creator_keys_skipped_short'] == 1
    assert sorted(json.loads(q(out, "SELECT candidate_ids_json FROM creator_identities WHERE creator_key='brown peter'")[0][0])) == sorted([BROWN, BROWN2])
    assert q(out, "SELECT person_namesakes,total_namesakes,source_count FROM creator_identities WHERE creator_key='john smith'") == [(2, 2, 2)]
    assert q(out, "SELECT raw,basis,dataset_id FROM source_creators WHERE creator_key='anna oldfield'") == [
        ('Anna Oldfield (1840-1900)', 'score_composer_claim', 'pdmx')]
    e = json.loads(q(out, "SELECT evidence_json FROM creator_identities WHERE creator_key='kiss'")[0][0])
    assert e['identity_status'] == 'candidate_unverified' and e['rights_clearance'] == 'not_established'
    terms = {k: (d, t, s) for k, d, t, s in q(out, 'SELECT creator_key,death_year,threshold_year,status FROM term_estimates')}
    assert terms['anna oldfield'] == (1900, 1970, 'likely_expired') and terms['john smith'] == (1990, 2060, 'likely_in_term')
    assert terms['cara living'] == (None, None, 'living_or_unknown_end') and set(terms) == {'anna oldfield', 'john smith', 'cara living', 'bert midway'}
    note = json.loads(q(out, "SELECT evidence_json FROM term_estimates WHERE creator_key='anna oldfield'")[0][0])
    assert note['estimate_not_clearance'] is True and 'United States' in note['jurisdiction_note']
    assert q(out, 'SELECT DISTINCT rule FROM term_estimates') == [('life_plus_70',)]


def test_unknown_term_status():
    artist = ('X', 'Person', None, '????', 1)
    assert wio.term_estimate('x', uid(1), artist, 2026)[5] == 'unknown'
    assert wio.term_estimate('x', uid(1), ('X', 'Person', None, None, 1), 2026)[5] == 'living_or_unknown_end'


def test_refusals(env, tmp_path, monkeypatch):
    index, subset, scores, out = env
    for name, kwargs in (('no_artists.sqlite', dict(artists=False)), ('truncated.sqlite', dict(truncated=True))):
        build_subset(tmp_path/name, index, scores, **kwargs)
        with pytest.raises(ValueError, match='artists passes|truncated'):
            wio.prepare(index, tmp_path/name, scores, out)
    build_subset(tmp_path/'other.sqlite', index, scores, work_sha='0'*64)
    with pytest.raises(ValueError, match='another work index'):
        wio.prepare(index, tmp_path/'other.sqlite', scores, out)
    build_subset(tmp_path/'other_scores.sqlite', index, scores, score_sha='0'*64)
    with pytest.raises(ValueError, match='another score metadata'):
        wio.prepare(index, tmp_path/'other_scores.sqlite', scores, out)
    build_subset(tmp_path/'stale.sqlite', index, scores, drop_key='anna oldfield')
    with pytest.raises(ValueError, match='creator key outside subset creator set'):
        wio.prepare(index, tmp_path/'stale.sqlite', scores, out)
    with pytest.raises(ValueError, match='positive'):
        wio.prepare(index, subset, scores, out, limit=0)
    assert not out.exists()
    out.write_text('keep')
    with pytest.raises(FileExistsError):
        wio.prepare(index, subset, scores, out)
    assert out.read_text() == 'keep'
    out.unlink()
    monkeypatch.setattr('samuged.work_identity_offline.shutil.disk_usage', lambda p: namedtuple('U', 'total used free')(0, 0, 10*1024**3))
    with pytest.raises(ValueError, match='reserve'):
        wio.prepare(index, subset, scores, out)
    assert not out.exists() and [p.name for p in tmp_path.iterdir() if p.name.startswith('tmp')] == []


def test_score_binding_mismatch(env):
    index, subset, scores, out = env
    with sqlite3.connect(scores) as db:
        db.execute("UPDATE score_metadata SET source_sha256='wrong' WHERE source_key='s05'")
    with pytest.raises(ValueError, match='binding'):
        wio.prepare(index, subset, scores, out)
    assert not out.exists()


def test_dataset_and_limit(env):
    index, subset, scores, out = env
    result = wio.prepare(index, subset, scores, out, dataset='lakh', limit=2)
    assert q(out, 'SELECT source_key FROM queue') == [('s04',), ('s07',)]
    assert result['selection'] == dict(dataset='lakh', limit=2, truncated=True, sources=2, creator_keys_skipped_short=0)
    assert json.loads(q(out, 'SELECT selection_json FROM provenance')[0][0])['truncated'] is True


def test_status_and_provenance(env):
    index, subset, scores, out = env
    wio.prepare(index, subset, scores, out)
    s = wio.status(out)
    assert s['sources'] == 12 and s['queue_status']['lakh'] == {'candidate': 1, 'no_namesake': 1, 'no_candidate': 1}
    assert (s['work_candidates'], s['candidate_sources'], s['distinct_works']) == (5, 5, 5)
    assert s['title_only_sources'] == 4 and s['title_only_rows'] == 3+3+50+2
    assert s['creator_identities']['disambiguated_by_work_relation'] == 3 and s['term_estimates']['likely_expired'] == 1
    inputs, dump, flags = q(out, 'SELECT inputs_json,dump_json,identity_verified||rights_clearance FROM provenance')[0]
    assert json.loads(inputs)['work_index']['sha256'] == file_digest(index) and flags == '0not_established'
    assert [r['archives'][0]['archive'] for r in json.loads(dump)['subset_provenance']] == ['work.tar.xz', 'artist.tar.xz']


def test_export(env, tmp_path, monkeypatch):
    index, subset, scores, out = env
    wio.prepare(index, subset, scores, out)
    target = tmp_path/'export.jsonl.gz'
    result = wio.export(out, target)
    assert result['lines'] == 12 and result['identity_verified'] is False
    with gzip.open(target, 'rt', encoding='utf-8') as f:
        lines = {r['source_key']: r for r in map(json.loads, f)}
    one = lines['s01']
    assert one['candidates'][0]['writers'][0]['name'] == 'John Smith' and one['candidates'][0]['title_namesake_count'] == 2
    assert one['dump_name'] == '20261003-001001' and one['rights_clearance'] == 'not_established' and one['policy'] == wio.POLICY
    assert {c['creator_key']: c['term_estimate']['status'] for c in one['creators']} == {'john smith': 'likely_in_term'}
    assert len(lines['s10']['title_only']) == 50 and lines['s05']['title_only'][0]['work_id'] == uid(2)
    assert lines['s05']['creators'][0]['identity_status'] == 'single_person_candidate'
    with pytest.raises(FileExistsError):
        wio.export(out, target)
    monkeypatch.setattr(wio, 'MB', 100)
    with pytest.raises(ValueError, match='max size'):
        wio.export(out, tmp_path/'small.jsonl.gz', max_output_mb=1)
    assert not (tmp_path/'small.jsonl.gz').exists()


def test_group_gets_no_term_estimate(env, tmp_path):
    index, subset, scores, _ = env
    out = sqlite3.connect(tmp_path/'identities.sqlite'); out.executescript(wio.SCHEMA)
    creators = {'kiss': dict(raw=['Kiss'], sources={'s07'}, datasets={'lakh': 1})}
    with sqlite3.connect(subset) as sub:
        wio.identify(out, sub, creators, {'kiss': {KISS}}, {})
    status, artist_id, encoded = out.execute("SELECT status,artist_id,evidence_json FROM creator_identities").fetchone()
    assert (status, artist_id) == ('disambiguated_by_work_relation', KISS)
    assert json.loads(encoded)['term_estimate_skipped'] == 'artist_type_not_person'
    assert out.execute('SELECT count(*) FROM term_estimates').fetchone()[0] == 0
    out.close()


def test_short_keys_counted_once(env, tmp_path):
    index, _, scores, out = env
    with sqlite3.connect(index) as db:
        db.execute("UPDATE queue SET creator='M.' WHERE source_key='s07'")
    build_subset(tmp_path/'s.sqlite', index, scores)
    result = wio.prepare(index, tmp_path/'s.sqlite', scores, out)
    assert result['selection']['creator_keys_skipped_short'] == 1


def test_alias_namesakes_carried(env, tmp_path):
    index, subset, scores, out = env
    with sqlite3.connect(subset) as db:
        db.execute("UPDATE name_namesakes SET alias_count=3 WHERE name_key='kiss'")
    wio.prepare(index, subset, scores, out)
    assert q(out, "SELECT person_namesakes,total_namesakes,alias_namesakes FROM creator_identities WHERE creator_key='kiss'") == [(0, 1, 3)]
    wio.export(out, tmp_path/'e.jsonl.gz')
    with gzip.open(tmp_path/'e.jsonl.gz', 'rt', encoding='utf-8') as f:
        record = next(r for r in map(json.loads, f) if r['source_key'] == 's07')
    assert record['creators'] == [dict(creator_key='kiss', basis='queue_creator', identity_status='non_person_match', artist_id=None,
                                       artist_name=None, alias_namesakes=3, term_estimate=None)]
