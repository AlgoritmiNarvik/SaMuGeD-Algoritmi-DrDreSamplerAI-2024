"""Offline recording to work candidates for the Lakh queue from the MusicBrainz full export subset.

The module applies the work-candidates-v3 rule for the recording kind to every Lakh queue row against the
local CC0 subset built by musicbrainz_fullexport: a recording whose normalized title equals the source title
and whose full artist credit agrees with the source creator, its performance work relations and the agreeing
writers of each work. It never uses the network, never opens the mutable work index, never writes to an
input and never treats a title or name agreement as a verified identity or a rights clearance.
"""
from __future__ import annotations
import argparse
from contextlib import closing
import gzip
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import time

from .dataset import file_digest
from .musicbrainz_fullexport import POLICY as SUBSET_POLICY
from .work_identity import creator_agreement, label, now
from .work_identity_offline import LICENSE, LICENSE_URL, _guard, _ro

POLICY, PROVIDER = 'work-candidates-v3-fullexport', 'musicbrainz_fullexport'
METHOD = 'normalized_labels_names_or_initials_and_dump_relationship_not_MIDI_identity'
WRITERS = ('composer', 'writer', 'lyricist')
RECORDINGS, WORKS, BATCH, CACHE = 50, 20, 5000, 65536
PAGES, MB = 524288, 1024*1024  # 2 GiB at 4 KiB pages
UNVERIFIED = dict(identity_verified=False, rights_clearance='not_established')
REASONS = ('candidate', 'no_recording_with_title', 'recordings_without_creator_agreement',
           'agreeing_recordings_without_work', 'missing_title', 'title_not_usable', 'missing_creator')
SCHEMA = f'''
CREATE TABLE provenance(policy TEXT,inputs_json TEXT,dump_json TEXT,selection_json TEXT,created_on TEXT,
    identity_verified INTEGER CHECK(identity_verified=0),rights_clearance TEXT CHECK(rights_clearance='not_established'));
CREATE TABLE queue(source_key TEXT PRIMARY KEY,source_sha256 TEXT,dataset_id TEXT,title TEXT,creator TEXT,query_kind TEXT,
    status TEXT CHECK(status IN ('candidate','no_candidate','missing_labels')),reason TEXT CHECK(reason IN {REASONS}),
    updated_on TEXT);
CREATE INDEX queue_status ON queue(status,reason,source_key);
CREATE TABLE work_candidates(source_key TEXT REFERENCES queue,work_id TEXT,recording_id TEXT,title TEXT,evidence_json TEXT,
    match_status TEXT CHECK(match_status='candidate'),PRIMARY KEY(source_key,work_id,recording_id));
CREATE TABLE source_matches(source_key TEXT PRIMARY KEY REFERENCES queue,title_recording_count INTEGER,
    agreeing_recording_count INTEGER,linked_work_count INTEGER,truncated INTEGER,recordings_truncated INTEGER,
    works_truncated INTEGER);
'''


def dump_block(sub, work_sha):
    """Check that the subset is complete and was built from this work index, and return the dump block."""
    rows = sub.execute('SELECT policy,dump_json,inputs_json FROM provenance').fetchall()
    if len(rows) != 1 or rows[0][0] != SUBSET_POLICY:
        raise ValueError('subset needs exactly one full export provenance row')
    dump, inputs = json.loads(rows[0][1]), json.loads(rows[0][2])
    if dump.get('truncated'):
        raise ValueError('subset pass was truncated')
    if inputs.get('work_index', {}).get('sha256') != work_sha:
        raise ValueError('subset was built from another work index')
    return dict(export_name=dump['export_name'], archive=dump['archive'], archive_sha256=dump['sha256'],
                timestamp=dump['timestamp'], replication_sequence=dump['replication_sequence'],
                schema_sequence=dump['schema_sequence'])


