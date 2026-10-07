import hashlib
import io
import json
import os
import sqlite3
import tarfile
from collections import namedtuple

import pytest

from samuged import musicbrainz_fullexport as mfe
from samuged.dataset import file_digest


def gid(kind, n): return f'{kind:08x}-0000-4000-8000-{n:012d}'


def a(n): return gid(0xa, n)
def r(n): return gid(0xb, n)
def w(n): return gid(0xc, n)


def row(*values):
    def field(v):
        if v is None:
            return '\\N'
        return str(v).replace('\\', '\\\\').replace('\t', '\\t').replace('\n', '\\n').replace('\r', '\\r')
    return '\t'.join(map(field, values))+'\n'


def artist(n, name, sort, type_=1):
    return row(n, a(n), name, sort, None, None, None, None, None, None, type_, None, None, '', 0, None, 'f', None, None)


def recording(n, name, credit):
    return row(n, r(n), name, credit, 200000, '', 0, '2020-01-01 00:00:00+00', 'f')


def work(n, name):
    return row(n, w(n), name, 17, '', 0, None)


def rel(n, link, left, right):
    return row(n, link, left, right, 0, None, 0, '', '')


def link_type(n, entity0, entity1, name):
    return row(n, None, 0, gid(0xd, n), entity0, entity1, name, 'description', 'phrase', 'reverse', 'long', None, 'f', 'f', 0, 0)


# Goldsmith 1, Kiss 2 (group), Stanley 3, Simmons 4, unreferenced 5, backslash name 6, other writer 8.
ARTISTS = [artist(1, 'Jerry Goldsmith', 'Goldsmith, Jerry'), artist(2, 'Kiss', 'Kiss', 2), artist(3, 'Paul Stanley', 'Stanley, Paul'),
           artist(4, 'Gene Simmons', 'Simmons, Gene'), artist(5, 'Nobody Referenced', 'Referenced, Nobody'),
           artist(6, 'Back\\Slash', 'Back\\Slash'), artist(8, 'Other Writer', 'Writer, Other')]
CREDITS = [row(1, 'Jerry Goldsmith', 1, 2, None, 0, gid(0xe, 1)), row(2, 'Kiss', 1, 5, None, 0, gid(0xe, 2)),
           row(3, 'Paul Stanley & Gene Simmons', 2, 1, None, 0, gid(0xe, 3)), row(4, 'Back\\Slash', 1, 1, None, 0, gid(0xe, 4)),
           row(5, 'Nobody Referenced', 1, 1, None, 0, gid(0xe, 5))]
CREDIT_NAMES = [row(1, 0, 1, 'Jerry Goldsmith', ''), row(2, 0, 2, 'Kiss', ''), row(3, 1, 4, 'Gene Simmons', ''),
                row(3, 0, 3, 'Paul Stanley', ' & '), row(4, 0, 6, 'Back\\Slash', ''), row(5, 0, 5, 'Nobody Referenced', '')]
# Home<TAB>Free and a second Goldsmith take, a disagreeing credit, Kiss, a recording without a work, an unqueued title.
RECORDINGS = [recording(1, 'Home\tFree', 1), recording(7, 'Home Free', 1), recording(2, 'Home Free', 4),
              recording(3, 'Detroit Rock City', 2), recording(4, 'Lonely Song', 3), recording(5, 'Not In Queue', 2)]
WORKS = [work(1, 'Home Free'), work(2, 'Detroit Rock City'), work(3, 'Unused Work'), work(4, 'Home Free (reprise)'),
         work(5, 'Not In Queue')]
LINK_TYPES = [link_type(278, 'recording', 'work', 'performance'), link_type(168, 'artist', 'work', 'composer'),
              link_type(167, 'artist', 'work', 'writer'), link_type(165, 'artist', 'work', 'lyricist'),
              link_type(170, 'artist', 'work', 'dedication'), link_type(999, 'artist', 'artist', 'member of band')]
LINKS = [row(10, 278, *[None]*6, 0, None, 'f'), row(11, 168, *[None]*6, 0, None, 'f'), row(12, 167, *[None]*6, 0, None, 'f'),
         row(13, 165, *[None]*6, 0, None, 'f'), row(14, 170, *[None]*6, 0, None, 'f'), row(15, 999, *[None]*6, 0, None, 'f')]
