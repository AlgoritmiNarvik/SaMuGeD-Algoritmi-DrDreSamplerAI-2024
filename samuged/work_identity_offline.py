"""Offline work candidates, title only review rows and creator life span estimates from a MusicBrainz dump subset.

The module applies the work-candidates-v3 title and writer agreement rules to every queue source against the
local CC0 subset built by musicbrainz_dump. It never uses the network, never opens the mutable work index,
never writes to an input, never treats a title or name agreement as a verified identity and never turns a
life span into rights clearance. Work candidates are candidates, title only rows require review, creator
identities are unverified candidates and term estimates are estimates for the composition layer only.
"""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
from contextlib import closing
from datetime import datetime, timezone
import gzip
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import time

from .dataset import file_digest
from .musicbrainz_dump import creator_search_names, name_key
from .work_identity import creator_agreement, label, now

POLICY, PROVIDER = 'work-candidates-v3-dump', 'musicbrainz_json_dump'
LICENSE, LICENSE_URL = 'CC0-1.0', 'https://musicbrainz.org/doc/About/Data_License'
METHOD = 'normalized_labels_names_or_initials_and_dump_relationship_not_MIDI_identity'
WRITERS = ('composer', 'writer', 'lyricist', 'librettist')
TITLE_ONLY, IDS, BATCH = 50, 10, 5000
RESERVE, PAGES, MB = 10.75*1024**3, 524288, 1024*1024  # 2 GiB at 4 KiB pages
JURISDICTION = ('Life plus 70 years applies in the EEA and many other states; the United States and some others use '
                'different rules. Estimate for the composition layer only, not clearance for arrangements, '
                'transcriptions or performances.')
UNVERIFIED = dict(identity_verified=False, rights_clearance='not_established')
IDENTITY = ('disambiguated_by_work_relation', 'single_person_candidate', 'ambiguous_persons', 'non_person_match', 'no_match')
SCHEMA = f'''
CREATE TABLE provenance(policy TEXT,inputs_json TEXT,dump_json TEXT,selection_json TEXT,created_on TEXT,
    identity_verified INTEGER CHECK(identity_verified=0),rights_clearance TEXT CHECK(rights_clearance='not_established'));
CREATE TABLE queue(source_key TEXT PRIMARY KEY,source_sha256 TEXT,dataset_id TEXT,title TEXT,creator TEXT,query_kind TEXT,
    status TEXT CHECK(status IN ('candidate','no_candidate','no_namesake','title_only_candidates','missing_labels')),
    error TEXT,updated_on TEXT);
CREATE INDEX queue_status ON queue(status,dataset_id,source_key);
CREATE TABLE work_candidates(source_key TEXT REFERENCES queue,work_id TEXT,recording_id TEXT,title TEXT,evidence_json TEXT,
    match_status TEXT CHECK(match_status='candidate'),PRIMARY KEY(source_key,work_id,recording_id));
CREATE TABLE title_only_candidates(source_key TEXT REFERENCES queue,work_id TEXT,title TEXT,writers_json TEXT,
    status TEXT CHECK(status IN ('title_only_candidate_requires_review','title_matches_other_writers_requires_review')),
    evidence_json TEXT,PRIMARY KEY(source_key,work_id));
CREATE TABLE source_creators(source_key TEXT REFERENCES queue,creator_key TEXT,raw TEXT,dataset_id TEXT,
    basis TEXT CHECK(basis IN ('queue_creator','score_composer_claim')),PRIMARY KEY(source_key,creator_key,basis));
CREATE INDEX source_creator_key ON source_creators(creator_key);
CREATE TABLE creator_identities(creator_key TEXT PRIMARY KEY,raw_examples_json TEXT,source_count INTEGER,
    dataset_counts_json TEXT,status TEXT CHECK(status IN {IDENTITY}),artist_id TEXT,artist_name TEXT,artist_type TEXT,
    begin TEXT,end TEXT,ended INTEGER,person_namesakes INTEGER,total_namesakes INTEGER,alias_namesakes INTEGER,candidate_ids_json TEXT,evidence_json TEXT);
CREATE TABLE term_estimates(creator_key TEXT PRIMARY KEY REFERENCES creator_identities,artist_id TEXT,death_year INTEGER,
    rule TEXT,threshold_year INTEGER,
    status TEXT CHECK(status IN ('likely_expired','likely_in_term','living_or_unknown_end','unknown')),evidence_json TEXT);
'''


