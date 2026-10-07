"""Offline provenance hints and a claim class for every source.

The module reads the immutable work identity index and the PDMX score metadata index read only and
writes a separate sidecar index. It never uses the network, never verifies or promotes an identity,
never maps a collection code to a manuscript and never treats a public domain declaration as clearance.
Every hint is a claim or a text pattern from existing labels, kept with the field it came from.
"""
from __future__ import annotations
import argparse
from contextlib import closing
import gzip
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import tempfile
from urllib.parse import urlsplit

from .dataset import file_digest
from .track_metadata import creator_kind
from .work_identity import label, now

POLICY = 'provenance-hints-v1'
RESERVE = 10.75 * 1024**3
CAP = 120
ARCHIVES = ('vwml.org', 'hymnary.org', 'imslp.org', 'themorrisring.org', 'abcnotation.com', 'tunearch.org',
            'thesession.org', 'archive.org', 'cpdl.org', 'library.efdss.org', 'musescore.com')
CATALOGUE = {'op', 'opus', 'bwv', 'k', 'kv', 'd', 'hob', 'hwv', 'rv', 'wq', 'twv', 's', 'l', 'woo', 'anh', 'sz',
             'bb', 'fp', 'h', 'm', 'z'}
# Catalogue prefixes, ordinary words and abbreviations that are never collection codes.
STOP = CATALOGUE | {'no', 'nr', 'num', 'nos', 'sonata', 'symphony', 'part', 'vol', 'volume', 'book', 'ex', 'fig',
                    'mvt', 'mov', 'movt', 'act', 'sc', 'track', 'take', 'var', 'bar', 'pt', 'ch', 'tr', 'ps',
                    'psalm', 'hymn', 'song', 'mix', 'ver', 'mr', 'mrs', 'dr', 'st', 'id', 'mp', 'op'}
CODE = re.compile(r'\b([A-Z][A-Za-z]{1,4})(\.?)(\d+(?:\.\d+)?)\b')
CAT = re.compile(r'\b(BWV|HWV|TWV|KV|K|D|Hob|RV|Wq|S|L|WoO|Anh|Sz|BB|FP|H|M|Z|[Oo]pus|[Oo]p)(\.?)\s?((?:[IVXL]+[a-z]?:)?(\d+)[a-z]?)\b')
YEAR = re.compile(r'\b(1[4-9]\d\d)(?:\s*[-–]\s*(1[4-9]\d\d))?\b')
LIFE = re.compile(r'\(?\s*\b(1[3-9]\d\d)\s*[-–]\s*(1[4-9]\d\d|20[0-2]\d)\b\s*\)?')
CONTEXT = re.compile(r'belegt|erstbeleg|datum|komponiert|quelle|\b(published|printed|collected|noted|circa|from|in)\b|(?<!\w)(c|ca)\.')
URL = re.compile(r'(?:https?://|www\.)[^\s<>"\']+', re.I)
COLLECTOR = re.compile(r'\b(noted by|collected by|sung by|transcribed by|arranged by|setting by|arr\.)', re.I)
ROLES = {'noted by': 'collector', 'collected by': 'collector', 'sung by': 'performer_source',
         'transcribed by': 'transcriber', 'arranged by': 'arranger', 'setting by': 'arranger', 'arr.': 'arranger'}
DANCE = re.compile(r'longways|for as many as will|\bhey\b|cast off|set and turn|rigadoon', re.I)
SETTING = re.compile(r'\b(\d+)(?:st|nd|rd|th)\s+setting\b|\bsetting\s+(\d+)\b', re.I)
URHEBER = re.compile(r'Urheber\s*:\s*(.+?)(?=Erstbeleg|Datum|Bezeichnung|Quelle|Komponiert|[\d(;]|$)', re.I)
STANDARD = re.compile(r'^\s*Bezeichnung standardisiert\s*:\s*(.*)$', re.I | re.S)
SACRED = re.compile(r'\b(hymn|psalm|chorale)', re.I)


def text(value, cap=CAP):
    return ' '.join(str(value).split())[:cap]


