"""Verify the MusicBrainz Postgres full export and stream filter it into a local recording subset.

The subset holds the CC0 recordings whose normalized titles occur among the Lakh recording queue rows,
their artist credits, their linked works, the creator relations of those works and whole database
recording namesake counts. It never extracts the archive to disk, never executes or imports anything
from the export directory, never uses the network, never opens the mutable work index and never
promotes a title or name agreement to a verified identity or rights clearance.
"""
from __future__ import annotations
import argparse
from contextlib import closing, contextmanager
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import time

from .dataset import file_digest
from .musicbrainz_dump import CREATOR_TYPES, META, _reserve, _ro, _signature, _unchanged
from .work_identity import label, mbid, now

POLICY = 'musicbrainz-fullexport-subset-v1'
ARCHIVE = 'mbdump.tar.bz2'
LINE_LIMIT = 1024*1024
PAGES = 1048576  # 4 GiB at a fixed 4 KiB page size
BATCH, PROGRESS = 50000, 1000000
# Column count and kept positions per table. link_type is checked up to its name column only.
TABLES = {
    'recording': (9, (0, 1, 2, 3)),                 # id, gid, name, artist_credit
    'artist_credit': (7, (0, 1)),                   # id, name
    'artist_credit_name': (5, (0, 1, 2, 3, 4)),     # artist_credit, position, artist, name, join_phrase
    'artist': (19, (0, 1, 2, 3, 10)),               # id, gid, name, sort_name, type
    'l_recording_work': (9, (2, 3, 1)),             # entity0 recording, entity1 work, link
    'l_artist_work': (9, (2, 3, 1)),                # entity0 artist, entity1 work, link
    'link': (11, (0, 1)),                           # id, link_type
    'link_type': (7, (0, 4, 5, 6)),                 # id, entity_type0, entity_type1, name
    'work': (7, (0, 1, 2, 3)),                      # id, gid, name, type
}
AT_LEAST = {'link_type'}
_ESCAPES = {'\\': '\\', 't': '\t', 'n': '\n', 'r': '\r', 'b': '\b', 'f': '\f', 'v': '\v'}
_ESCAPE = re.compile(r'\\(.?)', re.S)
STAGING = '''
CREATE TABLE s_recording(id INTEGER PRIMARY KEY,gid TEXT,name TEXT,title_norm TEXT,artist_credit INTEGER);
CREATE TABLE s_artist_credit(id INTEGER PRIMARY KEY,name TEXT);
CREATE TABLE s_artist_credit_name(artist_credit INTEGER,position INTEGER,artist INTEGER,name TEXT,join_phrase TEXT);
CREATE TABLE s_artist(id INTEGER PRIMARY KEY,gid TEXT,name TEXT,sort_name TEXT,type INTEGER);
CREATE TABLE s_l_recording_work(recording INTEGER,work INTEGER,link INTEGER);
CREATE TABLE s_l_artist_work(artist INTEGER,work INTEGER,link INTEGER);
CREATE TABLE s_link(id INTEGER PRIMARY KEY,link_type INTEGER);
CREATE TABLE s_link_type(id INTEGER PRIMARY KEY,entity_type0 TEXT,entity_type1 TEXT,name TEXT);
CREATE TABLE s_work(id INTEGER PRIMARY KEY,gid TEXT,name TEXT,type INTEGER);
'''
SCHEMA = '''
CREATE TABLE provenance(policy TEXT,dump_json TEXT,inputs_json TEXT,title_count INTEGER,created_on TEXT,
    identity_verified INTEGER CHECK(identity_verified=0),rights_clearance TEXT CHECK(rights_clearance='not_established'));
CREATE TABLE recordings(recording_id INTEGER PRIMARY KEY,gid TEXT UNIQUE,name TEXT,title_norm TEXT,credit_id INTEGER);
CREATE INDEX recording_title ON recordings(title_norm,gid);
CREATE TABLE artist_credits(credit_id INTEGER PRIMARY KEY,name TEXT,credit TEXT,names_json TEXT);
CREATE TABLE artists(artist_id INTEGER PRIMARY KEY,gid TEXT UNIQUE,name TEXT,sort_name TEXT,type INTEGER);
CREATE TABLE recording_works(recording_id INTEGER,work_id INTEGER,recording_gid TEXT,work_gid TEXT,link_type TEXT);
CREATE INDEX recording_work_key ON recording_works(recording_id,link_type);
CREATE TABLE works(work_id INTEGER PRIMARY KEY,gid TEXT UNIQUE,name TEXT,type INTEGER);
CREATE TABLE work_artists(work_id INTEGER,artist_id INTEGER,work_gid TEXT,artist_gid TEXT,role TEXT);
CREATE INDEX work_artist_key ON work_artists(work_id,role);
CREATE TABLE title_namesakes(title_norm TEXT PRIMARY KEY,recording_count INTEGER);
'''


