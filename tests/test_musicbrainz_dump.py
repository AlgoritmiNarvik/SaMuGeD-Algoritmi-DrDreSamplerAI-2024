import hashlib
import io
import json
import sqlite3
import tarfile
from collections import namedtuple

import pytest

from samuged import musicbrainz_dump as mb
from samuged.musicbrainz_dump import add_artists, creator_search_names, name_key, prepare, status

GOLDSMITH = 'db403e3d-0000-4000-8000-000000000001'
OTHER = 'db403e3d-0000-4000-8000-000000000002'
SCHUBERT = 'db403e3d-0000-4000-8000-000000000003'
UNRELATED = 'db403e3d-0000-4000-8000-000000000004'


def uid(n): return f'2f0b1b3a-0000-4000-8000-{n:012d}'


def work(n, title, aliases=(), relations=()):
    return dict(id=uid(n), title=title, type='Song', language='eng', languages=['eng'], iswcs=[], disambiguation='',
                aliases=[{'name': a, 'sort-name': a, 'type': None, 'locale': None, 'primary': None} for a in aliases],
                relations=list(relations), tags=[{'name': 'x', 'count': 1}], genres=[{'name': 'rock'}],
                rating={'value': 5, 'votes-count': 1}, annotation='note', **{'type-id': None})


COMPOSER = {'target-type': 'artist', 'type': 'composer', 'begin': None, 'end': None, 'attributes': [], 'direction': 'backward',
            'artist': {'id': GOLDSMITH, 'name': 'Jerry Goldsmith', 'sort-name': 'Goldsmith, Jerry', 'type': 'Person',
                       'country': 'US', 'disambiguation': 'American score composer'}}
PERFORMANCE = {'target-type': 'recording', 'type': 'performance', 'recording': {'id': uid(900), 'title': 'Home Free'}}
URL = {'target-type': 'url', 'type': 'download for free', 'url': {'id': uid(901), 'resource': 'https://imslp.org/wiki/X'}}
WORKS = [work(1, 'Home Free', relations=[COMPOSER, PERFORMANCE, PERFORMANCE, URL]),
         work(2, 'Something Else', aliases=['Café Tune']),
         work(3, 'Home Free', aliases=['Ignored']),
         work(4, 'Nothing Matches'),
         work(5, 'Other Title', aliases=['Home Free'])]


def artist(id_, name, sort_name, type_='Person', aliases=()):
    return {'id': id_, 'name': name, 'sort-name': sort_name, 'type': type_, 'gender': 'Male', 'country': 'AT',
            'disambiguation': '', 'life-span': {'begin': '1797-01-31', 'end': '1828-11-19', 'ended': True},
            'aliases': [{'name': a, 'sort-name': a} for a in aliases], 'isnis': ['0000000121442780'], 'ipis': [],
            'tags': [{'name': 'classical'}], 'genres': [], 'rating': {'value': 4}, 'annotation': 'x',
            'area': {'name': 'Austria'}, 'begin-area': {'name': 'Vienna'},
            'relations': [{'target-type': 'url', 'type': 'wikidata', 'url': {'resource': 'https://www.wikidata.org/wiki/Q7312'}}]}


ARTISTS = [artist(GOLDSMITH, 'Jerry Goldsmith', 'Goldsmith, Jerry'),
           artist(SCHUBERT, 'Franz Schübert', 'Schübert, Franz'),
           artist(OTHER, 'Franz Schubert', 'Schubert, Franz', type_='Group'),
           artist(UNRELATED, 'Nobody Here', 'Here, Nobody', aliases=['Turlough OConnor'])]


def archive(path, entity, lines, members=('TIMESTAMP', 'COPYING', 'README', 'REPLICATION_SEQUENCE', 'SCHEMA_SEQUENCE'), **meta):
    content = dict(TIMESTAMP=f'2026-10-03 0{len(entity)}:10:01.000000+00\n'.encode(), COPYING=b'CC0', README=b'readme',
                   REPLICATION_SEQUENCE=b'123\n', SCHEMA_SEQUENCE=b'30\n') | meta
    with tarfile.open(path, 'w:xz') as tar:
        for name in [*members, 'mbdump/'+entity]:
            data = content[name] if name in content else ''.join(json.dumps(x)+'\n' for x in lines).encode()
            info = tarfile.TarInfo(name); info.size = len(data)
            tar.addfile(info, io.BytesIO(data))


