"""Verify MusicBrainz JSON dumps and stream filter them into a small local reference subset.

The subset holds CC0 work and artist records whose normalized titles or creator names occur in
the work identity queue, plus whole dump namesake counts. It never extracts an archive to disk,
never executes or imports anything from the dump directory, never uses the network, never opens
the mutable work index and never promotes a title or name agreement to a verified identity or
rights clearance. Records in the subset are reference data, not matches.
"""
from __future__ import annotations
import argparse
from contextlib import closing
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import time

from .dataset import file_digest
from .track_metadata import creator_kind
from .work_identity import label, mbid, now

POLICY = 'musicbrainz-dump-subset-v1'
LICENSE, LICENSE_URL = 'CC0-1.0', 'https://musicbrainz.org/doc/About/Data_License'
# Measured on the 2026-10-03 dump: longest work line 1.6 MiB, longest artist line 48.7 MiB.
LINE_LIMITS = {'work': 16*1024*1024, 'artist': 64*1024*1024}
RESERVE = 10.75*1024**3
PAGES = 524288  # 2 GiB at a fixed 4 KiB page size
META = ('TIMESTAMP', 'REPLICATION_SEQUENCE', 'SCHEMA_SEQUENCE')
CREATOR_TYPES = {'composer', 'writer', 'lyricist', 'librettist', 'arranger', 'orchestrator',
                 'translator', 'instrument arranger', 'vocal arranger'}
UNATTRIBUTED = re.compile(r'\b(unbekannt|unknown|unattributed|anon|trad)\w*')
SCHEMA = '''
CREATE TABLE provenance(policy TEXT,dump_name TEXT,archives_json TEXT,timestamp TEXT,replication_sequence INTEGER,
    schema_sequence INTEGER,inputs_json TEXT,title_count INTEGER,creator_count INTEGER,metadata_license TEXT,
    metadata_license_url TEXT,identity_verified INTEGER,rights_clearance TEXT,created_on TEXT,creator_keys_dropped_short INTEGER);
CREATE TABLE title_set(normalized_title TEXT PRIMARY KEY);
CREATE TABLE creator_set(name_key TEXT PRIMARY KEY);
CREATE TABLE works(work_id TEXT PRIMARY KEY,title TEXT,normalized_title TEXT,type TEXT,language TEXT,record_json TEXT);
CREATE TABLE work_titles(normalized_title TEXT,work_id TEXT REFERENCES works,kind TEXT CHECK(kind IN ('title','alias')));
CREATE INDEX work_title_key ON work_titles(normalized_title);
CREATE TABLE title_namesakes(normalized_title TEXT PRIMARY KEY,work_count INTEGER,alias_count INTEGER);
CREATE TABLE artists(artist_id TEXT PRIMARY KEY,name TEXT,sort_name TEXT,name_key TEXT,type TEXT,begin TEXT,end TEXT,
    ended INTEGER,country TEXT,record_json TEXT);
CREATE TABLE artist_names(name_key TEXT,artist_id TEXT REFERENCES artists,kind TEXT CHECK(kind IN ('name','sort_name','alias')));
CREATE INDEX artist_name_key ON artist_names(name_key);
CREATE TABLE name_namesakes(name_key TEXT PRIMARY KEY,person_count INTEGER,total_count INTEGER,alias_count INTEGER);
'''


def _s(value): return value if isinstance(value, str) else None
def _l(value): return value if isinstance(value, list) else []
def _d(value): return value if isinstance(value, dict) else {}


def name_key(text):
    """Order insensitive name key, so 'Goldsmith, Jerry' and 'Jerry Goldsmith' agree."""
    return ' '.join(sorted(label(_s(text) or '').split()))


def creator_search_names(raw):
    """Conservative cleaned search names from a raw upstream composer claim, or []."""
    if not _s(raw) or UNATTRIBUTED.search(label(raw)) or re.search(r'https?:|www\.', raw, re.I):
        return []
    text = raw
    if 'Urheber:' in text:
        text = re.split(r'Erstbeleg|Datum', text.split('Urheber:', 1)[1], maxsplit=1)[0]
    text = re.sub(r'\([^()]*\d{3,4}[^()]*\)', ' ', text)
    text = re.sub(r'[\s,;]*(?:c\.\s*)?\d{3,4}(?:\s*[-–]\s*(?:c\.\s*)?\d{3,4})?\s*$', '', text)
    text = ' '.join(text.split()).strip(' ,;:-–')[:120].strip()
    if not label(text) or creator_kind(text) != 'named_claim':
        return []
    return [text]