class Reference:
    """Cached lookups over the read only subset. Caches are cleared when they grow beyond a bound."""
    def __init__(self, sub):
        self.sub, self.titles, self.credits, self.works, self.writers = sub, {}, {}, {}, {}
        self.namesakes = dict(sub.execute('SELECT title_norm,recording_count FROM title_namesakes'))

    def _cached(self, cache, key, load):
        if key not in cache:
            if len(cache) > CACHE:
                cache.clear()
            cache[key] = load(key)
        return cache[key]

    def recordings(self, title):
        return self._cached(self.titles, title, lambda t: self.sub.execute(
            'SELECT recording_id,gid,name,credit_id FROM recordings WHERE title_norm=? ORDER BY gid', (t,)).fetchall())

    def credit(self, credit_id):
        def load(key):
            row = self.sub.execute('SELECT credit,names_json FROM artist_credits WHERE credit_id=?', (key,)).fetchone()
            return (row[0], json.loads(row[1])) if row else ('', [])
        return self._cached(self.credits, credit_id, load)

    def performance_works(self, recording_id):
        return self._cached(self.works, recording_id, lambda r: self.sub.execute(
            '''SELECT DISTINCT w.work_id,w.gid,w.name,w.type FROM recording_works x JOIN works w USING(work_id)
               WHERE x.recording_id=? AND x.link_type='performance' ORDER BY w.gid''', (r,)).fetchall())

    def work_writers(self, work_id):
        return self._cached(self.writers, work_id, lambda w: self.sub.execute(
            f'''SELECT DISTINCT a.name,x.role,a.gid FROM work_artists x JOIN artists a USING(artist_id)
               WHERE x.work_id=? AND x.role IN ({",".join("?"*len(WRITERS))}) ORDER BY a.gid,x.role''',
            (w, *WRITERS)).fetchall())


def match(row, ref, dump):
    """Mirror resolve() for the recording kind. Returns status, reason, candidate rows and the source match row."""
    key, _, _, raw_title, raw_creator, title_status, basis = row
    title, creator = label(raw_title), label(raw_creator)
    if not title:
        return 'missing_labels', 'missing_title', [], None
    if title_status != 'usable':
        return 'missing_labels', 'title_not_usable', [], None
    if not creator:
        return 'missing_labels', 'missing_creator', [], None
    recordings = ref.recordings(title)
    agreeing = []
    for recording_id, gid, name, credit_id in recordings:
        credit, names = ref.credit(credit_id)
        found = creator_agreement(credit, creator)
        if found:
            agreeing.append((recording_id, gid, name, credit, names, found))
    over_recordings = len(agreeing) > RECORDINGS
    linked, over_works, pending = 0, False, []
    for recording_id, gid, name, credit, names, found in agreeing[:RECORDINGS]:
        works = ref.performance_works(recording_id)
        linked += len(works); over_works |= len(works) > WORKS
        for work_id, work_gid, work_name, work_type in works[:WORKS]:
            writers = [dict(name=n, role=role, artist_id=a, agreement=agreed) for n, role, a in ref.work_writers(work_id)
                       for agreed in [creator_agreement(n, creator)] if agreed]
            pending.append((gid, name, credit, names, found, len(works), work_gid, work_name, work_type, writers))
    distinct = len({p[6] for p in pending})
    rows = []
    for gid, name, credit, names, found, work_count, work_gid, work_name, work_type, writers in pending:
        basis_json = dict(source_creator_basis=basis or 'original_catalog_labels_unverified', query_title=raw_title,
            query_creator=raw_creator, title_agreement='recording_title_normalized', creator_agreement=found,
            credited_artists=[dict(name=n['name'], gid=n['artist_gid'], agreement=creator_agreement(n['name'], creator))
                              for n in names],
            recording=dict(gid=gid, name=name, credit=credit), recording_namesake_count=ref.namesakes.get(title),
            matching_recording_count=len(agreeing), matching_recordings_truncated=over_recordings,
            linked_work_count=work_count, linked_works_truncated=work_count > WORKS,
            distinct_work_candidates=distinct, multiple_work_candidates=distinct > 1,
            musical_comparison='not_performed', source_identity_verified=False)
        work = dict(gid=work_gid, title=work_name, type=work_type,
                    relations=[dict(type=w['role'], artist=dict(id=w['artist_id'], name=w['name'])) for w in writers])
        evidence = dict(provider=PROVIDER, policy=POLICY, metadata_license=LICENSE, metadata_license_url=LICENSE_URL,
            method=METHOD, dump=dump, match_basis=basis_json, work=work,
            musical_work_license_status='unknown', rights_holder_status='not_established', **UNVERIFIED)
        rows.append((key, work_gid, gid, work_name, json.dumps(evidence, ensure_ascii=False), 'candidate'))
    reason = 'candidate' if rows else 'no_recording_with_title' if not recordings else \
        'recordings_without_creator_agreement' if not agreeing else 'agreeing_recordings_without_work'
    source = (key, len(recordings), len(agreeing), linked, int(over_recordings or over_works),
              int(over_recordings), int(over_works))
    return ('candidate' if rows else 'no_candidate'), reason, rows, source