def sums(dumps):
    (dumps/'SHA256SUMS').write_text(''.join(f'{hashlib.sha256(p.read_bytes()).hexdigest()} *{p.name}\n'
                                            for p in sorted(dumps.glob('*.tar.xz'))))


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr('samuged.musicbrainz_dump.shutil.disk_usage', lambda p: namedtuple('Usage', 'total used free')(0, 0, 20*1024**3))
    dumps = tmp_path/'dumps'; dumps.mkdir()
    archive(dumps/'work.tar.xz', 'work', WORKS)
    archive(dumps/'artist.tar.xz', 'artist', ARTISTS)
    sums(dumps)
    index = tmp_path/'v04.sqlite'
    with sqlite3.connect(index) as db:
        db.execute('CREATE TABLE queue(source_key TEXT,source_sha256 TEXT,dataset_id TEXT,title TEXT,creator TEXT,query_kind TEXT,status TEXT)')
        db.executemany('INSERT INTO queue VALUES (?,?,?,?,?,?,?)', [('a', 'h', 'pdmx', 'Home  free!', None, 'work', 'missing_labels'),
            ('b', 'h', 'pdmx', 'Cafe tune', 'Schubert, Franz', 'work', 'pending'), ('c', 'h', 'lakh', None, 'Kiss', 'recording', 'pending'),
            ('d', 'h', 'pdmx', 'Never in dump', None, 'work', 'missing_labels'),
            ('e', 'h', 'lakh', None, 'M', 'recording', 'pending'), ('f', 'h', 'lakh', None, 'J. S.', 'recording', 'pending'),
            ('g', 'h', 'lakh', None, 'Seal', 'recording', 'pending'), ('h', 'h', 'lakh', None, 'Abc', 'recording', 'pending')])
    scores = tmp_path/'scores.sqlite'
    with sqlite3.connect(scores) as db:
        db.execute('CREATE TABLE score_metadata(source_key TEXT,source_sha256 TEXT,score_id TEXT,source_url TEXT,composer_claim TEXT,review_required INTEGER,evidence_json TEXT)')
        db.executemany('INSERT INTO score_metadata VALUES (?,?,?,?,?,?,?)', [(k, 'h', k, None, c, 1, '{}') for k, c in
            [('a', "Turlough O'Connor (1670-1738)"), ('b', 'Traditional'), ('c', '?'), ('d', None)]])
    return dumps, index, scores, tmp_path/'subset.sqlite'


def rows(path, sql):
    with sqlite3.connect(path) as db:
        return db.execute(sql).fetchall()


def test_creator_search_names():
    assert creator_search_names("Turlough O'Connor (1670-1738)") == ["Turlough O'Connor"]
    assert creator_search_names('John Stanley, 1712-1786') == ['John Stanley']
    assert creator_search_names('John Stanley1712-1786') == ['John Stanley']
    assert creator_search_names('Urheber: Johann Abraham Peter SchultErstbeleg: 1779 (Komponiert)Datum in der hier '
                                'transkribierten schriftlichen Quelle: 1792') == ['Johann Abraham Peter Schult']
    for raw in ('Urheber unbekanntDatum in der hier transkribierten schriftlichen Quelle: 1767', '?', 'Traditional', 'trad.',
                'anon.', '(Anonim)', 'Unknown', 'https://example.org/x', 'after Chief F. O\'Neill', '', None):
        assert creator_search_names(raw) == []
    assert len(creator_search_names('A'*300)[0]) == 120
    assert name_key('Goldsmith, Jerry') == name_key('Jerry Goldsmith') == 'goldsmith jerry'