def url_hint(raw):
    """Full URL for public archive records, the domain only for anything else."""
    url = re.sub(r'(?<=\d)[A-Z][a-z]*$', '', raw.rstrip('.,;:)]'))
    parts = urlsplit(url if '://' in url else 'http://'+url)
    domain = (parts.hostname or '').removeprefix('www.')
    archive = any(domain == d or domain.endswith('.'+d) for d in ARCHIVES)
    if domain.endswith('musescore.com'):
        archive = bool(re.search(r'/scores?/\d+', parts.path))
    if archive:
        url = parts._replace(netloc=parts.hostname).geturl()
    return (url if archive else domain), dict(domain=domain, archive_record=archive)


def unattributed(value):
    return creator_kind(value) == 'unattributed' or str(value).strip().casefold() == 'unknown'


def life_dates(value):
    for match in LIFE.finditer(value):
        before = re.split(r'[:;/\n]', value[:match.start()])[-1]
        name = text(re.sub(r'^\s*Urheber\s*:?', '', before, flags=re.I).strip(' ,('), 80)
        born, died = int(match[1]), int(match[2])
        if (re.search(r'[^\W\d_]{2}', name) and not re.search(r'\d', name) and not CONTEXT.search(name.casefold()[-40:])
                and re.search(r'[^\W\d_.]\.?$', name) and 15 <= died-born <= 110):
            yield match, name


def extract(fields, title_status=None, search_title=None):
    """Return {(hint_type, value): (basis_field, evidence)} from (basis_field, kind, text) tuples."""
    hints, seen = {}, set()
    def add(kind, value, basis, **evidence):
        if value:
            hints.setdefault((kind, text(value, 300)), (basis, evidence))
    if title_status == 'identifier_only':
        add('identifier_only_title', search_title, 'track_metadata.search_title')
    for basis, kind, raw in fields:
        if raw in (None, '') or (kind, str(raw)) in seen:
            continue
        seen.add((kind, str(raw))); value = str(raw)[:4000]; creator = kind in ('creator', 'artist')
        for url in URL.findall(value):
            shown, evidence = url_hint(url)
            add('external_reference', shown, basis, **evidence)
        if kind == 'url':
            continue
        plain = URL.sub(' ', value)
        for match in CAT.finditer(plain if kind in ('title', 'subtitle') else ''):
            prefix = 'Op' if match[1].casefold() in ('op', 'opus') else match[1]
            if len(prefix) > 1 or match[2] or len(match[4]) >= 2:
                add('catalogue_number', f'{prefix} {match[3]}', basis)
        if kind in ('title', 'subtitle'):
            for match in CODE.finditer(plain):
                prefix, dot, number = match.groups()
                upper = sum(c.isupper() for c in prefix) >= 2
                if prefix.casefold() not in STOP and (dot or upper or '.' in number):
                    add('collection_code', match[0], basis, prefix=prefix, number=number, mapping='unmapped_requires_review')
            plain = CODE.sub(' ', plain)
        dated = []
        if creator:
            for match, name in life_dates(plain):
                dated.append(match.span())
                add('life_dates_claim', f'{match[1]}-{match[2]}', basis, name_text=name)
                bare = re.sub(r'^(attr\.?|attributed to)\s+', '', name, flags=re.I)
                if creator_kind(bare) == 'named_claim':
                    add('named_creator_extracted', bare, basis, raw=text(value), role='composer_claim_unverified',
                        **({'attribution_marker': True} if bare != name else {}))
            for match in URHEBER.finditer(plain):
                name = text(match[1].strip(' ,.'), 80)
                if creator_kind(name) == 'named_claim':
                    add('named_creator_extracted', name, basis, raw=text(value), role='composer_claim_unverified')
        for match in YEAR.finditer(plain):
            if any(a <= match.start() < b for a, b in dated):
                continue
            window = plain[max(0, match.start()-40):match.end()+20]
            if kind == 'creator' or CONTEXT.search(window.casefold()):
                add('year_claim', match[1] + (f'-{match[2]}' if match[2] else ''), basis, context=text(window, 80))
        marker = COLLECTOR.search(value)
        if creator and re.match(r'\s*after\s', value, re.I):
            add('collector_attribution', text(URL.split(value)[0]).strip(' :;,'), basis, role='collector')
        elif marker:
            add('collector_attribution', text(URL.split(value[marker.start():])[0]).strip(' :;,'), basis, role=ROLES[marker[1].casefold()])
        if creator and unattributed(value):
            add('unattributed_claim', text(value), basis)
        if kind == 'artist' and (re.match(r'misc(\b|ellaneous)', value.strip(), re.I) or value.strip().casefold() in {'anonymous', 'various', 'various artists'}):
            add('generic_uploader_artist', text(value), basis)
        if kind in ('title', 'subtitle') and (match := STANDARD.match(value)):
            add('standardized_title_claim', text(match[1]).rstrip(' ;'), basis, language='de')
        if kind == 'subtitle' and DANCE.search(value):
            add('dance_instruction', text(value), basis)
        if kind in ('title', 'subtitle'):
            for match in SETTING.finditer(value):
                add('setting_number', match[1] or match[2], basis, text=text(match[0]))
    return hints