RECORDING_WORKS = [rel(1, 10, 1, 1), rel(2, 10, 7, 1), rel(3, 10, 7, 4), rel(4, 10, 2, 1), rel(5, 10, 3, 2), rel(6, 10, 5, 5)]
ARTIST_WORKS = [rel(1, 11, 1, 1), rel(2, 12, 8, 1), rel(3, 12, 3, 2), rel(4, 13, 4, 2), rel(5, 14, 5, 1), rel(6, 11, 5, 3),
                rel(7, 11, 1, 4)]
# Relationship tables come before the entities they reference, so member order is exercised.
TABLES = dict(l_artist_work=ARTIST_WORKS, l_recording_work=RECORDING_WORKS, artist=ARTISTS, artist_credit=CREDITS,
              artist_credit_name=CREDIT_NAMES, link=LINKS, link_type=LINK_TYPES, release=[row(1, 'Ignored', 'x')],
              recording=RECORDINGS, work=WORKS)
META = dict(TIMESTAMP=b'2026-10-07 00:21:48.263241+00\n', COPYING=b'CC0', README=b'readme', REPLICATION_SEQUENCE=b'189552\n',
            SCHEMA_SEQUENCE=b'31\n')
# key, title, creator, title_status
QUEUE = [('L01', 'Home Free', 'Jerry Goldsmith', 'usable'), ('L02', 'Home free!', 'J Goldsmith', 'usable'),
         ('L03', 'Detroit Rock City', 'Kiss', 'usable'), ('L04', 'Lonely Song', 'Gene Simmons, Paul Stanley', 'usable'),
         ('L05', 'Home Free', 'Nobody', 'usable'), ('L06', 'Unknown Tune', 'Kiss', 'usable'), ('L07', None, 'Kiss', 'missing'),
         ('L08', 'Home Free', 'Jerry Goldsmith', 'suspect_encoding'), ('L09', 'Home Free', None, 'usable')]


def build_archive(path, tables=None, meta=None, members=None):
    tables = TABLES if tables is None else tables
    content = dict(META, **(meta or {}))
    with tarfile.open(path, 'w:bz2') as tar:
        for name in members or [*content, *('mbdump/'+t for t in tables)]:
            data = content[name] if name in content else ''.join(tables[name[7:]]).encode()
            info = tarfile.TarInfo(name); info.size = len(data)
            tar.addfile(info, io.BytesIO(data))


def sums(export):
    archive = export/'mbdump.tar.bz2'
    (export/'SHA256SUMS').write_text(f'{"0"*64} *mbdump-cdstubs.tar.bz2\n'
                                     f'{hashlib.sha256(archive.read_bytes()).hexdigest()} *mbdump.tar.bz2\n')


def work_index(path, queue=QUEUE):
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE queue(source_key TEXT,source_sha256 TEXT,dataset_id TEXT,title TEXT,creator TEXT,query_kind TEXT,status TEXT,error TEXT,updated_on TEXT)')
        db.execute('CREATE TABLE track_metadata(source_key TEXT,title_status TEXT,creator_status TEXT,creator_basis TEXT,gaps_json TEXT,evidence_json TEXT)')
        db.executemany('INSERT INTO queue VALUES (?,?,?,?,?,?,?,?,?)', [(k, 'h'+k, 'lakh', t, c, 'recording', 'no_candidate', None, 'x')
                                                                         for k, t, c, _ in queue])
        db.execute("INSERT INTO queue VALUES ('P01','hP01','pdmx','Not In Queue','Kiss','work','pending',NULL,'x')")
        db.executemany('INSERT INTO track_metadata VALUES (?,?,?,?,?,?)', [(k, s, None, 'catalog_artist', '[]', '{}') for k, _, _, s in queue])


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr('samuged.musicbrainz_dump.shutil.disk_usage', lambda p: namedtuple('U', 'total used free')(0, 0, 20*1024**3))
    monkeypatch.setattr('samuged.musicbrainz_fullexport.shutil.which', lambda name: None)
    export = tmp_path/'20261007-002147'; export.mkdir()
    build_archive(export/'mbdump.tar.bz2'); sums(export)
    index = tmp_path/'v04.sqlite'
    work_index(index)
    return export, index, tmp_path/'recordings.sqlite'


def q(path, sql, *args):
    with sqlite3.connect(path) as db:
        return db.execute(sql, args).fetchall()