def _ro(path):
    return sqlite3.connect(Path(path).resolve(strict=True).as_uri()+'?mode=ro', uri=True)


def _guard(output: Path):
    if output.exists() or output.is_symlink():
        raise FileExistsError(output)
    if not output.parent.is_dir():
        raise ValueError('output directory must exist')
    if shutil.disk_usage(output.parent).free < RESERVE:
        raise ValueError('10 GiB storage reserve required')


def _short(key): return len(key.replace(' ', '')) < 3  # The subset drops these keys too.


def dump_block(sub, work_sha, score_sha):
    """Check that both subset passes completed from these inputs and return the dump block."""
    cursor = sub.execute('SELECT * FROM provenance ORDER BY rowid')
    fields = [c[0] for c in cursor.description]
    rows = [dict(zip(fields, r), archives=json.loads(r[fields.index('archives_json')]),
                 inputs=json.loads(r[fields.index('inputs_json')])) for r in cursor]
    archives = {a['archive']: (a, r) for r in rows for a in r['archives']}
    if 'work.tar.xz' not in archives or 'artist.tar.xz' not in archives \
            or not sub.execute('SELECT count(*) FROM artists').fetchone()[0]:
        raise ValueError('subset needs completed works and artists passes')
    if any(a['truncated'] for a, _ in archives.values()):
        raise ValueError('subset passes were truncated')
    archive, works = archives['work.tar.xz']
    if work_sha not in works['inputs'].values():
        raise ValueError('subset was built from another work index')
    if score_sha not in works['inputs'].values():
        raise ValueError('subset was built from another score metadata file')
    block = dict(dump_name=works['dump_name'], timestamp=works['timestamp'], replication_sequence=works['replication_sequence'],
                 schema_sequence=works['schema_sequence'], archive_sha256=archive['sha256'])
    return block, [{k: v for k, v in r.items() if not k.endswith('_json')} for r in rows]


class Reference:
    """In memory title and name lookups over the read only subset, with lazily loaded work records."""
    def __init__(self, sub):
        self.sub, self.records, self.ranked, self.teams, self.agreeing = sub, {}, {}, {}, {}
        self.creator_set = {k for (k,) in sub.execute('SELECT name_key FROM creator_set')}
        self.titles = defaultdict(list)
        for title, work_id, kind in sub.execute('SELECT normalized_title,work_id,kind FROM work_titles'):
            self.titles[title].append((work_id, kind))
        self.performances = dict(sub.execute("SELECT work_id,json_extract(record_json,'$.performance_count') FROM works"))
        self.namesakes = {t: (w, a) for t, w, a in sub.execute('SELECT normalized_title,work_count,alias_count FROM title_namesakes')}

    def work(self, work_id):
        if work_id not in self.records:
            if len(self.records) > 65536:
                self.records.clear()
            raw = self.sub.execute('SELECT record_json FROM works WHERE work_id=?', (work_id,)).fetchone()[0]
            self.records[work_id] = json.loads(raw)
        return self.records[work_id]

    def ranked_works(self, title):
        """Namesake works: canonical title first, then performance count descending, then work id."""
        if title not in self.ranked:
            kinds = {}
            for work_id, kind in self.titles.get(title, ()):
                kinds[work_id] = 'title' if kind == 'title' or kinds.get(work_id) == 'title' else 'alias'
            self.ranked[title] = sorted(kinds.items(), key=lambda x: (x[1] != 'title', -(self.performances.get(x[0]) or 0), x[0]))
        return self.ranked[title]

    def agreeing_works(self, title, creator):
        """Every namesake work with at least one agreeing writer. Writers are cached per work, results per pair."""
        if (title, creator) not in self.agreeing:
            found = []
            for work_id, kind in self.ranked_works(title):
                if work_id not in self.teams:
                    self.teams[work_id] = writers(self.work(work_id))
                agreeing = [dict(name=w['name'], role=w['role'], agreement=a, artist_id=w['artist_id'])
                            for w in self.teams[work_id] for a in [agreement(w, creator)] if a]
                if agreeing:
                    found.append((work_id, kind, agreeing))
            self.agreeing[title, creator] = found
        return self.agreeing[title, creator]