def unescape(field):
    """Decode one PostgreSQL COPY text field. The bare marker \\N is NULL."""
    if field == '\\N':
        return None
    if '\\' not in field:
        return field

    def replace(match):
        if match[1] not in _ESCAPES:
            raise ValueError('unsupported COPY escape')
        return _ESCAPES[match[1]]
    return _ESCAPE.sub(replace, field)


def _verified(export_dir: Path):
    """Hash the whole archive against SHA256SUMS before any tar member is read."""
    path = export_dir/ARCHIVE
    listed = {}
    for line in (export_dir/'SHA256SUMS').read_text(encoding='utf-8').splitlines():
        if match := re.fullmatch(r'([0-9a-f]{64}) [ *](\S+)', line.strip()):
            listed[match[2]] = match[1]
    if ARCHIVE not in listed:
        raise ValueError('archive missing from SHA256SUMS')
    handle = path.open('rb')
    try:
        digest = hashlib.sha256()
        for chunk in iter(lambda: handle.read(1024*1024), b''):
            digest.update(chunk)
        if digest.hexdigest() != listed[ARCHIVE]:
            raise ValueError('archive sha256 mismatch')
        handle.seek(0)
    except BaseException:
        handle.close(); raise
    stat = os.fstat(handle.fileno())
    return handle, dict(export_name=export_dir.resolve().name, archive=ARCHIVE, sha256=listed[ARCHIVE],
                        bytes=stat.st_size, verified_against='SHA256SUMS'), (stat.st_size, stat.st_mtime_ns)


def _command(decompressor):
    """An explicit decompressor must be an absolute executable path. Otherwise lbzip2 when present."""
    if decompressor is None:
        found = shutil.which('lbzip2')
        return [found, '-dc'] if found else None
    parts = shlex.split(decompressor) if isinstance(decompressor, str) else [str(x) for x in decompressor]
    if not parts or not os.path.isabs(parts[0]) or not os.access(parts[0], os.X_OK):
        raise ValueError('decompressor must be an absolute executable path')
    return parts