def _ro(path):
    return sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro', uri=True)


def _reserve(directory):
    if shutil.disk_usage(directory).free < RESERVE:
        raise ValueError('10 GiB storage reserve required')


def _signature(dumps):
    asc = dumps/'SHA256SUMS.asc'
    if not asc.is_file():
        return 'signature_missing'
    gpg = shutil.which('gpg')
    if not gpg:
        return 'gpg_unavailable'
    try:  # Keys are never fetched; a missing key leaves the signature unverified.
        done = subprocess.run([gpg, '--batch', '--no-auto-key-retrieve', '--verify', str(asc), str(dumps/'SHA256SUMS')],
                              capture_output=True, timeout=30, check=False)
    except (OSError, subprocess.SubprocessError):
        return 'unverified_key_missing_or_failed'
    return 'verified' if done.returncode == 0 else 'unverified_key_missing_or_failed'


def _verified(dumps, entity):
    """Hash the whole archive against SHA256SUMS before any tar member is read."""
    path = dumps/f'{entity}.tar.xz'
    listed = {}
    for line in (dumps/'SHA256SUMS').read_text(encoding='utf-8').splitlines():
        if match := re.fullmatch(r'([0-9a-f]{64}) [ *](\S+)', line.strip()):
            listed[match[2]] = match[1]
    if path.name not in listed:
        raise ValueError('archive missing from SHA256SUMS')
    handle = path.open('rb')
    try:
        digest = hashlib.sha256()
        for chunk in iter(lambda: handle.read(1024*1024), b''):
            digest.update(chunk)
        if digest.hexdigest() != listed[path.name]:
            raise ValueError('archive sha256 mismatch')
        handle.seek(0)
    except BaseException:
        handle.close(); raise
    stat = os.fstat(handle.fileno())
    entry = dict(archive=path.name, sha256=listed[path.name], bytes=stat.st_size, verified_against='SHA256SUMS',
                 signature_status=_signature(dumps), lines_read=0, truncated=False, kept=0)
    return handle, entry, (stat.st_size, stat.st_mtime_ns)


def _unchanged(handle, stamp):
    stat = os.fstat(handle.fileno())
    if (stat.st_size, stat.st_mtime_ns) != stamp:
        raise ValueError('archive changed while reading')


def records(handle, entity, entry, limit=None, expect=None):
    """Yield dump records one line at a time from a verified tar.xz stream."""
    meta, started = {}, time.monotonic()
    with tarfile.open(fileobj=handle, mode='r|xz') as tar:
        for member in tar:  # Member names are compared, never used as paths.
            if member.name in META and member.isfile() and member.size <= 4096:
                meta[member.name] = tar.extractfile(member).read(4096).decode('utf-8').strip()
            elif member.name == 'mbdump/'+entity and member.isfile():
                if set(META) - set(meta):
                    raise ValueError('dump metadata members missing')
                entry.update(timestamp=meta['TIMESTAMP'], replication_sequence=int(meta['REPLICATION_SEQUENCE']),
                             schema_sequence=int(meta['SCHEMA_SEQUENCE']))
                if expect and (entry['replication_sequence'], entry['schema_sequence']) != expect:
                    raise ValueError('archive belongs to another dump')
                reader = io.BufferedReader(tar.extractfile(member), 8*1024*1024)
                cap = LINE_LIMITS[entity]
                while line := reader.readline(cap+1):
                    if len(line) > cap:
                        raise ValueError(f'dump line exceeds {cap >> 20} MiB')
                    if limit is not None and entry['lines_read'] >= limit:
                        entry['truncated'] = True; break
                    entry['lines_read'] += 1
                    record = json.loads(line.decode('utf-8'))
                    if not isinstance(record, dict):
                        raise ValueError('dump record must be an object')
                    yield record
                    if entry['lines_read'] % 200000 == 0:
                        print(json.dumps(dict(lines=entry['lines_read'], kept=entry['kept'],
                              elapsed=round(time.monotonic()-started, 1))), file=sys.stderr, flush=True)
                return
    raise ValueError('dump member missing')