def writers(record):
    return [dict(name=r['artist']['name'], role=r['type'], artist_id=r['artist']['id'], sort_name=r['artist'].get('sort_name'))
            for r in record['artist_relations'] if r['type'] in WRITERS]


def agreement(writer, creator):
    found = {creator_agreement(writer['name'], creator), creator_agreement(writer['sort_name'], creator)}
    return next((k for k in ('normalized_tokens', 'initials_candidate') if k in found), None)


def role_of(dataset, basis):
    if dataset == 'lakh':
        return 'performer_label'
    return 'artist_label_role_unverified' if basis == 'upstream_artist_role_unverified' else 'composer_label'


def match(row, ref, dump):
    """Mirror resolve() for the work kind. Returns status, candidate rows, title only rows and agreeing artist ids."""
    key, _, dataset, raw_title, raw_creator, title_status, basis = row
    title, creator = label(raw_title), label(raw_creator)
    if not title or title_status != 'usable':
        return 'missing_labels', [], [], set()
    ranked = ref.ranked_works(title)
    if not ranked:
        return 'no_namesake', [], [], set()
    canonical, aliases = ref.namesakes.get(title, (None, None))
    basis = basis or 'original_catalog_labels_unverified'
    common = dict(source_creator_basis=basis, query_title=raw_title, query_creator=raw_creator,
                  title_namesake_count=canonical, title_alias_namesake_count=aliases, source_creator_role=role_of(dataset, basis))
    found = ref.agreeing_works(title, creator) if creator else []
    if found:
        rows = []
        for work_id, kind, agreeing in found:
            record = ref.work(work_id)
            basis_json = dict(common, title_agreement='canonical_title_normalized' if kind == 'title' else 'alias_normalized',
                creator_agreement=agreeing, distinct_work_candidates=len(found), multiple_work_candidates=len(found) > 1,
                linked_work_count=len(ranked),
                musical_comparison='not_performed', source_identity_verified=False)
            work = dict(record, relations=[dict(type=w['role'], artist=dict(id=w['artist_id'], name=w['name'])) for w in writers(record)])
            evidence = dict(provider=PROVIDER, policy=POLICY, metadata_license=LICENSE, metadata_license_url=LICENSE_URL,
                method=METHOD, dump=dump, match_basis=basis_json, work=work,
                musical_work_license_status='unknown', rights_holder_status='not_established', **UNVERIFIED)
            rows.append((key, work_id, '', record['title'], json.dumps(evidence, ensure_ascii=False), 'candidate'))
        # Only full token agreement on a canonical title can narrow a creator identity.
        strong = {a['artist_id'] for _, kind, agreeing in found if kind == 'title'
                  for a in agreeing if a['agreement'] == 'normalized_tokens'}
        return 'candidate', rows, [], strong
    status = 'title_matches_other_writers_requires_review' if creator else 'title_only_candidate_requires_review'
    over = len(ranked) > TITLE_ONLY
    rows = []
    for work_id, kind in ranked[:TITLE_ONLY]:
        record = ref.work(work_id)
        evidence = dict(common, provider=PROVIDER, policy=POLICY, metadata_license=LICENSE, status=status, dump=dump,
            title_agreement='canonical_title_normalized' if kind == 'title' else 'alias_normalized',
            namesake_works=len(ranked), iswc_present=bool(record['iswcs']), iswcs=record['iswcs'][:3],
            performance_count=record['performance_count'], truncated=over, ambiguous_title=over,
            musical_comparison='not_performed', **UNVERIFIED)
        team = [{k: w[k] for k in ('name', 'role', 'artist_id')} for w in writers(record)]
        rows.append((key, work_id, record['title'], json.dumps(team, ensure_ascii=False), status, json.dumps(evidence, ensure_ascii=False)))
    return ('no_candidate' if creator else 'title_only_candidates'), [], rows, set()


