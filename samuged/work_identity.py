"""Resumable work candidates and phrase inheritance, never inferred reuse permission."""
from __future__ import annotations
import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import time
import urllib.parse
import urllib.request
import urllib.error
import uuid
import unicodedata

from .dataset import file_digest
from .metadata_links import USER_AGENT

POLICY = 'work-candidates-v3'
BASE = 'https://musicbrainz.org/ws/2/'


def now():
    return datetime.now(timezone.utc).isoformat()


def label(value):
    text = unicodedata.normalize('NFKD', (value or '').replace('_', ' ').casefold())
    text = ''.join(c for c in text if not unicodedata.combining(c)).replace("'", '').replace('’', '')
    return ' '.join(re.findall(r'\w+', text))[:250]


def creator_agreement(left, right):
    a, b = label(left).split(), label(right).split()
    if sorted(a) == sorted(b):
        return 'normalized_tokens' if a else None
    if len(a) != len(b) or len(a) < 2 or not any(len(x) >= 3 and x in b for x in a):
        return None
    remaining = b[:]
    for token in sorted(a, key=len, reverse=True):
        matches = [x for x in remaining if x == token or (min(len(x), len(token)) == 1 and x[0] == token[0])]
        if len(matches) != 1:
            return None
        remaining.remove(matches[0])
    return 'initials_candidate'


def mbid(value):
    if not isinstance(value, str) or str(uuid.UUID(value)) != value:
        raise ValueError('invalid MusicBrainz ID')
    return value


def open_db(path, *, create=False):
    target = path if create else Path(path).resolve(strict=True).as_uri()+'?mode=rw'
    db = sqlite3.connect(target, uri=True)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    db.execute('PRAGMA max_page_count=262144')
    db.execute('PRAGMA busy_timeout=1000')
    return db