def _aliases(record):
    return [dict(name=a['name'], sort_name=_s(a.get('sort-name')), type=_s(a.get('type')), locale=_s(a.get('locale')),
                 primary=a.get('primary') if isinstance(a.get('primary'), bool) else None)
            for a in map(_d, _l(record.get('aliases'))) if _s(a.get('name'))]


def _urls(record):
    return [dict(type=_s(r.get('type')), resource=_d(r.get('url'))['resource']) for r in map(_d, _l(record.get('relations')))
            if r.get('target-type') == 'url' and _s(_d(r.get('url')).get('resource'))]


def _strings(value): return [x for x in _l(value) if isinstance(x, str)]


def project_work(record):
    """Core work fields and creator, work and url relations. Tags, genres, ratings and annotations are dropped."""
    artists, works, recordings, performances = [], [], [], 0
    for rel in map(_d, _l(record.get('relations'))):
        kind = rel.get('target-type')
        if kind == 'artist' and rel.get('type') in CREATOR_TYPES:
            a = _d(rel.get('artist'))
            artists.append(dict(type=rel['type'], begin=_s(rel.get('begin')), end=_s(rel.get('end')),
                attributes=_strings(rel.get('attributes')), artist=dict(id=mbid(a.get('id')), name=_s(a.get('name')),
                sort_name=_s(a.get('sort-name')), type=_s(a.get('type')), country=_s(a.get('country')),
                disambiguation=_s(a.get('disambiguation')))))
        elif kind == 'work':
            w = _d(rel.get('work'))
            works.append(dict(type=_s(rel.get('type')), direction=_s(rel.get('direction')),
                              work=dict(id=mbid(w.get('id')), title=_s(w.get('title')))))
        elif kind == 'recording':
            performances += 1
            title = _s(_d(rel.get('recording')).get('title'))
            if title and title not in recordings and len(recordings) < 3:
                recordings.append(title)
    return dict(id=mbid(record.get('id')), title=_s(record.get('title')), type=_s(record.get('type')),
                language=_s(record.get('language')), languages=_strings(record.get('languages')),
                iswcs=_strings(record.get('iswcs')), disambiguation=_s(record.get('disambiguation')),
                aliases=_aliases(record), artist_relations=artists, work_relations=works, url_relations=_urls(record),
                performance_count=performances, recording_titles_sample=recordings)


def project_artist(record):
    """Core artist fields, life span and url relations. Tags, genres, ratings, annotations and areas are dropped."""
    span = _d(record.get('life-span'))
    return dict(id=mbid(record.get('id')), name=_s(record.get('name')), sort_name=_s(record.get('sort-name')),
                type=_s(record.get('type')), gender=_s(record.get('gender')), country=_s(record.get('country')),
                disambiguation=_s(record.get('disambiguation')),
                life_span=dict(begin=_s(span.get('begin')), end=_s(span.get('end')),
                               ended=span.get('ended') if isinstance(span.get('ended'), bool) else None),
                aliases=_aliases(record), isnis=_strings(record.get('isnis')), ipis=_strings(record.get('ipis')),
                url_relations=_urls(record))


def _finish(db, dumps, entry, inputs, titles, creators, dropped):
    """One provenance row per pass: the works pass writes the first, the artist pass appends the second."""
    archive = {k: v for k, v in entry.items() if k not in {'timestamp', 'replication_sequence', 'schema_sequence'}}
    db.execute('INSERT INTO provenance VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)', (POLICY, dumps.resolve().name,
        json.dumps([archive]), entry['timestamp'], entry['replication_sequence'], entry['schema_sequence'],
        json.dumps(inputs), titles, creators, LICENSE, LICENSE_URL, 0, 'not_established', now(), dropped))
    db.commit()
    if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
        raise ValueError('subset integrity check failed')


def _result(path, entry, started, **counts):
    return dict(policy=POLICY, **counts, lines_read=entry['lines_read'], truncated=entry['truncated'],
                elapsed_seconds=round(time.monotonic()-started, 1), output_sha256=file_digest(path),
                output_bytes=path.stat().st_size, identity_verified=False, rights_clearance='not_established')