def test_unescape():
    assert mfe.unescape('\\N') is None and mfe.unescape('') == '' and mfe.unescape('plain') == 'plain'
    assert mfe.unescape('a\\tb\\\\c\\nd\\re\\bf\\fg\\vh') == 'a\tb\\c\nd\re\bf\fg\vh'
    assert mfe.unescape('\\\\N') == '\\N'
    for bad in ('\\x41', '\\1', 'tail\\'):
        with pytest.raises(ValueError, match='escape'):
            mfe.unescape(bad)


def test_prepare_filters_prunes_and_counts(env):
    export, index, out = env
    before = file_digest(index)
    result = mfe.prepare(export, index, out)
    assert file_digest(index) == before
    assert result['identity_verified'] is False and result['rights_clearance'] == 'not_established'
    assert result['title_count'] == 4 and result['titles_with_recordings'] == 3
    assert {g for (g,) in q(out, 'SELECT gid FROM recordings')} == {r(1), r(7), r(2), r(3), r(4)}
    assert q(out, f"SELECT name,title_norm FROM recordings WHERE gid='{r(1)}'") == [('Home\tFree', 'home free')]
    assert dict(q(out, 'SELECT * FROM title_namesakes')) == {'home free': 3, 'detroit rock city': 1, 'lonely song': 1,
                                                             'unknown tune': 0}
    assert {g for (g,) in q(out, 'SELECT gid FROM works')} == {w(1), w(2), w(4)}  # unused and unqueued works are gone
    assert {g for (g,) in q(out, 'SELECT gid FROM artists')} == {a(1), a(2), a(3), a(4), a(6), a(8)}  # artist 5 is gone
    assert q(out, f"SELECT name FROM artists WHERE gid='{a(6)}'") == [('Back\\Slash',)]
    assert set(q(out, 'SELECT work_gid,artist_gid,role FROM work_artists')) == {
        (w(1), a(1), 'composer'), (w(1), a(8), 'writer'), (w(2), a(3), 'writer'), (w(2), a(4), 'lyricist'), (w(4), a(1), 'composer')}
    assert set(q(out, 'SELECT recording_gid,work_gid,link_type FROM recording_works')) == {
        (r(1), w(1), 'performance'), (r(7), w(1), 'performance'), (r(7), w(4), 'performance'), (r(2), w(1), 'performance'),
        (r(3), w(2), 'performance')}
    credit, names = q(out, 'SELECT credit,names_json FROM artist_credits WHERE credit_id=3')[0]
    assert credit == 'Paul Stanley & Gene Simmons' and [n['artist_gid'] for n in json.loads(names)] == [a(3), a(4)]
    assert {c for (c,) in q(out, 'SELECT credit_id FROM artist_credits')} == {1, 2, 3, 4}
    assert not {t for (t,) in q(out, "SELECT name FROM sqlite_master WHERE name LIKE 's\\_%' ESCAPE '\\'")}
    policy, dump, inputs, flags = q(out, 'SELECT policy,dump_json,inputs_json,identity_verified||rights_clearance FROM provenance')[0]
    dump = json.loads(dump)
    assert policy == 'musicbrainz-fullexport-subset-v1' and flags == '0not_established'
    assert dump['export_name'] == '20261007-002147' and dump['archive'] == 'mbdump.tar.bz2'
    assert dump['sha256'] == hashlib.sha256((export/'mbdump.tar.bz2').read_bytes()).hexdigest()
    assert (dump['replication_sequence'], dump['schema_sequence'], dump['timestamp']) == (189552, 31, '2026-10-07 00:21:48.263241+00')
    assert dump['signature_status'] == 'signature_missing' and dump['decompressor'] == 'python-tarfile-bz2'
    assert dump['lines_read']['recording'] == 6 and dump['lines_read']['link_type'] == 6 and dump['truncated'] is False
    assert 'release' not in dump['lines_read']
    assert json.loads(inputs)['work_index']['sha256'] == before
    s = mfe.status(out)
    assert (s['recordings'], s['works'], s['artists'], s['work_artists'], s['recording_works']) == (5, 3, 6, 5, 5)


def test_hash_mismatch_refuses_before_reading(env, monkeypatch):
    export, index, out = env
    (export/'SHA256SUMS').write_text('0'*64+'  mbdump.tar.bz2\n')
    monkeypatch.setattr('samuged.musicbrainz_fullexport.tarfile.open', lambda *a, **k: pytest.fail('tar read before hash check'))
    with pytest.raises(ValueError, match='sha256 mismatch'):
        mfe.prepare(export, index, out)
    (export/'SHA256SUMS').write_text('')
    with pytest.raises(ValueError, match='missing from SHA256SUMS'):
        mfe.prepare(export, index, out)
    assert not out.exists() and [p.name for p in out.parent.iterdir() if p.name.startswith('tmp')] == []