def term_estimate(key, artist_id, artist, year):
    name, _, begin, end, ended = artist
    death = int(end[:4]) if end and end[:4].isdigit() else None
    threshold = death+70 if death is not None else None
    status = ('likely_expired' if threshold < year else 'likely_in_term') if death is not None else \
        'living_or_unknown_end' if ended == 0 or not end else 'unknown'
    evidence = dict(artist_id=artist_id, artist_name=name, begin=begin, end=end, ended=None if ended is None else bool(ended),
                    jurisdiction_note=JURISDICTION, estimate_not_clearance=True)
    return key, artist_id, death, 'life_plus_70', threshold, status, json.dumps(evidence, ensure_ascii=False)


def identify(db, sub, creators, writer_ids, dump):
    """Match each creator key to dump artists by exact name key, then narrow by work relations."""
    artists = {a: rest for a, *rest in sub.execute('SELECT artist_id,name,type,begin,end,ended FROM artists')}
    names = defaultdict(list)
    for key, artist_id, kind in sub.execute('SELECT name_key,artist_id,kind FROM artist_names'):
        if key in creators and artist_id in artists:
            names[key].append((artist_id, kind))
    counts = {k: c for k, *c in sub.execute('SELECT name_key,person_count,total_count,alias_count FROM name_namesakes')}
    year, identities, terms = datetime.now(timezone.utc).year, [], []
    for key in sorted(creators):
        entries, info = names.get(key, []), creators[key]
        primary = sorted({a for a, kind in entries if kind != 'alias'}) or sorted({a for a, _ in entries})
        via = sorted({a for a, _ in entries} & writer_ids.get(key, set()))
        persons = [a for a in primary if artists[a][1] == 'Person']
        chosen = via[0] if len(via) == 1 else persons[0] if len(persons) == 1 else None
        status = IDENTITY[0] if len(via) == 1 else IDENTITY[1] if chosen else IDENTITY[2] if persons \
            else IDENTITY[3] if primary else IDENTITY[4]
        artist = artists[chosen] if chosen else (None,)*5
        evidence = dict(identity_status='candidate_unverified', rights_clearance='not_established', dump=dump,
                        matching_rule='name_key_exact_then_work_relation', matched_by_alias_only=bool(entries) and
                        all(kind == 'alias' for _, kind in entries), work_relation_ids=via[:IDS])
        if chosen and artist[1] != 'Person':  # Dissolution dates of groups are not a life span.
            evidence['term_estimate_skipped'] = 'artist_type_not_person'
        identities.append((key, json.dumps(info['raw'][:3], ensure_ascii=False), len(info['sources']),
            json.dumps(dict(sorted(info['datasets'].items()))), status, chosen, *artist, *counts.get(key, (None,)*3),
            json.dumps((persons+[a for a in primary if a not in persons])[:IDS]), json.dumps(evidence, ensure_ascii=False)))
        if chosen and artist[1] == 'Person':
            terms.append(term_estimate(key, chosen, artist, year))
    db.executemany('INSERT INTO creator_identities VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)', identities)
    db.executemany('INSERT INTO term_estimates VALUES (?,?,?,?,?,?,?)', terms)