def prepare(dumps: Path, work_index: Path, score_metadata: Path, output: Path, *, limit=None):
    """Build the works subset. Inputs stay read only and the output is created once."""
    if output.exists() or output.is_symlink():
        raise FileExistsError(output)
    if not output.parent.is_dir():
        raise ValueError('output directory must exist')
    _reserve(output.parent)
    inputs = {str(p): file_digest(p) for p in (work_index, score_metadata)}
    with closing(_ro(work_index)) as db:
        queue = db.execute('SELECT title,creator FROM queue').fetchall()
    titles = {t for t in (label(_s(r[0]) or '') for r in queue) if t}
    creators = {k for k in (name_key(r[1]) for r in queue) if k}
    with closing(_ro(score_metadata)) as db:
        for (claim,) in db.execute('SELECT DISTINCT composer_claim FROM score_metadata'):
            creators.update(k for k in map(name_key, creator_search_names(claim)) if k)
    short = {k for k in creators if len(k.replace(' ', '')) < 3}  # Keys like 'm' or 'j s' match too many artists.
    creators -= short
    handle, entry, stamp = _verified(dumps, 'work')
    started = time.monotonic()
    with handle, tempfile.TemporaryDirectory(dir=output.parent) as temp:
        target = Path(temp)/'subset.sqlite'
        with closing(sqlite3.connect(target)) as db:
            db.execute('PRAGMA page_size=4096'); db.execute(f'PRAGMA max_page_count={PAGES}')
            db.executescript(SCHEMA)
            db.executemany('INSERT INTO title_set VALUES (?)', ((t,) for t in sorted(titles)))
            db.executemany('INSERT INTO creator_set VALUES (?)', ((k,) for k in sorted(creators)))
            counts = {t: [0, 0] for t in titles}
            for record in records(handle, 'work', entry, limit):
                canon = label(_s(record.get('title')) or '')
                aliases = {label(_s(_d(a).get('name')) or '') for a in _l(record.get('aliases'))} - {canon, ''}
                hits = [a for a in aliases if a in counts]
                if canon in counts:
                    counts[canon][0] += 1
                for alias in hits:
                    counts[alias][1] += 1
                if canon in counts or hits:
                    work = project_work(record)
                    db.execute('INSERT INTO works VALUES (?,?,?,?,?,?)', (work['id'], work['title'], canon, work['type'],
                               work['language'], json.dumps(work, ensure_ascii=False)))
                    db.executemany('INSERT INTO work_titles VALUES (?,?,?)', [(canon, work['id'], 'title')]*bool(canon)
                                   + [(a, work['id'], 'alias') for a in sorted(aliases)])
                    entry['kept'] += 1
            _unchanged(handle, stamp)
            db.executemany('INSERT INTO title_namesakes VALUES (?,?,?)', ((t, *c) for t, c in sorted(counts.items())))
            if any(file_digest(Path(p)) != digest for p, digest in inputs.items()):
                raise ValueError('input changed')
            _finish(db, dumps, entry, inputs, len(titles), len(creators), len(short))
            named = db.execute('SELECT count(*) FROM title_namesakes WHERE work_count+alias_count>0').fetchone()[0]
        os.link(target, output)  # Fails rather than overwrite an output created meanwhile.
    return _result(output, entry, started, works_kept=entry['kept'], titles_with_namesakes=named,
                   title_count=len(titles), creator_count=len(creators),
                   creator_keys_dropped_short=len(short))