def test_prepare_filters_projects_and_counts(env):
    dumps, index, scores, out = env
    before = index.read_bytes()
    result = prepare(dumps, index, scores, out)
    assert index.read_bytes() == before
    assert result['works_kept'] == 4 and result['title_count'] == 3 and result['lines_read'] == 5 and not result['truncated']
    assert result['identity_verified'] is False and result['rights_clearance'] == 'not_established'
    assert {r[0] for r in rows(out, 'SELECT work_id FROM works')} == {uid(1), uid(2), uid(3), uid(5)}
    namesakes = dict((t, (w, a)) for t, w, a in rows(out, 'SELECT * FROM title_namesakes'))
    assert namesakes == {'home free': (2, 1), 'cafe tune': (0, 1), 'never in dump': (0, 0)}
    assert ('cafe tune', uid(2), 'alias') in rows(out, 'SELECT * FROM work_titles')
    record = json.loads(rows(out, f"SELECT record_json FROM works WHERE work_id='{uid(1)}'")[0][0])
    assert not {'tags', 'genres', 'rating', 'annotation', 'type-id'} & set(record)
    assert record['artist_relations'][0]['artist']['id'] == GOLDSMITH and record['artist_relations'][0]['type'] == 'composer'
    assert record['url_relations'] == [{'type': 'download for free', 'resource': 'https://imslp.org/wiki/X'}]
    assert record['performance_count'] == 2 and record['recording_titles_sample'] == ['Home Free']
    creators = {r[0] for r in rows(out, 'SELECT name_key FROM creator_set')}
    assert creators == {'franz schubert', 'kiss', 'seal', 'abc', 'oconnor turlough'}  # 'm' and 'j s' dropped as short
    assert result['creator_keys_dropped_short'] == 2 and result['creator_count'] == 5
    assert rows(out, 'SELECT creator_keys_dropped_short FROM provenance') == [(2,)]
    prov = rows(out, 'SELECT policy,archives_json,timestamp,replication_sequence,schema_sequence,metadata_license,identity_verified,rights_clearance FROM provenance')
    assert len(prov) == 1 and prov[0][0] == 'musicbrainz-dump-subset-v1' and prov[0][3:] == (123, 30, 'CC0-1.0', 0, 'not_established')
    entry = json.loads(prov[0][1])[0]
    assert entry['archive'] == 'work.tar.xz' and entry['verified_against'] == 'SHA256SUMS' and entry['signature_status'] == 'signature_missing'


def test_artist_pass_and_refusal(env):
    dumps, index, scores, out = env
    prepare(dumps, index, scores, out)
    result = add_artists(dumps, out)
    assert result['artists_kept'] == 4 and result['identity_verified'] is False
    kept = {r[0] for r in rows(out, 'SELECT artist_id FROM artists')}
    assert kept == {GOLDSMITH, SCHUBERT, OTHER, UNRELATED}  # id, accent insensitive name, order insensitive name, alias
    namesakes = {k: c for k, *c in rows(out, 'SELECT * FROM name_namesakes')}
    assert namesakes['franz schubert'] == [1, 2, 0] and namesakes['oconnor turlough'] == [0, 0, 1]
    record = json.loads(rows(out, f"SELECT record_json FROM artists WHERE artist_id='{SCHUBERT}'")[0][0])
    assert record['life_span'] == {'begin': '1797-01-31', 'end': '1828-11-19', 'ended': True}
    assert not {'tags', 'genres', 'rating', 'annotation', 'area', 'begin-area'} & set(record)
    assert record['url_relations'][0]['type'] == 'wikidata'
    assert rows(out, 'SELECT creator_count,creator_keys_dropped_short FROM provenance') == [(5, 2), (5, 2)]
    assert status(out)['artists'] == 4
    snapshot = out.read_bytes()
    with pytest.raises(ValueError, match='provenance|already'):
        add_artists(dumps, out)
    assert out.read_bytes() == snapshot


def test_hash_mismatch_fails_before_reading(env, monkeypatch):
    dumps, index, scores, out = env
    (dumps/'SHA256SUMS').write_text('0'*64+' *work.tar.xz\n')
    monkeypatch.setattr('samuged.musicbrainz_dump.tarfile.open', lambda *a, **k: pytest.fail('tar read before hash check'))
    with pytest.raises(ValueError, match='sha256'):
        prepare(dumps, index, scores, out)
    (dumps/'SHA256SUMS').write_text('')
    with pytest.raises(ValueError, match='missing'):
        prepare(dumps, index, scores, out)
    assert not out.exists() and [p.name for p in out.parent.iterdir() if p.name.startswith('tmp')] == []