def prepare(work_index: Path, subset: Path, output: Path, *, limit=None):
    """Build a new sidecar index. Inputs are opened read only and re-hashed at the end."""
    if limit is not None and (type(limit) is not int or limit < 1):
        raise ValueError('limit must be a positive integer')
    _guard(output)
    started = time.monotonic()
    inputs = {k: dict(path=str(p), sha256=file_digest(p)) for k, p in dict(work_index=work_index, subset=subset).items()}
    with closing(_ro(work_index)) as source:
        rows = source.execute('''SELECT q.source_key,q.source_sha256,q.dataset_id,q.title,q.creator,t.title_status,t.creator_basis
            FROM queue q LEFT JOIN track_metadata t USING(source_key) WHERE q.query_kind='recording'
            ORDER BY q.source_key''').fetchall()
    truncated = limit is not None and len(rows) > limit
    rows = rows[:limit]
    with closing(_ro(subset)) as sub, tempfile.TemporaryDirectory(dir=output.parent) as temp:
        dump = dump_block(sub, inputs['work_index']['sha256'])
        ref = Reference(sub)
        target = Path(temp)/'offline.sqlite'
        with closing(sqlite3.connect(target)) as db:
            db.execute('PRAGMA page_size=4096'); db.execute(f'PRAGMA max_page_count={PAGES}')
            db.executescript(SCHEMA)
            buffers = dict(queue=[], work_candidates=[], source_matches=[])
            for n, row in enumerate(rows, 1):
                key, sha, dataset, raw_title, raw_creator = row[:5]
                state, reason, candidates, matched = match(row, ref, dump)
                buffers['queue'].append((key, sha, dataset, raw_title, raw_creator, 'recording', state, reason, now()))
                buffers['work_candidates'] += candidates
                if matched:
                    buffers['source_matches'].append(matched)
                if n % BATCH == 0 or n == len(rows):
                    for table, values in buffers.items():
                        if values:
                            db.executemany(f'INSERT INTO {table} VALUES ({",".join("?"*len(values[0]))})', values)
                            values.clear()
                if n % 5000 == 0:
                    print(json.dumps(dict(sources=n, elapsed=round(time.monotonic()-started, 1))), file=sys.stderr, flush=True)
            if any(file_digest(Path(v['path'])) != v['sha256'] for v in inputs.values()):
                raise ValueError('input changed during prepare')
            selection = dict(query_kind='recording', limit=limit, truncated=truncated, sources=len(rows),
                             max_recordings_per_source=RECORDINGS, max_works_per_recording=WORKS)
            db.execute('INSERT INTO provenance VALUES (?,?,?,?,?,0,?)', (POLICY, json.dumps(inputs), json.dumps(dump),
                       json.dumps(selection), now(), 'not_established'))
            db.commit()
            if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise ValueError('offline index integrity check failed')
        os.link(target, output)  # Fails rather than overwrite an output created meanwhile.
    return dict(status(output), selection=selection, elapsed_seconds=round(time.monotonic()-started, 1),
                output_sha256=file_digest(output), output_bytes=output.stat().st_size)