def declaration(score):
    public, upstream = score.get('public_score_fields') or {}, score.get('upstream_declarations') or {}
    license_ = str(public.get('license') or '')
    flagged = public.get('is_public_domain') is True or upstream.get('is_public_domain') is True
    marked = re.search(r'publicdomain|public domain|cc0', license_, re.I)
    if not (flagged or marked):
        return None
    evidence = dict(is_public_domain=public.get('is_public_domain'), upstream_is_public_domain=upstream.get('is_public_domain'),
        license=license_ or None, license_id=public.get('license_id'), license_version=public.get('license_version'),
        license_url=upstream.get('license_url'), declaration_not_clearance=True)
    if marked and public.get('is_public_domain') is False and upstream.get('is_public_domain') is False:
        evidence['declaration_conflict'] = True
    return (license_ if marked else 'is_public_domain'), evidence


def classify(title_status, queue_creator, hints, titles=()):
    types = {kind for kind, _ in hints}
    values = lambda kind: [value for k, value in hints if k == kind]
    generic = values('generic_uploader_artist')
    domains = {evidence.get('domain') for (k, _), (_, evidence) in hints.items() if k == 'external_reference'}
    checks = [
        ('identifier_only_source', 'source_identifier_or_musical_review', title_status != 'usable', f'title_status:{title_status}'),
        ('named_creator_claim', 'title_and_creator_candidate_search',
         bool(queue_creator) and creator_kind(queue_creator) == 'named_claim', 'queue_creator_named_claim'),
        ('named_creator_claim', 'title_and_creator_candidate_search', 'named_creator_extracted' in types, 'named_creator_extracted'),
        ('dated_anonymous_source', 'title_only_namesake_review', bool(types & {'unattributed_claim', 'standardized_title_claim'})
         and bool(types & {'year_claim', 'life_dates_claim'}), 'unattributed_or_standardized_with_date'),
        ('traditional_collection_transcription', 'title_only_namesake_review', bool(types & {'collection_code', 'collector_attribution'})
         or any(v.casefold().startswith(('misc tunes', 'misc traditional')) for v in generic), 'collection_or_collector_or_misc_tunes'),
        ('hymn_or_sacred_reference', 'title_only_namesake_review', any(d == 'hymnary.org' or str(d).endswith('.hymnary.org') for d in domains)
         or any(v.casefold() == 'misc praise songs' for v in generic) or any(SACRED.search(t) for t in titles), 'sacred_reference'),
        ('unattributed_traditional', 'title_only_namesake_review', 'unattributed_claim' in types, 'unattributed_claim')]
    matched = [check for check in checks if check[2]]
    first = matched[0] if matched else ('title_only_unclassified', 'title_only_namesake_review', True, 'no_specific_signal')
    reasons = [check[3] for check in matched] or ['no_specific_signal']
    if any(k == 'upstream_pd_declaration' and evidence.get('declaration_conflict') for (k, _), (_, evidence) in hints.items()):
        reasons.append('upstream_pd_declaration_conflict')
    return first[0], first[1], reasons


def fields_for(row, track, score):
    original, upstream = track.get('original') or {}, track.get('upstream') or {}
    public = score.get('public_score_fields') or {}
    return [('queue.title', 'title', row['title']), ('track.original.title', 'title', original.get('title')),
        ('track.upstream.song_name', 'title', upstream.get('song_name')), ('score.title', 'title', public.get('title')),
        ('score.file_score_title', 'title', public.get('file_score_title')), ('score.song_name', 'title', public.get('song_name')),
        ('score.subtitle', 'subtitle', public.get('subtitle')), ('queue.creator', 'artist' if row['dataset_id'] == 'lakh' else 'creator', row['creator']),
        ('track.original.composer', 'creator', original.get('composer')), ('track.upstream.composer_name', 'creator', upstream.get('composer_name')),
        ('score.composer_name', 'creator', public.get('composer_name')), ('score.composer_claim', 'creator', row['composer_claim']),
        ('track.original.artist', 'artist', original.get('artist')), ('track.upstream.artist_name', 'artist', upstream.get('artist_name')),
        ('score.artist_name', 'artist', public.get('artist_name')), ('score.source_url', 'url', row['source_url']), ('score.url', 'url', public.get('url'))]