def initialize(metadata: Path, output: Path):
    if output.exists() or output.is_symlink():
        raise FileExistsError(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    # ASVS 5.2.4: keep a storage reserve and bound the derived database.
    if shutil.disk_usage(output.parent).free < 11 * 1024**3:
        raise ValueError('10 GiB reserve required')
    digest = file_digest(metadata)
    target = output.with_name(output.name+'.'+str(uuid.uuid4())+'.tmp')
    try:
        with closing(open_db(target, create=True)) as db, closing(sqlite3.connect(
                metadata.resolve(strict=True).as_uri()+'?mode=ro', uri=True)) as source:
            db.execute('PRAGMA max_page_count=262144')
            db.executescript('''
                CREATE TABLE provenance(metadata_sha256 TEXT, policy TEXT, created_on TEXT);
                CREATE TABLE queue(source_key TEXT PRIMARY KEY, source_sha256 TEXT,
                    dataset_id TEXT, title TEXT, creator TEXT, query_kind TEXT,
                    status TEXT, error TEXT, updated_on TEXT);
                CREATE INDEX queue_status ON queue(status,dataset_id,source_key);
                CREATE TABLE cache(request_key TEXT PRIMARY KEY, url TEXT,
                    payload_json TEXT, payload_sha256 TEXT, retrieved_on TEXT);
                CREATE TABLE work_candidates(source_key TEXT REFERENCES queue,
                    work_id TEXT, recording_id TEXT, title TEXT, evidence_json TEXT,
                    match_status TEXT CHECK(match_status='candidate'),
                    PRIMARY KEY(source_key,work_id,recording_id));
                CREATE TABLE reviews(revision INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_key TEXT REFERENCES queue, work_id TEXT,
                    decision TEXT CHECK(decision IN ('accepted','rejected','unresolved')),
                    reviewer TEXT, evidence_url TEXT, reasoning TEXT, reviewed_on TEXT);
                CREATE INDEX review_source ON reviews(source_key,revision);
                CREATE TABLE rights_observations(revision INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_key TEXT REFERENCES queue, work_id TEXT, provider TEXT,
                    rights_layer TEXT, intended_use TEXT, territory TEXT,
                    holder TEXT, license_declaration TEXT, conditions_json TEXT,
                    metadata_license TEXT, evidence_url TEXT, observed_on TEXT,
                    reviewer TEXT, status TEXT CHECK(status='claimed_unverified'));
                CREATE INDEX rights_source ON rights_observations(source_key,revision);
                CREATE TABLE provider_access(provider TEXT PRIMARY KEY, status TEXT,
                    evidence_url TEXT, reviewed_on TEXT);
            ''')
            for key, sha, dataset, artist, title, composer in source.execute(
                    'SELECT source_key,source_sha256,dataset_id,artist,title,composer FROM records ORDER BY source_key'):
                kind = 'recording' if dataset == 'lakh' else 'work'
                creator = artist if kind == 'recording' else composer
                queue_status = 'pending' if label(title) and label(creator) else 'missing_labels'
                db.execute('INSERT INTO queue VALUES (?,?,?,?,?,?,?,?,?)',
                    (key, sha, dataset, title, creator, kind, queue_status, None, now()))
            db.execute('INSERT INTO provenance VALUES (?,?,?)', (digest, POLICY, now()))
            db.execute('INSERT INTO provider_access VALUES (?,?,?,?)',
                ('the_mlc', 'access_required', 'https://www.themlc.com/data-programs-all', now()))
            db.execute('PRAGMA user_version=1')
            if file_digest(metadata) != digest:
                raise ValueError('metadata changed')
            db.commit()
        os.link(target, output)
    finally:
        target.unlink(missing_ok=True)
    return status(output)


def project(entity, data):
    """Retain core entities and relationships, exclude scores, tags and annotations."""
    result = {}
    for key in ('id', 'title', 'iswcs'):
        if key in data:
            result[key] = data[key]
    if entity == 'work':
        result['aliases'] = [x['name'] for x in data.get('aliases', []) if isinstance(x, dict) and isinstance(x.get('name'), str)]
    if entity == 'recording':
        result['artist-credit'] = [dict(name=x.get('name', x.get('artist', {}).get('name', '')),
            joinphrase=x.get('joinphrase', '')) for x in data.get('artist-credit', []) if isinstance(x, dict)]
    relations = []
    for rel in data.get('relations', []):
        if rel.get('target-type') == 'work' and isinstance(rel.get('work'), dict):
            relations.append(dict(type=rel.get('type'), work=project('work', rel['work'])))
        elif rel.get('target-type') == 'artist' and rel.get('type') in {'composer', 'writer', 'lyricist'}:
            artist = rel.get('artist', {})
            relations.append(dict(type=rel['type'], artist=dict(id=artist.get('id'), name=artist.get('name'))))
    result['relations'] = relations
    return result


class BudgetReached(Exception):
    pass


class Client:
    def __init__(self, db, budget):
        self.db, self.budget, self.requests, self.last = db, budget, 0, time.monotonic()
        self.opener = urllib.request.build_opener(NoRedirect())

    def get(self, entity, identifier=None, query=None):
        if entity not in {'work', 'recording'}:
            raise ValueError('unsupported entity')
        path = entity+'/' + (mbid(identifier) if identifier else '')
        params = {'fmt': 'json'}
        if query is not None:
            params.update(query=query, limit=5)
        elif entity == 'recording':
            params['inc'] = 'work-rels'
        else:
            params['inc'] = 'artist-rels+aliases'
        # ASVS 1.2.2, 13.2.4: fixed HTTPS host, validated IDs, encoded parameters.
        url = BASE+path+'?'+urllib.parse.urlencode(params)
        key = hashlib.sha256(url.encode()).hexdigest()
        cached = self.db.execute('SELECT payload_json,retrieved_on,payload_sha256 FROM cache WHERE request_key=?', (key,)).fetchone()
        if cached:
            if hashlib.sha256(cached[0].encode()).hexdigest() != cached[2]:
                raise ValueError('cache hash mismatch')
            return json.loads(cached[0]), dict(url=url, retrieved_on=cached[1], payload_sha256=cached[2])
        if shutil.disk_usage(Path(self.db.execute('PRAGMA database_list').fetchone()[2]).parent).free < 10.1*1024**3:
            raise ValueError('storage reserve reached')
        # ASVS 13.2.6: bounded attempts, response size, timeout and service backoff.
        for attempt in range(3):
            if self.requests >= self.budget:
                raise BudgetReached()
            time.sleep(max(0, 1.1-(time.monotonic()-self.last)))
            self.last = time.monotonic(); self.requests += 1
            try:
                with self.opener.open(urllib.request.Request(url, headers={'User-Agent': USER_AGENT}), timeout=15) as response:
                    payload = response.read(1024*1024+1)
                break
            except urllib.error.HTTPError as exc:
                if exc.code not in {429, 503} or attempt == 2:
                    raise
                retry = (exc.headers.get('Retry-After') or '') if exc.headers else ''
                if retry and (not retry.isdigit() or int(retry) > 60):
                    raise  # Do not retry before an unhandled server cooldown.
                time.sleep(max(int(retry or 0), 5*(3**attempt)))
        if len(payload) > 1024*1024:
            raise ValueError('response exceeds 1 MiB')
        raw = json.loads(payload)
        if not isinstance(raw, dict):
            raise ValueError('invalid API response')
        if query is not None:
            data = {entity+'s': [project(entity, x) for x in raw.get(entity+'s', [])[:5]]}
        else:
            if raw.get('id') != identifier:
                raise ValueError('API entity mismatch')
            data = project(entity, raw)
        encoded = json.dumps(data, ensure_ascii=False, sort_keys=True)
        sha = hashlib.sha256(encoded.encode()).hexdigest(); date = now()
        self.db.execute('INSERT INTO cache VALUES (?,?,?,?,?)', (key, url, encoded, sha, date))
        self.db.commit()
        return data, dict(url=url, retrieved_on=date, payload_sha256=sha)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('API redirect refused')


def resolve(db, client, row):
    kind = row['query_kind']; title = label(row['title']); creator = label(row['creator'])
    # Work search is title based. Writer agreement is checked on the work lookup.
    query = f'{kind}:"{title}"' if kind == 'recording' else f'(work:"{title}" OR alias:"{title}")'
    query += ''.join(' AND artist:'+token for token in creator.split() if len(token)>1)
    found, search_evidence = client.get(kind, query=query)
    results = []
    source_basis = 'original_catalog_labels_unverified'
    if db.execute("SELECT 1 FROM sqlite_master WHERE name='track_metadata'").fetchone():
        audit = db.execute('SELECT creator_basis FROM track_metadata WHERE source_key=?', (row['source_key'],)).fetchone()
        if audit:
            source_basis = audit[0]
    for candidate in found.get(kind+'s', []):
        if kind == 'recording' and label(candidate.get('title')) != title:
            continue
        entity_id = mbid(candidate['id'])
        if kind == 'recording':
            credit = ''.join(x['name']+x['joinphrase'] for x in candidate['artist-credit'])
            if not creator_agreement(credit, creator):
                continue
        details, lookup_evidence = client.get(kind, identifier=entity_id)
        works = [details] if kind == 'work' else [r['work'] for r in details['relations'] if r.get('type') == 'performance' and 'work' in r]
        for work in works[:5]:
            work_id = mbid(work['id'])
            work_details, work_evidence = client.get('work', identifier=work_id)
            if kind == 'work' and title not in {label(work_details.get('title')), *[label(x) for x in work_details.get('aliases', [])]}:
                continue
            writers = [dict(name=r['artist']['name'], role=r['type'],
                agreement=creator_agreement(r['artist']['name'], creator))
                for r in work_details['relations']
                if r.get('type') in {'composer', 'writer', 'lyricist'}
                and creator_agreement(r.get('artist', {}).get('name'), creator)]
            if kind == 'work' and not writers:
                continue
            evidence = dict(provider='musicbrainz', policy=POLICY, metadata_license='CC0-1.0',
                metadata_license_url='https://musicbrainz.org/doc/About/Data_License',
                method='normalized_labels_names_or_initials_and_database_relationship_not_MIDI_identity',
                search=search_evidence, lookup=lookup_evidence, work_lookup=work_evidence,
                match_basis=dict(source_creator_basis=source_basis, query_title=row['title'],
                    query_creator=row['creator'], title_agreement=('recording_title_normalized' if kind == 'recording'
                        else 'canonical_title_normalized' if label(work_details.get('title')) == title else 'alias_normalized'),
                    creator_agreement=creator_agreement(credit, creator) if kind == 'recording' else writers,
                    linked_work_count=len(works), linked_works_truncated=len(works)>5,
                    musical_comparison='not_performed', source_identity_verified=False),
                work=work_details, musical_work_license_status='unknown', rights_holder_status='not_established')
            results.append((row['source_key'], work_id, entity_id if kind == 'recording' else '',
                work_details.get('title'), json.dumps(evidence, ensure_ascii=False), 'candidate'))
    distinct = len({item[1] for item in results})
    for i, item in enumerate(results):
        evidence = json.loads(item[4])
        evidence['match_basis']['distinct_work_candidates'] = distinct
        evidence['match_basis']['multiple_work_candidates'] = distinct > 1
        results[i] = (*item[:4], json.dumps(evidence, ensure_ascii=False), item[5])
    return results


def run(path: Path, *, requests=50, sources=20, dataset=None):
    if type(requests) is not int or not 1 <= requests <= 500 or type(sources) is not int or not 1 <= sources <= 1000:
        raise ValueError('invalid pilot bounds')
    with closing(open_db(path)) as db:
        if db.execute('PRAGMA user_version').fetchone()[0] != 1:
            raise ValueError('unsupported work index')
        # Cache commits require a separate ownership lock across the complete run.
        import fcntl
        with path.with_suffix('.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            client = Client(db, requests)
            sql = "SELECT * FROM queue WHERE status IN ('pending','error')"
            params = []
            if dataset:
                sql += ' AND dataset_id=?'; params.append(dataset)
            rows = db.execute(sql+' ORDER BY source_key LIMIT ?', params+[sources]).fetchall()
            for row in rows:
                try:
                    results = resolve(db, client, row)
                except BudgetReached:
                    break  # Cached partial lookups make this source resumable.
                except Exception as exc:
                    db.execute('UPDATE queue SET status=?,error=?,updated_on=? WHERE source_key=?',
                        ('error', type(exc).__name__+(':'+str(exc.code) if hasattr(exc, 'code') else ''), now(), row['source_key']))
                    db.commit(); break
                db.executemany('INSERT OR REPLACE INTO work_candidates VALUES (?,?,?,?,?,?)', results)
                db.execute('UPDATE queue SET status=?,error=NULL,updated_on=? WHERE source_key=?',
                    ('candidate' if results else 'no_candidate', now(), row['source_key']))
                db.commit()
            result = status(path); result['network_requests'] = client.requests
            return result


def status(path):
    with closing(open_db(path)) as db:
        return dict(policy=POLICY, sources=db.execute('SELECT count(*) FROM queue').fetchone()[0],
            coverage=dict(db.execute('SELECT status,count(*) FROM queue GROUP BY status').fetchall()),
            work_candidates=db.execute('SELECT count(*) FROM work_candidates').fetchone()[0],
            unique_work_ids=db.execute('SELECT count(DISTINCT work_id) FROM work_candidates').fetchone()[0],
            cached_requests=db.execute('SELECT count(*) FROM cache').fetchone()[0],
            provider_access=[dict(r) for r in db.execute('SELECT * FROM provider_access')],
            published=False, all_rights_clearance='not_established')


def review(path, source_key, work_id, decision, reviewer, evidence_url, reasoning):
    if decision not in {'accepted', 'rejected', 'unresolved'}:
        raise ValueError('invalid identity decision')
    mbid(work_id)
    for value in (source_key, reviewer, reasoning):
        if not isinstance(value, str) or not 1 <= len(value.strip()) <= 2000:
            raise ValueError('review evidence required')
    url = urllib.parse.urlsplit(evidence_url)
    if url.scheme != 'https' or not url.netloc or url.username or url.password:
        raise ValueError('HTTPS evidence required')
    with closing(open_db(path)) as db:
        if not db.execute('SELECT 1 FROM work_candidates WHERE source_key=? AND work_id=?', (source_key, work_id)).fetchone():
            raise ValueError('unknown work candidate')
        db.execute('INSERT INTO reviews(source_key,work_id,decision,reviewer,evidence_url,reasoning,reviewed_on) VALUES (?,?,?,?,?,?,?)',
            (source_key, work_id, decision, reviewer, evidence_url, reasoning, now()))
        db.commit()
        return db.execute('SELECT max(revision) FROM reviews').fetchone()[0]


def phrase_evidence(catalog: Path, metadata: Path, identities: Path, *, source_key=None, limit=50):
    """Resolve rights by source at read time, so a review applies to every phrase."""
    if type(limit) is not int or not 1 <= limit <= 500:
        raise ValueError('invalid result limit')
    with closing(open_db(identities)) as db:
        # ASVS 1.2.4: paths and filters are parameters, attached inputs are read only.
        db.execute('ATTACH DATABASE ? AS catalog', (catalog.resolve(strict=True).as_uri()+'?mode=ro',))
        db.execute('ATTACH DATABASE ? AS metadata', (metadata.resolve(strict=True).as_uri()+'?mode=ro',))
        provenance = db.execute('SELECT metadata_sha256 FROM provenance').fetchone()[0]
        if file_digest(metadata) != provenance:
            raise ValueError('metadata hash mismatch')
        catalog_sha = db.execute('SELECT catalog_sha256 FROM metadata.provenance').fetchone()[0]
        if file_digest(catalog) != catalog_sha:
            raise ValueError('catalog hash mismatch')
        deadline = time.monotonic()+10
        db.set_progress_handler(lambda: int(time.monotonic() > deadline), 10000)
        # Original metadata is content bound at initialization. Source hashes are also checked per result.
        sql = '''SELECT p.phrase_key,p.source_key,p.start_tick,p.end_tick,p.kind,
            q.status AS identity_search_status,q.source_sha256,r.source_sha256 AS current_sha,
            w.musical_work_license_status,u.research_terms_status,u.redistribution_terms_status,
            u.commercial_terms_status,u.overall_clearance_status,
            v.revision,v.work_id,v.decision,v.evidence_url,v.reasoning
            FROM catalog.phrases p JOIN queue q USING(source_key)
            JOIN metadata.records r USING(source_key)
            JOIN metadata.source_rights w USING(source_key)
            JOIN metadata.source_usage u USING(source_key)
            LEFT JOIN reviews v ON v.revision=(SELECT max(revision) FROM reviews WHERE source_key=p.source_key)'''
        rows = db.execute(sql+(' WHERE p.source_key=?' if source_key else '')+' ORDER BY p.phrase_key LIMIT ?',
            ([source_key] if source_key else [])+[limit]).fetchall()
        has_audit = bool(db.execute("SELECT 1 FROM sqlite_master WHERE name='track_metadata'").fetchone())
        result = []
        for row in rows:
            item = dict(row)
            if has_audit:
                audit = db.execute('SELECT evidence_json FROM track_metadata WHERE source_key=?', (item['source_key'],)).fetchone()
                item['source_metadata_audit'] = json.loads(audit[0]) if audit else None
            if item.pop('current_sha') != item['source_sha256']:
                raise ValueError('source hash mismatch')
            item['work_id'] = item['work_id'] if item['decision'] == 'accepted' else None
            item['identity_status'] = item.pop('decision') or 'unresolved'
            item['metadata_input_sha256'] = provenance
            item['midi_publication_clearance'] = item['audio_publication_clearance'] = item['new_music_reuse_clearance'] = 'not_established'
            item['rights_observations'] = [dict(r) for r in db.execute('SELECT * FROM rights_observations WHERE source_key=? ORDER BY revision', (item['source_key'],))]
            item['candidates'] = [dict(r) for r in db.execute('SELECT DISTINCT work_id,title FROM work_candidates WHERE source_key=?', (item['source_key'],))]
            result.append(item)
        return result


def search_candidates(path, *, text=None, dataset=None, work_id=None, gap=None, limit=50):
    from .catalog_search import literal_like
    if type(limit) is not int or not 1 <= limit <= 500:
        raise ValueError('invalid result limit')
    for value in (text, dataset, gap):
        if value is not None and (not isinstance(value, str) or not 1 <= len(value) <= 250):
            raise ValueError('invalid search text')
    if work_id is not None:
        mbid(work_id)
    with closing(open_db(path)) as db:
        db.execute('PRAGMA query_only=ON')
        deadline = time.monotonic()+10
        db.set_progress_handler(lambda: int(time.monotonic() > deadline), 10000)
        clauses = []; params = []
        if gap:
            if not db.execute("SELECT 1 FROM sqlite_master WHERE name='track_metadata'").fetchone():
                raise ValueError('source label audit required')
            clauses.append('EXISTS(SELECT 1 FROM track_metadata t, json_each(t.gaps_json) g WHERE t.source_key=q.source_key AND g.value=?)')
            params.append(gap)
        if text:
            clauses.append("(q.title LIKE ? ESCAPE '\\' OR q.creator LIKE ? ESCAPE '\\' OR c.title LIKE ? ESCAPE '\\')")
            params.extend([literal_like(text)]*3)
        if dataset:
            clauses.append('q.dataset_id=?'); params.append(dataset)
        if work_id:
            clauses.append('c.work_id=?'); params.append(work_id)
        sql = """SELECT q.source_key,q.dataset_id,q.title AS source_title,q.creator,
            q.status,q.error,c.work_id,c.recording_id,c.title AS work_title,c.evidence_json
            FROM queue q LEFT JOIN work_candidates c USING(source_key)"""
        rows = db.execute(sql+(' WHERE '+' AND '.join(clauses) if clauses else '')+
            ' ORDER BY q.source_key,c.work_id,c.recording_id LIMIT ?', params+[limit]).fetchall()
        has_audit = bool(db.execute("SELECT 1 FROM sqlite_master WHERE name='track_metadata'").fetchone())
        result = []
        for row in rows:
            item = dict(row); item['work_evidence'] = json.loads(item.pop('evidence_json') or 'null')
            if has_audit:
                audit = db.execute('SELECT evidence_json FROM track_metadata WHERE source_key=?', (item['source_key'],)).fetchone()
                item['source_metadata_audit'] = json.loads(audit[0]) if audit else None
            item['match_status'] = 'candidate' if item['work_id'] else 'unresolved'
            result.append(item)
        return result


def observe_rights(path, *, source_key, work_id, provider, rights_layer, intended_use,
                   territory, holder, license_declaration, conditions,
                   metadata_license, evidence_url, reviewer):
    """Append a documented claim. It cannot grant permission or confirm identity."""
    mbid(work_id)
    if rights_layer not in {'composition', 'arrangement_transcription', 'performance'}:
        raise ValueError('invalid rights layer')
    if intended_use not in {'research', 'midi_publication', 'audio_publication', 'new_music_reuse'}:
        raise ValueError('invalid intended use')
    if provider not in {'manual', 'the_mlc'}:
        raise ValueError('unsupported ownership provider')
    for value in (source_key, territory, holder, license_declaration, metadata_license, reviewer):
        if not isinstance(value, str) or not 1 <= len(value.strip()) <= 2000:
            raise ValueError('rights evidence fields required')
    if not isinstance(conditions, list) or len(conditions) > 30 or any(
            not isinstance(x, str) or len(x) > 2000 for x in conditions):
        raise ValueError('invalid conditions')
    url = urllib.parse.urlsplit(evidence_url)
    if url.scheme != 'https' or not url.netloc or url.username or url.password:
        raise ValueError('HTTPS evidence required')
    with closing(open_db(path)) as db:
        if provider == 'the_mlc':
            access = db.execute('SELECT status FROM provider_access WHERE provider=?', (provider,)).fetchone()
            if not access or access[0] != 'authorized':
                raise ValueError('The MLC access and data terms required')
        if not db.execute('SELECT 1 FROM work_candidates WHERE source_key=? AND work_id=?',
                          (source_key, work_id)).fetchone():
            raise ValueError('unknown work candidate')
        db.execute("""INSERT INTO rights_observations(source_key,work_id,provider,
            rights_layer,intended_use,territory,holder,license_declaration,conditions_json,
            metadata_license,evidence_url,observed_on,reviewer,status)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,'claimed_unverified')""",
            (source_key, work_id, provider, rights_layer, intended_use, territory, holder,
             license_declaration, json.dumps(conditions), metadata_license, evidence_url, now(), reviewer))
        db.commit()
        return db.execute('SELECT max(revision) FROM rights_observations').fetchone()[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    init = sub.add_parser('init'); init.add_argument('--metadata', type=Path, required=True); init.add_argument('--output', type=Path, required=True)
    pilot = sub.add_parser('pilot'); pilot.add_argument('--index', type=Path, required=True); pilot.add_argument('--requests', type=int, default=50); pilot.add_argument('--sources', type=int, default=20); pilot.add_argument('--dataset')
    check = sub.add_parser('status'); check.add_argument('--index', type=Path, required=True)
    phrases = sub.add_parser('phrases')
    phrases.add_argument('--index', type=Path, required=True)
    phrases.add_argument('--metadata', type=Path, required=True)
    phrases.add_argument('--catalog', type=Path, required=True)
    phrases.add_argument('--source-key'); phrases.add_argument('--limit', type=int, default=50)
    decide = sub.add_parser('review'); decide.add_argument('--index', type=Path, required=True)
    decide.add_argument('--source-key', required=True); decide.add_argument('--work-id', required=True)
    decide.add_argument('--decision', choices=['accepted', 'rejected', 'unresolved'], required=True)
    decide.add_argument('--reviewer', required=True); decide.add_argument('--evidence-url', required=True)
    decide.add_argument('--reasoning', required=True)
    search = sub.add_parser('search'); search.add_argument('--index', type=Path, required=True)
    search.add_argument('--text'); search.add_argument('--gap'); search.add_argument('--dataset'); search.add_argument('--work-id'); search.add_argument('--limit', type=int, default=50)
    args = parser.parse_args()
    if args.command == 'init': result = initialize(args.metadata, args.output)
    elif args.command == 'pilot': result = run(args.index, requests=args.requests, sources=args.sources, dataset=args.dataset)
    elif args.command == 'phrases': result = phrase_evidence(args.catalog, args.metadata, args.index, source_key=args.source_key, limit=args.limit)
    elif args.command == 'search': result = search_candidates(args.index, text=args.text, dataset=args.dataset, work_id=args.work_id, gap=args.gap, limit=args.limit)
    elif args.command == 'review': result = dict(revision=review(args.index, args.source_key, args.work_id, args.decision, args.reviewer, args.evidence_url, args.reasoning))
    else: result = status(args.index)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