def test_missing_metadata_member_and_table(env):
    export, index, out = env
    build_archive(export/'mbdump.tar.bz2', members=['TIMESTAMP', 'REPLICATION_SEQUENCE', 'mbdump/recording', 'SCHEMA_SEQUENCE'])
    sums(export)
    with pytest.raises(ValueError, match='metadata members'):
        mfe.prepare(export, index, out)
    build_archive(export/'mbdump.tar.bz2', tables={k: v for k, v in TABLES.items() if k != 'link'})
    sums(export)
    with pytest.raises(ValueError, match='dump member missing: link'):
        mfe.prepare(export, index, out)
    assert not out.exists()


def test_existing_output_and_reserve(env, monkeypatch):
    export, index, out = env
    out.write_text('keep')
    with pytest.raises(FileExistsError):
        mfe.prepare(export, index, out)
    assert out.read_text() == 'keep'
    out.unlink()
    monkeypatch.setattr('samuged.musicbrainz_dump.shutil.disk_usage', lambda p: namedtuple('U', 'total used free')(0, 0, 10*1024**3))
    with pytest.raises(ValueError, match='reserve'):
        mfe.prepare(export, index, out)
    assert not out.exists()


def test_column_count_long_line_and_invalid_mbid(env, monkeypatch):
    export, index, out = env
    build_archive(export/'mbdump.tar.bz2', tables=dict(TABLES, work=WORKS+['1\tonly two\n']))
    sums(export)
    with pytest.raises(ValueError, match='work has an unexpected column count'):
        mfe.prepare(export, index, out)
    build_archive(export/'mbdump.tar.bz2'); sums(export)
    monkeypatch.setattr(mfe, 'LINE_LIMIT', 100)
    with pytest.raises(ValueError, match='exceeds 1 MiB'):
        mfe.prepare(export, index, out)
    monkeypatch.setattr(mfe, 'LINE_LIMIT', 1024*1024)
    build_archive(export/'mbdump.tar.bz2', tables=dict(TABLES, work=[row(1, 'not-a-uuid', 'Home Free', 17, '', 0, None)]+WORKS[1:]))
    sums(export)
    with pytest.raises(ValueError, match='MusicBrainz ID'):
        mfe.prepare(export, index, out)
    assert not out.exists()


def test_dangling_reference_refused(env):
    export, index, out = env
    build_archive(export/'mbdump.tar.bz2', tables=dict(TABLES, work=WORKS[1:]))
    sums(export)
    with pytest.raises(ValueError, match='dangling'):
        mfe.prepare(export, index, out)
    assert not out.exists()


def test_limit_marks_truncated(env):
    export, index, out = env
    result = mfe.prepare(export, index, out, limit=2)
    assert result['dump']['truncated'] is True and result['dump']['lines_read']['recording'] == 2
    assert result['recordings'] == 2
    with pytest.raises(ValueError, match='positive'):
        mfe.prepare(export, index, out.with_name('x.sqlite'), limit=0)


def test_decompressor_override(env, monkeypatch):
    export, index, out = env
    with pytest.raises(ValueError, match='absolute'):
        mfe.prepare(export, index, out, decompressor='bzip2 -dc')
    if not os.access('/usr/bin/bzip2', os.X_OK):
        pytest.skip('bzip2 unavailable')
    monkeypatch.setattr('samuged.musicbrainz_fullexport.tarfile.open', lambda fileobj, mode: (
        mode == 'r|' or pytest.fail('pure Python bz2 used')) and tarfile.TarFile.open(fileobj=fileobj, mode=mode))
    result = mfe.prepare(export, index, out, decompressor='/usr/bin/bzip2 -dc')
    assert result['dump']['decompressor'] == '/usr/bin/bzip2 -dc' and result['recordings'] == 5
    monkeypatch.setattr('samuged.musicbrainz_fullexport.shutil.which', lambda name: '/usr/bin/bzip2')
    assert mfe._command(None) == ['/usr/bin/bzip2', '-dc']


def test_failing_decompressor_refused(env):
    export, index, out = env
    if not os.access('/usr/bin/false', os.X_OK):
        pytest.skip('false unavailable')
    with pytest.raises((ValueError, tarfile.ReadError)):
        mfe.prepare(export, index, out, decompressor='/usr/bin/false')
    assert not out.exists()