def add_artists(dumps: Path, subset: Path, *, limit=None):
    """Stream the artist archive into an existing subset. Refuses a second artist pass."""
    _reserve(subset.parent)
    before = file_digest(subset)
    with closing(_ro(subset)) as db:
        first = db.execute('SELECT policy,dump_name,replication_sequence,schema_sequence,title_count,creator_count,'
                           'creator_keys_dropped_short '
                           'FROM provenance ORDER BY rowid').fetchall()
        if len(first) != 1 or first[0][0] != POLICY:
            raise ValueError('subset needs exactly one works provenance row')
        if first[0][1] != dumps.resolve().name:
            raise ValueError('archive belongs to another dump')
        if db.execute('SELECT count(*) FROM artists').fetchone()[0]:
            raise ValueError('artists already added')
        creators = {r[0] for r in db.execute('SELECT name_key FROM creator_set')}
        ids = {rel['artist']['id'] for (raw,) in db.execute('SELECT record_json FROM works')
               for rel in json.loads(raw)['artist_relations']}
    handle, entry, stamp = _verified(dumps, 'artist')
    started = time.monotonic()
    with handle, tempfile.TemporaryDirectory(dir=subset.parent) as temp:
        target = Path(temp)/'subset.sqlite'
        with closing(_ro(subset)) as source, closing(sqlite3.connect(target)) as db:
            source.backup(db)
            db.execute(f'PRAGMA max_page_count={PAGES}')
            counts = {k: [0, 0, 0] for k in creators}
            for record in records(handle, 'artist', entry, limit, expect=tuple(first[0][2:4])):
                names = {name_key(record.get('name')), name_key(record.get('sort-name'))} - {''}
                aliases = {name_key(_d(a).get('name')) for a in _l(record.get('aliases'))} - names - {''}
                for key in names & creators:
                    counts[key][0] += record.get('type') == 'Person'; counts[key][1] += 1
                for key in aliases & creators:
                    counts[key][2] += 1
                if record.get('id') in ids or (names | aliases) & creators:
                    artist = project_artist(record); span = artist['life_span']
                    db.execute('INSERT INTO artists VALUES (?,?,?,?,?,?,?,?,?,?)', (artist['id'], artist['name'],
                        artist['sort_name'], name_key(artist['name']), artist['type'], span['begin'], span['end'],
                        None if span['ended'] is None else int(span['ended']), artist['country'],
                        json.dumps(artist, ensure_ascii=False)))
                    rows = {(name_key(artist['name']), 'name'), (name_key(artist['sort_name']), 'sort_name')}
                    rows |= {(name_key(a['name']), 'alias') for a in artist['aliases']}
                    db.executemany('INSERT INTO artist_names VALUES (?,?,?)',
                                   sorted((k, artist['id'], kind) for k, kind in rows if k))
                    entry['kept'] += 1
            _unchanged(handle, stamp)
            db.executemany('INSERT INTO name_namesakes VALUES (?,?,?,?)', ((k, *c) for k, c in sorted(counts.items())))
            _finish(db, dumps, entry, {str(subset): before}, *first[0][4:7])
            named = db.execute('SELECT count(*) FROM name_namesakes WHERE total_count+alias_count>0').fetchone()[0]
        if file_digest(subset) != before:
            raise ValueError('subset changed during artist pass')
        os.replace(target, subset)
    return _result(subset, entry, started, artists_kept=entry['kept'], work_artist_ids=len(ids),
                   creator_count=len(creators), creators_with_namesakes=named)


def status(subset: Path):
    with closing(_ro(subset)) as db:
        def count(sql): return db.execute(sql).fetchone()[0]
        cursor = db.execute('SELECT * FROM provenance ORDER BY rowid')
        fields = [c[0] for c in cursor.description]
        provenance = [dict(zip(fields, row)) for row in cursor]
        for row in provenance:
            row.update(archives=json.loads(row.pop('archives_json')), inputs=json.loads(row.pop('inputs_json')),
                       identity_verified=bool(row['identity_verified']))
        return dict(works=count('SELECT count(*) FROM works'), titles=count('SELECT count(*) FROM title_set'),
            titles_with_namesakes=count('SELECT count(*) FROM title_namesakes WHERE work_count+alias_count>0'),
            artists=count('SELECT count(*) FROM artists'), creators=count('SELECT count(*) FROM creator_set'),
            creators_with_namesakes=count('SELECT count(*) FROM name_namesakes WHERE total_count+alias_count>0'),
            provenance=provenance, identity_verified=False, rights_clearance='not_established')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    for command, names in (('prepare', ('dumps', 'work-index', 'score-metadata', 'output')),
                           ('add-artists', ('dumps', 'subset')), ('status', ('subset',))):
        sub = commands.add_parser(command)
        for name in names:
            sub.add_argument('--'+name, type=Path, required=True)
        if command != 'status':
            sub.add_argument('--limit-lines', type=int)
    args = parser.parse_args()
    if args.command != 'status' and args.limit_lines is not None and args.limit_lines < 1:
        parser.error('--limit-lines must be positive')
    if args.command == 'prepare':
        result = prepare(args.dumps, args.work_index, args.score_metadata, args.output, limit=args.limit_lines)
    elif args.command == 'add-artists':
        result = add_artists(args.dumps, args.subset, limit=args.limit_lines)
    else:
        result = status(args.subset)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