def prepare(work_index: Path, subset: Path, score_metadata: Path, output: Path, *, dataset=None, limit=None):
    """Build a new offline index. Inputs are opened read only and re-hashed at the end."""
    if limit is not None and (type(limit) is not int or limit < 1):
        raise ValueError('limit must be a positive integer')
    _guard(output)
    started = time.monotonic()
    paths = dict(work_index=work_index, subset=subset, score_metadata=score_metadata)
    inputs = {k: dict(path=str(p), sha256=file_digest(p)) for k, p in paths.items()}
    with closing(_ro(work_index)) as source:
        rows = source.execute('''SELECT q.source_key,q.source_sha256,q.dataset_id,q.title,q.creator,t.title_status,t.creator_basis
            FROM queue q LEFT JOIN track_metadata t USING(source_key) ORDER BY q.source_key''').fetchall()
    hashes = {r[0]: r[1] for r in rows}
    selected = [r for r in rows if dataset in (None, r[2])]
    truncated = limit is not None and len(selected) > limit
    selected = selected[:limit]
    chosen = {r[0] for r in selected}
    claims = defaultdict(list)
    with closing(_ro(score_metadata)) as scores:
        for key, sha, claim in scores.execute('SELECT source_key,source_sha256,composer_claim FROM score_metadata'):
            if hashes.get(key) != sha:
                raise ValueError('score metadata binding mismatch')
            if key in chosen:
                claims[key] += [(name_key(x), claim) for x in creator_search_names(claim)]
    with closing(_ro(subset)) as sub, tempfile.TemporaryDirectory(dir=output.parent) as temp:
        dump, subset_rows = dump_block(sub, inputs['work_index']['sha256'], inputs['score_metadata']['sha256'])
        ref = Reference(sub)
        target = Path(temp)/'offline.sqlite'
        with closing(sqlite3.connect(target)) as db:
            db.execute('PRAGMA page_size=4096'); db.execute(f'PRAGMA max_page_count={PAGES}')
            db.executescript(SCHEMA)
            creators = defaultdict(lambda: dict(raw=[], sources=set(), datasets=Counter()))
            writer_ids, skipped = defaultdict(set), set()
            buffers = dict(queue=[], work_candidates=[], title_only_candidates=[], source_creators=[])
            for n, row in enumerate(selected, 1):
                key, sha, ds, raw_title, raw_creator = row[:5]
                state, candidates, title_only, ids = match(row, ref, dump)
                buffers['queue'].append((key, sha, ds, raw_title, raw_creator, 'work', state, None, now()))
                buffers['work_candidates'] += candidates; buffers['title_only_candidates'] += title_only
                own = {(name_key(raw_creator), raw_creator, 'queue_creator')} if label(raw_creator) else set()
                own |= {(k, claim, 'score_composer_claim') for k, claim in claims.get(key, ())}
                for creator_key, raw, basis in sorted(own):
                    if _short(creator_key):
                        skipped.add(creator_key); continue
                    if creator_key not in ref.creator_set:
                        raise ValueError('creator key outside subset creator set')
                    info = creators[creator_key]
                    if raw not in info['raw'] and len(info['raw']) < 3:
                        info['raw'].append(raw)
                    if key not in info['sources']:
                        info['sources'].add(key); info['datasets'][ds] += 1
                    writer_ids[creator_key] |= ids
                    buffers['source_creators'].append((key, creator_key, raw, ds, basis))
                if n % BATCH == 0 or n == len(selected):
                    for table, values in buffers.items():
                        if values:
                            db.executemany(f'INSERT INTO {table} VALUES ({",".join("?"*len(values[0]))})', values)
                            values.clear()
                if n % 20000 == 0:
                    print(json.dumps(dict(sources=n, elapsed=round(time.monotonic()-started, 1))), file=sys.stderr, flush=True)
            identify(db, sub, creators, writer_ids, dump)
            if any(file_digest(Path(v['path'])) != v['sha256'] for v in inputs.values()):
                raise ValueError('input changed during prepare')
            selection = dict(dataset=dataset, limit=limit, truncated=truncated, sources=len(selected),
                             creator_keys_skipped_short=len(skipped))
            db.execute('INSERT INTO provenance VALUES (?,?,?,?,?,0,?)', (POLICY, json.dumps(inputs), json.dumps(
                dict(block=dump, subset_provenance=subset_rows), ensure_ascii=False), json.dumps(selection), now(), 'not_established'))
            db.commit()
            if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise ValueError('offline index integrity check failed')
        os.link(target, output)  # Fails rather than overwrite an output created meanwhile.
    return dict(status(output), selection=selection,
                elapsed_seconds=round(time.monotonic()-started, 1), output_sha256=file_digest(output),
                output_bytes=output.stat().st_size)