def guard_output(output: Path):
    if output.exists() or output.is_symlink():
        raise FileExistsError(output)
    if not output.parent.is_dir():
        raise ValueError('output directory must exist')
    if shutil.disk_usage(output.parent).free < RESERVE:
        raise ValueError('10 GiB storage reserve required')


def prepare(work_index: Path, score_metadata: Path, output: Path):
    guard_output(output)
    inputs = {str(p): file_digest(p) for p in (work_index, score_metadata)}
    with tempfile.TemporaryDirectory(dir=output.parent) as temp:
        target = Path(temp)/'hints.sqlite'
        with closing(sqlite3.connect(str(target), uri=True)) as db:
            db.row_factory = sqlite3.Row
            db.execute('PRAGMA max_page_count=262144')
            db.execute('ATTACH DATABASE ? AS w', (work_index.resolve().as_uri()+'?mode=ro',))
            db.execute('ATTACH DATABASE ? AS s', (score_metadata.resolve().as_uri()+'?mode=ro',))
            db.executescript('''
                CREATE TABLE provenance(policy TEXT,inputs_json TEXT,created_on TEXT,identity_verified INTEGER,rights_clearance TEXT);
                CREATE TABLE sources(source_key TEXT PRIMARY KEY,source_sha256 TEXT,dataset_id TEXT);
                CREATE TABLE hints(source_key TEXT REFERENCES sources,hint_type TEXT,value TEXT,basis_field TEXT,evidence_json TEXT,
                    PRIMARY KEY(source_key,hint_type,value));
                CREATE TABLE claim_class(source_key TEXT PRIMARY KEY REFERENCES sources,claim_class TEXT,search_route TEXT,
                    reasons_json TEXT,identity_status TEXT,rights_clearance TEXT);''')
            if db.execute('SELECT count(*) FROM s.score_metadata WHERE source_key NOT IN (SELECT source_key FROM w.queue)').fetchone()[0]:
                raise ValueError('score metadata source outside the work index')
            rows = db.execute('''SELECT q.source_key,q.source_sha256,q.dataset_id,q.title,q.creator,t.source_key AS tracked,t.title_status,
                t.evidence_json AS track_json,m.source_key AS scored,m.source_sha256 AS score_sha256,m.source_url,m.composer_claim,
                m.evidence_json AS score_json FROM w.queue q LEFT JOIN w.track_metadata t USING(source_key)
                LEFT JOIN s.score_metadata m USING(source_key) ORDER BY q.source_key''')
            for row in rows:
                key = row['source_key']
                if not row['source_sha256'] or row['tracked'] is None:
                    raise ValueError('incomplete source binding')
                track = json.loads(row['track_json'] or '{}'); score = json.loads(row['score_json'] or '{}') if row['scored'] else {}
                if row['scored'] and (row['score_sha256'] != row['source_sha256'] or score.get('source_sha256', row['source_sha256']) != row['source_sha256']):
                    raise ValueError('source binding mismatch')
                fields = fields_for(row, track, score)
                hints = extract(fields, row['title_status'], track.get('search_title') or row['title'])
                if score and (pd := declaration(score)):
                    hints.setdefault(('upstream_pd_declaration', pd[0]), ('score.public_score_fields.license', pd[1]))
                titles = [value for _, kind, value in fields if kind == 'title' and value]
                claim, route, reasons = classify(row['title_status'], row['creator'], hints, titles)
                db.execute('INSERT INTO sources VALUES (?,?,?)', (key, row['source_sha256'], row['dataset_id']))
                db.executemany('INSERT INTO hints VALUES (?,?,?,?,?)', [(key, kind, value, basis, json.dumps(evidence, ensure_ascii=False))
                    for (kind, value), (basis, evidence) in hints.items()])
                db.execute('INSERT INTO claim_class VALUES (?,?,?,?,?,?)', (key, claim, route, json.dumps(reasons), 'unverified', 'not_established'))
            db.executescript('CREATE INDEX hint_type ON hints(hint_type); CREATE INDEX claim ON claim_class(claim_class);')
            if any(file_digest(Path(p)) != digest for p, digest in inputs.items()):
                raise ValueError('input changed')
            db.execute('INSERT INTO provenance VALUES (?,?,?,?,?)', (POLICY, json.dumps(inputs), now(), 0, 'not_established'))
            db.commit()
            db.execute('DETACH DATABASE w'); db.execute('DETACH DATABASE s')
            if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok' or db.execute('PRAGMA foreign_key_check').fetchall():
                raise ValueError('index validation failed')
        result = summary(target)
        os.link(target, output)
    result.update(inputs=inputs, output_sha256=file_digest(output), output_bytes=output.stat().st_size, published=False)
    return result