def test_missing_timestamp_fails(env):
    dumps, index, scores, out = env
    archive(dumps/'work.tar.xz', 'work', WORKS, members=('COPYING', 'REPLICATION_SEQUENCE', 'SCHEMA_SEQUENCE'))
    sums(dumps)
    with pytest.raises(ValueError, match='metadata members'):
        prepare(dumps, index, scores, out)
    assert not out.exists()


def test_limit_lines_and_oversized_line(env, monkeypatch):
    dumps, index, scores, out = env
    result = prepare(dumps, index, scores, out, limit=2)
    assert result['lines_read'] == 2 and result['truncated'] and result['works_kept'] == 2
    assert json.loads(rows(out, 'SELECT archives_json FROM provenance')[0][0])[0]['truncated'] is True
    out.unlink()
    assert mb.LINE_LIMITS == {'work': 16*1024*1024, 'artist': 64*1024*1024}
    monkeypatch.setitem(mb.LINE_LIMITS, 'work', 100)
    with pytest.raises(ValueError, match='line exceeds'):
        prepare(dumps, index, scores, out)
    assert not out.exists()
    monkeypatch.setitem(mb.LINE_LIMITS, 'work', 16*1024*1024)
    prepare(dumps, index, scores, out)
    snapshot = out.read_bytes()
    monkeypatch.setitem(mb.LINE_LIMITS, 'artist', 100)
    with pytest.raises(ValueError, match='line exceeds'):
        add_artists(dumps, out)
    assert out.read_bytes() == snapshot


def test_existing_output_and_storage_reserve(env, monkeypatch):
    dumps, index, scores, out = env
    out.write_text('keep')
    with pytest.raises(FileExistsError):
        prepare(dumps, index, scores, out)
    assert out.read_text() == 'keep'
    out.unlink()
    monkeypatch.setattr('samuged.musicbrainz_dump.shutil.disk_usage', lambda p: namedtuple('Usage', 'total used free')(0, 0, 10*1024**3))
    with pytest.raises(ValueError, match='reserve'):
        prepare(dumps, index, scores, out)
    assert not out.exists()


def test_invalid_mbid_fails_closed(env):
    dumps, index, scores, out = env
    archive(dumps/'work.tar.xz', 'work', [dict(WORKS[0], id='not-a-uuid')])
    sums(dumps)
    with pytest.raises(ValueError, match='UUID|MusicBrainz ID'):
        prepare(dumps, index, scores, out)
    assert not out.exists()


def test_artist_archive_from_another_dump_refused(env):
    dumps, index, scores, out = env
    prepare(dumps, index, scores, out)
    archive(dumps/'artist.tar.xz', 'artist', ARTISTS, REPLICATION_SEQUENCE=b'124\n')
    sums(dumps)
    snapshot = out.read_bytes()
    with pytest.raises(ValueError, match='another dump'):
        add_artists(dumps, out)
    assert out.read_bytes() == snapshot and status(out)['artists'] == 0


def test_signature_status_never_fails(env, monkeypatch):
    dumps = env[0]
    assert mb._signature(dumps) == 'signature_missing'
    (dumps/'SHA256SUMS.asc').write_text('not a signature')
    monkeypatch.setattr('samuged.musicbrainz_dump.shutil.which', lambda name: None)
    assert mb._signature(dumps) == 'gpg_unavailable'
    monkeypatch.setattr('samuged.musicbrainz_dump.shutil.which', lambda name: '/usr/bin/gpg')
    calls = []
    def run(args, **kwargs):
        calls.append(args)
        return namedtuple('Done', 'returncode')(calls.__len__() - 1)
    monkeypatch.setattr('samuged.musicbrainz_dump.subprocess.run', run)
    assert mb._signature(dumps) == 'verified' and mb._signature(dumps) == 'unverified_key_missing_or_failed'
    assert '--no-auto-key-retrieve' in calls[0]
    monkeypatch.setattr('samuged.musicbrainz_dump.subprocess.run', lambda *a, **k: (_ for _ in ()).throw(mb.subprocess.TimeoutExpired('gpg', 30)))
    assert mb._signature(dumps) == 'unverified_key_missing_or_failed'