def status(index: Path):
    with closing(_ro(index)) as db:
        def one(sql): return db.execute(sql).fetchone()[0]
        return dict(policy=POLICY, sources=one('SELECT count(*) FROM queue'),
            queue_status=dict(db.execute('SELECT status,count(*) FROM queue GROUP BY 1')),
            reasons=dict(db.execute('SELECT reason,count(*) FROM queue GROUP BY 1')),
            work_candidates=one('SELECT count(*) FROM work_candidates'),
            candidate_sources=one('SELECT count(DISTINCT source_key) FROM work_candidates'),
            distinct_works=one('SELECT count(DISTINCT work_id) FROM work_candidates'),
            distinct_recordings=one('SELECT count(DISTINCT recording_id) FROM work_candidates'),
            truncated_sources=one('SELECT count(*) FROM source_matches WHERE truncated'),
            recordings_truncated_sources=one('SELECT count(*) FROM source_matches WHERE recordings_truncated'),
            works_truncated_sources=one('SELECT count(*) FROM source_matches WHERE works_truncated'), **UNVERIFIED)


def source_record(db, key, sha, dataset, state, reason, dump_name):
    candidates = []
    for work_id, recording_id, title, encoded in db.execute('''SELECT work_id,recording_id,title,evidence_json
            FROM work_candidates WHERE source_key=? ORDER BY work_id,recording_id''', (key,)):
        evidence = json.loads(encoded); basis = evidence['match_basis']
        candidates.append(dict(work_id=work_id, recording_id=recording_id, title=title, credit=basis['recording']['credit'],
            creator_agreement=basis['creator_agreement'], writers=evidence['work']['relations']))
    counts = db.execute('''SELECT title_recording_count,agreeing_recording_count,linked_work_count,truncated
        FROM source_matches WHERE source_key=?''', (key,)).fetchone()
    matches = dict(zip(('title_recording_count', 'agreeing_recording_count', 'linked_work_count'), counts[:3]),
                   truncated=bool(counts[3])) if counts else None
    return dict(source_key=key, source_sha256=sha, dataset_id=dataset, status=state, reason=reason, matches=matches,
                candidates=candidates, policy=POLICY, dump_name=dump_name, **UNVERIFIED)


def export(index: Path, output: Path, *, max_output_mb=512):
    """Write one JSON line per source to a new gzip file, refusing outputs beyond the size bound."""
    if type(max_output_mb) is not int or max_output_mb < 1:
        raise ValueError('max_output_mb must be a positive integer')
    _guard(output)
    cap, lines = max_output_mb*MB, 0
    with closing(_ro(index)) as db, tempfile.TemporaryDirectory(dir=output.parent) as temp:
        dump_name = json.loads(db.execute('SELECT dump_json FROM provenance').fetchone()[0])['export_name']
        target = Path(temp)/'export.jsonl.gz'
        with target.open('wb') as raw, gzip.GzipFile(fileobj=raw, mode='wb', mtime=0) as stream:
            for row in db.execute('SELECT source_key,source_sha256,dataset_id,status,reason FROM queue ORDER BY source_key'):
                stream.write((json.dumps(source_record(db, *row, dump_name), ensure_ascii=False)+'\n').encode())
                lines += 1
                if raw.tell() > cap:
                    raise ValueError('export exceeds max size')
        if target.stat().st_size > cap:
            raise ValueError('export exceeds max size')
        os.link(target, output)
    return dict(policy=POLICY, output=str(output), lines=lines, output_sha256=file_digest(output),
                output_bytes=output.stat().st_size, **UNVERIFIED)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    build = commands.add_parser('prepare')
    for name in ('work-index', 'subset', 'output'):
        build.add_argument('--'+name, type=Path, required=True)
    build.add_argument('--limit', type=int)
    commands.add_parser('status').add_argument('--index', type=Path, required=True)
    out = commands.add_parser('export')
    out.add_argument('--index', type=Path, required=True); out.add_argument('--output', type=Path, required=True)
    out.add_argument('--max-output-mb', type=int, default=512)
    args = parser.parse_args()
    if args.command == 'prepare':
        result = prepare(args.work_index, args.subset, args.output, limit=args.limit)
    elif args.command == 'status':
        result = status(args.index)
    else:
        result = export(args.index, args.output, max_output_mb=args.max_output_mb)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