def summary(hints: Path):
    with closing(sqlite3.connect(hints.resolve().as_uri()+'?mode=ro', uri=True)) as db:
        classes = {}
        for dataset, claim, count in db.execute('SELECT s.dataset_id,c.claim_class,count(*) FROM claim_class c JOIN sources s USING(source_key) GROUP BY 1,2 ORDER BY 1,3 DESC'):
            classes.setdefault(dataset, {})[claim] = count
        types = {kind: dict(rows=rows, sources=sources) for kind, rows, sources in
                 db.execute('SELECT hint_type,count(*),count(DISTINCT source_key) FROM hints GROUP BY 1 ORDER BY 2 DESC')}
        return dict(policy=db.execute('SELECT policy FROM provenance').fetchone()[0],
            sources=db.execute('SELECT count(*) FROM sources').fetchone()[0], claim_classes=classes, hint_types=types,
            identity_verified=False, rights_clearance='not_established')


def export(hints: Path, output: Path, *, max_output_mb=256):
    guard_output(output)
    limit = max_output_mb * 1024**2; lines = 0
    with tempfile.TemporaryDirectory(dir=output.parent) as temp:
        target = Path(temp)/'export.jsonl.gz'
        with closing(sqlite3.connect(hints.resolve().as_uri()+'?mode=ro', uri=True)) as db, target.open('wb') as raw, \
                gzip.GzipFile(fileobj=raw, mode='wb', mtime=0) as stream:
            policy = db.execute('SELECT policy FROM provenance').fetchone()[0]
            for key, digest, dataset, claim, route, reasons, identity, rights in db.execute('''SELECT s.source_key,s.source_sha256,s.dataset_id,
                    c.claim_class,c.search_route,c.reasons_json,c.identity_status,c.rights_clearance FROM sources s JOIN claim_class c USING(source_key)
                    ORDER BY s.source_key'''):
                items = [dict(hint_type=kind, value=value, basis_field=basis, evidence=json.loads(evidence)) for kind, value, basis, evidence in
                         db.execute('SELECT hint_type,value,basis_field,evidence_json FROM hints WHERE source_key=? ORDER BY hint_type,value', (key,))]
                stream.write((json.dumps(dict(source_key=key, source_sha256=digest, dataset_id=dataset, claim_class=claim, search_route=route,
                    reasons=json.loads(reasons), hints=items, identity_status=identity, rights_clearance=rights, policy=policy),
                    ensure_ascii=False)+'\n').encode()); lines += 1
                if raw.tell() > limit:
                    raise ValueError('export exceeds output limit')
        if target.stat().st_size > limit:
            raise ValueError('export exceeds output limit')
        os.link(target, output)
    return dict(lines=lines, output_sha256=file_digest(output), output_bytes=output.stat().st_size, policy=POLICY,
                identity_verified=False, rights_clearance='not_established')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    build = commands.add_parser('prepare')
    for name in ('work-index', 'score-metadata', 'output'):
        build.add_argument('--'+name, type=Path, required=True)
    commands.add_parser('summary').add_argument('--hints', type=Path, required=True)
    out = commands.add_parser('export')
    out.add_argument('--hints', type=Path, required=True); out.add_argument('--output', type=Path, required=True)
    out.add_argument('--max-output-mb', type=int, default=256)
    args = parser.parse_args()
    if args.command == 'prepare':
        result = prepare(args.work_index, args.score_metadata, args.output)
    elif args.command == 'summary':
        result = summary(args.hints)
    else:
        result = export(args.hints, args.output, max_output_mb=args.max_output_mb)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