@contextmanager
def _tar(handle, command):
    if command is None:
        with tarfile.open(fileobj=handle, mode='r|bz2') as tar:
            yield tar
        return
    proc = subprocess.Popen(command, stdin=handle, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    try:
        with tarfile.open(fileobj=proc.stdout, mode='r|') as tar:
            yield tar
        while proc.stdout.read(1024*1024):  # Drain trailing padding so the child can exit.
            pass
        proc.stdout.close()
        if proc.wait() != 0:
            raise ValueError('decompressor failed')
    finally:
        if proc.poll() is None:
            proc.kill(); proc.wait()


def _rows(tar, member, table, state, limit, tables=None, at_least=None):
    """Yield the kept fields of one COPY text table, one line at a time."""
    tables = TABLES if tables is None else tables
    at_least = AT_LEAST if at_least is None else at_least
    count, keep = tables[table]
    reader = io.BufferedReader(tar.extractfile(member), 8*1024*1024)
    read = state['lines_read']
    while line := reader.readline(LINE_LIMIT+1):
        if len(line) > LINE_LIMIT:
            raise ValueError('dump line exceeds 1 MiB')
        if limit is not None and read[table] >= limit:
            state['truncated'] = True; break
        read[table] += 1; state['total'] += 1
        text = line.decode('utf-8')
        fields = (text[:-1] if text.endswith('\n') else text).split('\t')
        if len(fields) < count if table in at_least else len(fields) != count:
            raise ValueError(f'{table} has an unexpected column count')
        yield [unescape(fields[i]) for i in keep]
        if state['total'] % PROGRESS == 0:
            print(json.dumps(dict(lines=state['total'], table=table, kept_recordings=state['kept'],
                  elapsed=round(time.monotonic()-state['started'], 1))), file=sys.stderr, flush=True)


def _integer(value):
    return None if value is None else int(value)


def _load(db, tar, titles, counts, state, limit):
    meta, seen = {}, set()
    for member in tar:  # Member names are compared, never used as paths.
        if member.name in META and member.isfile() and member.size <= 4096:
            meta[member.name] = tar.extractfile(member).read(4096).decode('utf-8').strip()
            continue
        if not member.name.startswith('mbdump/'):
            continue
        if set(META) - set(meta):
            raise ValueError('dump metadata members missing')
        table = member.name[len('mbdump/'):]
        if table not in TABLES:
            continue
        if table in seen or not member.isfile():
            raise ValueError(f'unexpected member {member.name}')
        seen.add(table)
        buffer = []
        for fields in _rows(tar, member, table, state, limit):
            if table == 'recording':
                key = label(fields[2] or '')
                if key not in titles:
                    continue
                counts[key] += 1; state['kept'] += 1
                buffer.append((int(fields[0]), mbid(fields[1]), fields[2], key, _integer(fields[3])))
            elif table == 'artist_credit_name':
                buffer.append((int(fields[0]), int(fields[1]), int(fields[2]), fields[3], fields[4]))
            elif table in {'artist', 'work'}:
                buffer.append((int(fields[0]), fields[1], *fields[2:-1], _integer(fields[-1])))
            elif table in {'l_recording_work', 'l_artist_work', 'link'}:
                buffer.append(tuple(map(int, fields)))
            else:  # artist_credit, link_type
                buffer.append((int(fields[0]), *fields[1:]))
            if len(buffer) >= BATCH:
                db.executemany(f'INSERT INTO s_{table} VALUES ({",".join("?"*len(buffer[0]))})', buffer); buffer.clear()
        if buffer:
            db.executemany(f'INSERT INTO s_{table} VALUES ({",".join("?"*len(buffer[0]))})', buffer)
    if set(META) - set(meta):
        raise ValueError('dump metadata members missing')
    if missing := sorted(set(TABLES) - seen):
        raise ValueError('dump member missing: '+', '.join(missing))
    return dict(timestamp=meta['TIMESTAMP'], replication_sequence=int(meta['REPLICATION_SEQUENCE']),
                schema_sequence=int(meta['SCHEMA_SEQUENCE']))


def _one(db, sql, *args):
    return db.execute(sql, args).fetchone()[0]


def _prune(db, strict):
    """Resolve link type names, keep only rows reachable from kept recordings and drop the staging tables."""
    db.execute('CREATE INDEX s_rw ON s_l_recording_work(recording)')
    db.execute('CREATE INDEX s_aw ON s_l_artist_work(work)')
    db.execute('CREATE INDEX s_acn ON s_artist_credit_name(artist_credit,position)')
    db.execute('INSERT INTO recordings SELECT id,gid,name,title_norm,artist_credit FROM s_recording')
    db.execute('''INSERT INTO recording_works SELECT r.id,w.id,r.gid,mbid(w.gid),t.name
        FROM s_recording r JOIN s_l_recording_work x ON x.recording=r.id JOIN s_link l ON l.id=x.link
        JOIN s_link_type t ON t.id=l.link_type JOIN s_work w ON w.id=x.work ORDER BY r.id,w.id''')
    linked = _one(db, 'SELECT count(*) FROM s_l_recording_work WHERE recording IN (SELECT id FROM s_recording)')
    if strict and linked != _one(db, 'SELECT count(*) FROM recording_works'):
        raise ValueError('recording work relation with a dangling reference')
    if _one(db, '''SELECT count(*) FROM s_link_type WHERE id IN (SELECT l.link_type FROM s_l_recording_work x
            JOIN s_link l ON l.id=x.link WHERE x.recording IN (SELECT id FROM s_recording))
            AND (entity_type0!='recording' OR entity_type1!='work')'''):
        raise ValueError('recording work link type has unexpected entity types')
    db.execute('''INSERT INTO works SELECT id,gid,name,type FROM s_work
        WHERE id IN (SELECT work_id FROM recording_works) ORDER BY id''')
    roles = sorted(CREATOR_TYPES)
    marks = ','.join('?'*len(roles))
    creator = f'''FROM s_l_artist_work x JOIN works w ON w.work_id=x.work JOIN s_link l ON l.id=x.link
        JOIN s_link_type t ON t.id=l.link_type WHERE t.name IN ({marks})'''
    if _one(db, f"SELECT count(*) {creator} AND (t.entity_type0!='artist' OR t.entity_type1!='work')", *roles):
        raise ValueError('artist work link type has unexpected entity types')
    db.execute(f'''INSERT INTO work_artists SELECT x.work,x.artist,w.gid,mbid(a.gid),t.name
        FROM s_l_artist_work x JOIN works w ON w.work_id=x.work JOIN s_artist a ON a.id=x.artist
        JOIN s_link l ON l.id=x.link JOIN s_link_type t ON t.id=l.link_type WHERE t.name IN ({marks})
        ORDER BY x.work,x.artist,t.name''', roles)
    if strict and _one(db, f'SELECT count(*) {creator}', *roles) != _one(db, 'SELECT count(*) FROM work_artists'):
        raise ValueError('work artist relation with a dangling reference')
    credits = 'SELECT DISTINCT credit_id FROM recordings WHERE credit_id IS NOT NULL'
    if strict and _one(db, f'SELECT count(*) FROM ({credits}) WHERE credit_id NOT IN (SELECT id FROM s_artist_credit)'):
        raise ValueError('recording with a dangling artist credit')
    db.execute(f'''INSERT INTO artists SELECT id,gid,name,sort_name,type FROM s_artist WHERE id IN (
        SELECT artist FROM s_artist_credit_name WHERE artist_credit IN ({credits}) UNION SELECT artist_id FROM work_artists)
        ORDER BY id''')
    if strict and _one(db, f'''SELECT count(*) FROM s_artist_credit_name WHERE artist_credit IN ({credits})
            AND artist NOT IN (SELECT artist_id FROM artists)'''):
        raise ValueError('artist credit with a dangling artist')
    batch = []

    def add(credit, parts):
        name = (db.execute('SELECT name FROM s_artist_credit WHERE id=?', (credit,)).fetchone() or (None,))[0]
        batch.append((credit, name, ''.join(p['name']+(p['join_phrase'] or '') for p in parts),
                      json.dumps(parts, ensure_ascii=False)))
        if len(batch) >= BATCH:
            db.executemany('INSERT INTO artist_credits VALUES (?,?,?,?)', batch); batch.clear()
    current, parts = None, []
    for credit, position, gid, name, join in db.execute(f'''SELECT c.artist_credit,c.position,a.gid,c.name,c.join_phrase
            FROM s_artist_credit_name c LEFT JOIN artists a ON a.artist_id=c.artist
            WHERE c.artist_credit IN ({credits}) ORDER BY c.artist_credit,c.position'''):
        if credit != current:
            if current is not None:
                add(current, parts)
            current, parts = credit, []
        parts.append(dict(position=position, artist_gid=None if gid is None else mbid(gid), name=name, join_phrase=join))
    if current is not None:
        add(current, parts)
    db.executemany('INSERT INTO artist_credits VALUES (?,?,?,?)', batch)
    if strict and _one(db, f'SELECT count(*) FROM ({credits}) WHERE credit_id NOT IN (SELECT credit_id FROM artist_credits)'):
        raise ValueError('artist credit without credited names')
    for table in ('s_recording', 's_artist_credit', 's_artist_credit_name', 's_artist', 's_l_recording_work',
                  's_l_artist_work', 's_link', 's_link_type', 's_work'):
        db.execute(f'DROP TABLE {table}')


def prepare(export_dir: Path, work_index: Path, output: Path, *, limit=None, decompressor=None):
    """Build the recording subset once. Inputs stay read only and the archive is verified first."""
    if limit is not None and (type(limit) is not int or limit < 1):
        raise ValueError('limit must be a positive integer')
    if output.exists() or output.is_symlink():
        raise FileExistsError(output)
    if not output.parent.is_dir():
        raise ValueError('output directory must exist')
    _reserve(output.parent)
    command = _command(decompressor)
    inputs = dict(work_index=dict(path=str(work_index), sha256=file_digest(work_index)))
    with closing(_ro(work_index)) as db:
        titles = {t for (raw,) in db.execute("SELECT title FROM queue WHERE query_kind='recording'")
                  for t in [label(raw if isinstance(raw, str) else '')] if t}
    handle, dump, stamp = _verified(export_dir)
    dump.update(signature_status=_signature(export_dir),
                decompressor=' '.join(command) if command else 'python-tarfile-bz2')
    started = time.monotonic()
    state = dict(lines_read={t: 0 for t in TABLES}, total=0, kept=0, truncated=False, started=started)
    counts = {t: 0 for t in titles}
    with handle, tempfile.TemporaryDirectory(dir=output.parent) as temp:
        staging, final = Path(temp)/'staging.sqlite', Path(temp)/'subset.sqlite'
        with closing(sqlite3.connect(staging)) as db:
            db.execute('PRAGMA page_size=4096'); db.execute(f'PRAGMA max_page_count={PAGES}')
            db.execute('PRAGMA synchronous=OFF'); db.execute('PRAGMA journal_mode=OFF')
            db.create_function('mbid', 1, mbid, deterministic=True)
            db.executescript(STAGING+SCHEMA)
            with _tar(handle, command) as tar:
                dump.update(_load(db, tar, titles, counts, state, limit))
            _unchanged(handle, stamp)
            try:
                _prune(db, strict=not state['truncated'])
            except sqlite3.OperationalError as exc:
                if 'user-defined function' in str(exc):
                    raise ValueError('invalid MusicBrainz ID') from exc
                raise
            db.executemany('INSERT INTO title_namesakes VALUES (?,?)', sorted(counts.items()))
            dump.update(lines_read=state['lines_read'], truncated=state['truncated'])
            if file_digest(work_index) != inputs['work_index']['sha256']:
                raise ValueError('input changed')
            db.execute('INSERT INTO provenance VALUES (?,?,?,?,?,0,?)', (POLICY, json.dumps(dump, ensure_ascii=False),
                       json.dumps(inputs), len(titles), now(), 'not_established'))
            db.commit()
            if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise ValueError('subset integrity check failed')
            _reserve(output.parent)
            db.execute('VACUUM INTO ?', (str(final),))
        os.link(final, output)  # Fails rather than overwrite an output created meanwhile.
    result = status(output)
    result.update(elapsed_seconds=round(time.monotonic()-started, 1), output_sha256=file_digest(output),
                  output_bytes=output.stat().st_size)
    return result


def status(subset: Path):
    with closing(_ro(subset)) as db:
        def count(sql): return _one(db, sql)
        policy, dump, inputs, titles = db.execute('SELECT policy,dump_json,inputs_json,title_count FROM provenance').fetchone()
        return dict(policy=policy, dump=json.loads(dump), inputs=json.loads(inputs), title_count=titles,
                    recordings=count('SELECT count(*) FROM recordings'),
                    titles_with_recordings=count('SELECT count(*) FROM title_namesakes WHERE recording_count>0'),
                    artist_credits=count('SELECT count(*) FROM artist_credits'), artists=count('SELECT count(*) FROM artists'),
                    recording_works=count('SELECT count(*) FROM recording_works'), works=count('SELECT count(*) FROM works'),
                    work_artists=count('SELECT count(*) FROM work_artists'),
                    identity_verified=False, rights_clearance='not_established')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    build = commands.add_parser('prepare')
    build.add_argument('--export', type=Path, required=True); build.add_argument('--work-index', type=Path, required=True)
    build.add_argument('--output', type=Path, required=True); build.add_argument('--limit', type=int)
    build.add_argument('--decompressor')
    commands.add_parser('status').add_argument('--subset', type=Path, required=True)
    args = parser.parse_args()
    if args.command == 'prepare':
        result = prepare(args.export, args.work_index, args.output, limit=args.limit, decompressor=args.decompressor)
    else:
        result = status(args.subset)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