def status(index: Path):
    with closing(_ro(index)) as db:
        def one(sql): return db.execute(sql).fetchone()[0]
        queue = defaultdict(dict)
        for ds, state, count in db.execute('SELECT dataset_id,status,count(*) FROM queue GROUP BY 1,2'):
            queue[ds][state] = count
        return dict(policy=POLICY, sources=one('SELECT count(*) FROM queue'), queue_status=dict(queue),
            work_candidates=one('SELECT count(*) FROM work_candidates'),
            candidate_sources=one('SELECT count(DISTINCT source_key) FROM work_candidates'),
            distinct_works=one('SELECT count(DISTINCT work_id) FROM work_candidates'),
            title_only_rows=one('SELECT count(*) FROM title_only_candidates'),
            title_only_sources=one('SELECT count(DISTINCT source_key) FROM title_only_candidates'),
            source_creators=one('SELECT count(*) FROM source_creators'),
            creator_identities=dict(db.execute('SELECT status,count(*) FROM creator_identities GROUP BY 1')),
            term_estimates=dict(db.execute('SELECT status,count(*) FROM term_estimates GROUP BY 1')), **UNVERIFIED)


def source_record(db, key, sha, dataset, state, dump_name):
    candidates = []
    for work_id, title, encoded in db.execute('SELECT work_id,title,evidence_json FROM work_candidates WHERE source_key=? ORDER BY work_id', (key,)):
        basis = json.loads(encoded)['match_basis']
        candidates.append(dict(work_id=work_id, title=title, title_agreement=basis['title_agreement'],
            writers=basis['creator_agreement'], title_namesake_count=basis['title_namesake_count'],
            title_alias_namesake_count=basis['title_alias_namesake_count']))
    title_only = [dict(work_id=w, title=t, writers=json.loads(team), status=s) for w, t, team, s in db.execute(
        'SELECT work_id,title,writers_json,status FROM title_only_candidates WHERE source_key=? ORDER BY rowid LIMIT ?', (key, TITLE_ONLY))]
    creators = [dict(creator_key=k, basis=b, identity_status=s, artist_id=a, artist_name=n, alias_namesakes=al,
                     term_estimate=dict(status=ts, death_year=d, threshold_year=y) if ts else None)
                for k, b, s, a, n, al, ts, d, y in db.execute('''SELECT s.creator_key,s.basis,i.status,i.artist_id,i.artist_name,
                    i.alias_namesakes,t.status,t.death_year,t.threshold_year FROM source_creators s JOIN creator_identities i USING(creator_key)
                    LEFT JOIN term_estimates t USING(creator_key) WHERE s.source_key=? ORDER BY 1,2''', (key,))]
    return dict(source_key=key, source_sha256=sha, dataset_id=dataset, status=state, candidates=candidates,
                title_only=title_only, creators=creators, policy=POLICY, dump_name=dump_name, **UNVERIFIED)


def export(index: Path, output: Path, *, max_output_mb=512):
    """Write one JSON line per source to a new gzip file, refusing outputs beyond the size bound."""
    if type(max_output_mb) is not int or max_output_mb < 1:
        raise ValueError('max_output_mb must be a positive integer')
    _guard(output)
    cap, lines = max_output_mb*MB, 0
    with closing(_ro(index)) as db, tempfile.TemporaryDirectory(dir=output.parent) as temp:
        dump_name = json.loads(db.execute('SELECT dump_json FROM provenance').fetchone()[0])['block']['dump_name']
        target = Path(temp)/'export.jsonl.gz'
        with target.open('wb') as raw, gzip.GzipFile(fileobj=raw, mode='wb', mtime=0) as stream:
            for key, sha, dataset, state in db.execute('SELECT source_key,source_sha256,dataset_id,status FROM queue ORDER BY source_key'):
                stream.write((json.dumps(source_record(db, key, sha, dataset, state, dump_name), ensure_ascii=False)+'\n').encode())
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
    for name in ('work-index', 'subset', 'score-metadata', 'output'):
        build.add_argument('--'+name, type=Path, required=True)
    build.add_argument('--dataset'); build.add_argument('--limit', type=int)
    commands.add_parser('status').add_argument('--index', type=Path, required=True)
    out = commands.add_parser('export')
    out.add_argument('--index', type=Path, required=True); out.add_argument('--output', type=Path, required=True)
    out.add_argument('--max-output-mb', type=int, default=512)
    args = parser.parse_args()
    if args.command == 'prepare':
        result = prepare(args.work_index, args.subset, args.score_metadata, args.output, dataset=args.dataset, limit=args.limit)
    elif args.command == 'status':
        result = status(args.index)
    else:
        result = export(args.index, args.output, max_output_mb=args.max_output_mb)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
