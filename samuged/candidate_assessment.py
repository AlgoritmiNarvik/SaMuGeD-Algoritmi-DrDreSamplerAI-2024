"""Assessment tiers and cross checks for unreviewed work candidates.

The module reads work candidates from the API work index and, when present, the offline
dump index, the offline recordings index and the offline catalogue index built from the full export. It never writes
identity reviews or rights observations, never modifies an input index, never opens the
network and never promotes a candidate to an accepted identity or a rights clearance. Every
output row is an assessment with signals for review.
"""
from __future__ import annotations
import argparse
import fcntl
from collections import defaultdict
from contextlib import closing
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import uuid

from .dataset import file_digest
from .work_identity import label

POLICY = 'candidate-assessment-v3'
CATALOGUE = 'musicbrainz_fullexport_catalogue'  # Provider name for documentation and tests, not used for logic.
TIERS = ('conflict', 'single_work_full_agreement', 'single_work_weaker_agreement', 'multiple_works')
PRIORITY = dict(zip(TIERS, range(4)))
FAVOUR = ('single_work_full_agreement', 'single_work_weaker_agreement', 'multiple_works')
# Agreement kinds in order of strength. The first kind present in the evidence is reported.
TITLE_KINDS = ('canonical_title_normalized', 'recording_title_normalized', 'catalogue_number_attribute', 'catalogue_number_title',
               'alias_normalized', 'nickname_quoted')
CREATOR_KINDS = ('normalized_tokens', 'composer_identity', 'initials_candidate', 'composer_name_single_namesake', 'surname_subset')
FULL_TITLE = {'canonical_title_normalized', 'recording_title_normalized', 'catalogue_number_attribute', 'catalogue_number_title'}
FULL_CREATOR = {'normalized_tokens', 'composer_identity'}
WRITER_ROLES = {'composer', 'writer', 'lyricist', 'librettist'}
# Words that describe the notice itself, sequencing or company form rather than a party.
STOP = set('''copyright copyrighted music musical publishing publications rights reserved inc ltd
    records all by and the arranged arrangement sequenced sequence sequencer midi file files version
    corporation corp company software studio studios productions international year name song songs
    professional written composed transcribed performed words lyrics with from this that used
    permission tous droits reserves'''.split())
STATUS = dict(identity_status='unverified_assessment_only', rights_clearance='not_established')
RESERVE = 10.75 * 1024**3
URL = 'https://musicbrainz.org/work/'


def now():
    return datetime.now(timezone.utc).isoformat()


def ro(path):
    return Path(path).resolve(strict=True).as_uri()+'?mode=ro'


def guard(output: Path):
    if output.exists() or output.is_symlink():
        raise FileExistsError(output)
    if not output.parent.is_dir():
        raise ValueError('output directory must exist')
    if shutil.disk_usage(output.parent).free < RESERVE:
        raise ValueError('10 GiB storage reserve required')


def publish(temp: Path, output: Path):
    try:
        os.link(temp, output)  # Fails rather than replacing a file created meanwhile.
    finally:
        temp.unlink(missing_ok=True)


def writers_of(evidence):
    names = [r.get('artist', {}).get('name') for r in (evidence.get('work') or {}).get('relations', [])
             if isinstance(r, dict) and r.get('type') in WRITER_ROLES]
    return list(dict.fromkeys(n for n in names if n))


def creator_kind(value):
    kinds = {value} if isinstance(value, str) else {x.get('agreement') for x in value or [] if isinstance(x, dict)}
    return next((k for k in CREATOR_KINDS if k in kinds), None)


def notice_check(notices, writers):
    texts = [n.get('text') or '' for n in notices if isinstance(n, dict)]
    if not any(t.strip() for t in texts):
        return 'no_notice', []
    words = set(label(' '.join(texts)).split())
    padded = ' '+label(' '.join(texts))+' '
    tokens = {w for name in writers for w in label(name).split()[-1:] if len(w) >= 4}
    matched = sorted(t for t in tokens if t in words) + sorted(
        label(n) for n in writers if label(n) and ' '+label(n)+' ' in padded)
    if matched:
        return 'corroborates', list(dict.fromkeys(matched))
    others = sorted({label(w) for t in texts for w in re.findall(r'[^\W\d_]{4,}', t)
                     if w[0].isupper() and label(w) not in STOP})
    return ('names_other_party', others) if others else ('uninformative', [])


def read_candidates(db, schema, origin):
    rows = db.execute(f'''SELECT c.source_key,c.work_id,c.recording_id,c.title,c.evidence_json,c.match_status,
        q.source_sha256,q.title,q.dataset_id FROM {schema}.work_candidates c
        LEFT JOIN {schema}.queue q USING(source_key)''').fetchall()
    result = []
    for key, work, recording, title, encoded, match, sha, query_title, dataset in rows:
        evidence = json.loads(encoded or '{}')
        if match != 'candidate' or sha is None or (evidence.get('match_basis') or {}).get('source_identity_verified') is True:
            raise ValueError('candidate is not an unverified queue candidate')
        result.append(dict(key=key, work=work, recording=recording or '', title=title, evidence=evidence, sha=sha, origin=origin,
            provider=evidence.get('provider') or 'unknown', query_title=query_title, dataset=dataset))
    return result


def prepare(work_index: Path, metadata: Path, output: Path, *, offline_index: Path | None = None, subset: Path | None = None,
            recordings_index: Path | None = None, catalogue_index: Path | None = None):
    """Build a new assessment index. All inputs are attached read only and re-hashed at the end.

    The work index lock is held for the whole build, so a lookup runner started meanwhile fails fast."""
    guard(output)
    with Path(work_index).with_suffix('.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('work index lock held') from None
        try:
            return build(work_index, metadata, output, offline_index, subset, recordings_index, catalogue_index)
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def build(work_index, metadata, output, offline_index, subset, recordings_index=None, catalogue_index=None):
    paths = dict(work_index=work_index, metadata=metadata, offline_index=offline_index, subset=subset,
                 recordings_index=recordings_index, catalogue_index=catalogue_index)
    inputs = {k: dict(path=str(p), sha256=file_digest(p)) for k, p in paths.items() if p is not None}
    temp = output.with_name(f'.{output.name}.{uuid.uuid4()}.tmp')
    try:
        with closing(sqlite3.connect(temp, uri=True)) as db:
            db.execute('PRAGMA max_page_count=262144')
            for schema, key in (('w', 'work_index'), ('m', 'metadata'), ('o', 'offline_index'), ('s', 'subset'), ('r', 'recordings_index'),
                                ('c', 'catalogue_index')):
                if paths[key] is not None:
                    db.execute(f'ATTACH DATABASE ? AS {schema}', (ro(paths[key]),))
            rows = read_candidates(db, 'w', 'work_index') + (read_candidates(db, 'o', 'offline_index') if offline_index else []) \
                + (read_candidates(db, 'r', 'recordings_index') if recordings_index else []) \
                + (read_candidates(db, 'c', 'catalogue_index') if catalogue_index else [])
            origins = defaultdict(set)
            for r in rows:
                origins[r['provider']].add(r['origin'])
            if any(len(v) > 1 for v in origins.values()):
                raise ValueError('a provider appears in both candidate indexes')  # One origin per provider.
            db.executescript('''CREATE TEMP TABLE keys(source_key TEXT PRIMARY KEY);
                CREATE TEMP TABLE hashes(musical_sha256 TEXT PRIMARY KEY);''')
            db.executemany('INSERT OR IGNORE INTO temp.keys VALUES (?)', [(r['key'],) for r in rows])
            queue = dict(db.execute('SELECT source_key,source_sha256 FROM w.queue JOIN temp.keys USING(source_key)'))
            records = {k: v for k, *v in db.execute('''SELECT source_key,source_sha256,musical_sha256,candidate_group
                FROM m.records JOIN temp.keys USING(source_key)''')}
            for r in rows:
                if not (r['sha'] == queue.get(r['key']) == (records.get(r['key']) or [None])[0]):
                    raise ValueError('source binding mismatch')
            db.executemany('INSERT OR IGNORE INTO temp.hashes VALUES (?)', [(v[1],) for v in records.values() if v[1]])
            twins = defaultdict(set)
            for key, music in db.execute('SELECT source_key,musical_sha256 FROM m.records WHERE musical_sha256 IN (SELECT musical_sha256 FROM temp.hashes)'):
                twins[music].add(key)
            notices = {k: json.loads(v or '[]') for k, v in db.execute(
                'SELECT source_key,copyright_notices_json FROM m.source_rights JOIN temp.keys USING(source_key)')}
            namesakes = {t: (w, a) for t, w, a in db.execute('SELECT normalized_title,work_count,alias_count FROM s.title_namesakes')} if subset else {}
            db.executescript('''
                CREATE TABLE provenance(policy TEXT, inputs_json TEXT, created_on TEXT,
                    identity_verified INTEGER CHECK(identity_verified=0), rights_clearance TEXT CHECK(rights_clearance='not_established'));
                CREATE TABLE assessments(source_key TEXT, work_id TEXT, provider TEXT, tier TEXT, signals_json TEXT,
                    policy TEXT, assessed_on TEXT, PRIMARY KEY(source_key,work_id,provider));
                CREATE INDEX assessment_tier ON assessments(tier);
                CREATE TABLE source_summary(source_key TEXT PRIMARY KEY, dataset_id TEXT, best_tier TEXT,
                    distinct_works INTEGER, providers_json TEXT, review_priority INTEGER, reasons_json TEXT,
                    identity_status TEXT CHECK(identity_status='unverified_assessment_only'),
                    rights_clearance TEXT CHECK(rights_clearance='not_established'));
                CREATE INDEX summary_priority ON source_summary(review_priority,dataset_id);''')
            result = assess(db, rows, records, twins, notices, namesakes)
            if any(file_digest(Path(v['path'])) != v['sha256'] for v in inputs.values()):
                raise ValueError('input changed during assessment')
            db.execute('INSERT INTO provenance VALUES (?,?,?,0,?)', (POLICY, json.dumps(inputs), now(), 'not_established'))
            db.commit()
            if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise ValueError('assessment integrity check failed')
        publish(temp, output)
    finally:
        temp.unlink(missing_ok=True)
    return dict(result, policy=POLICY, output=str(output), output_sha256=file_digest(output),
                output_bytes=output.stat().st_size, identity_verified=False, **STATUS)


def first_of(bases, field):
    """The first value recorded for a field across the match bases of one group, or None."""
    return next((b[field] for b in bases if b.get(field) is not None), None)


def work_families(rows):
    """Group the catalogue candidates of one source that are duplicate MusicBrainz works of one composer and one
    catalogue number: works sharing a specific key, or works sharing a bare key and an equal normalized title.

    MusicBrainz lists the same sonata or etude more than once (one entry per editor), so without this rule such
    sources count several works. Each family counts as its lowest work id. Nickname matches never form a family.
    Returns {(source key, work): (lowest work id, sorted members, rule)}."""
    groups = defaultdict(set)
    for r in rows:
        basis = r['evidence'].get('match_basis') or {}
        composer = (basis.get('composer') or {}).get('gid')
        key = basis.get('catalogue_key')
        if r['provider'] != CATALOGUE or not composer or not key or basis.get('title_agreement') == 'nickname_quoted':
            continue
        if basis.get('catalogue_key_specific') is True:
            groups[r['key'], 'catalogue_key', composer, key].add(r['work'])
        else:
            groups[r['key'], 'catalogue_key_and_title', composer, key, label(r['title'])].add(r['work'])
    families = {}
    for (key, rule, *_), works in groups.items():
        if len(works) > 1:
            members = sorted(works)
            for work in members:
                families[key, work] = (members[0], members, rule)
    return families


def canonical_works(rows):
    """Map (source key, work) to the candidate work it counts as: the catalogue work that lists it among its related
    parts, movements or versions, or the lowest work id of its duplicate family.

    The catalogue index reduces movements and arrangements to the work itself and records their ids, so a dump or
    API candidate for the first movement counts as the same work as the catalogue candidate for the sonata."""
    families = work_families(rows)
    parent = {}
    for r in sorted(rows, key=lambda r: (r['key'], r['work'])):
        own = families.get((r['key'], r['work']), (r['work'],))[0]
        for related in (r['evidence'].get('match_basis') or {}).get('related_work_ids') or []:
            parent.setdefault((r['key'], related), own)
    for (key, work), (lowest, _, _) in families.items():
        if work != lowest:
            parent[key, work] = lowest
    return parent, families


def assess(db, rows, records, twins, notices, namesakes):
    groups, works = defaultdict(list), defaultdict(lambda: defaultdict(set))
    parent, families = canonical_works(rows)
    for r in rows:
        groups[r['key'], r['work'], r['provider']].append(r)
        works[r['key']][r['provider']].add(parent.get((r['key'], r['work']), r['work']))
    summaries, assessed_on = defaultdict(list), now()
    for (key, work, provider), items in sorted(groups.items()):
        bases = [i['evidence'].get('match_basis') or {} for i in items]
        titles = {b.get('title_agreement') for b in bases}
        kinds = {creator_kind(b.get('creator_agreement')) for b in bases}
        evidence, own = items[0]['evidence'], works[key]
        writers = writers_of(evidence)
        counts = [b['title_namesake_count'] for b in bases if isinstance(b.get('title_namesake_count'), int)]
        title = label(items[0]['query_title'])
        # Canonical title namesakes only; alias only namesakes are recorded separately.
        namesake, alias = (min(counts), next((b.get('title_alias_namesake_count') for b in bases if 'title_alias_namesake_count' in b), None)) \
            if counts else namesakes.get(title, (None, None))
        music, group = records[key][1], records[key][2]
        others = {k for k in twins.get(music, set()) if k != key} if music else set()
        canonical = parent.get((key, work), work)
        family = families.get((key, work)) or families.get((key, canonical))  # Parts and other providers follow the family.
        mine = set().union(*own.values())
        rival = [set().union(*works[k].values()) for k in sorted(others) if k in works]
        duplicate = ('no_duplicates' if not rival else 'duplicates_conflict' if any(not (s & mine) for s in rival)
                     else 'duplicates_agree' if all(work in s for s in rival) else 'duplicates_partial')
        sets = list(own.values())
        # The dump checks every namesake, so a superset from one provider is expected, not a contradiction.
        # With three providers: agree when all sets are equal, differ when any pair is disjoint, overlap otherwise.
        cross = ('single_provider' if len(sets) < 2 else 'providers_agree' if all(s == sets[0] for s in sets)
                 else 'providers_differ' if any(not (a & b) for a in sets for b in sets) else 'providers_overlap')
        nested = cross == 'providers_overlap' and all(a <= b or b <= a for a in sets for b in sets)
        check, matched = notice_check(notices.get(key, []), writers)
        signals = dict(evidence_policy=evidence.get('policy'), origin=items[0]['origin'], work_title=items[0]['title'],
            canonical_work=canonical if canonical != work else None,
            work_family=family[1] if family else None, work_family_rule=family[2] if family else None,
            recording_ids=sorted({i['recording'] for i in items} - {''}),
            distinct_works=len(own[provider]), distinct_works_all_providers=len(mine),
            title_agreement=next((t for t in TITLE_KINDS if t in titles), None),
            creator_agreement_kind=next((k for k in CREATOR_KINDS if k in kinds), None),
            key_agreement=first_of(bases, 'key_agreement'), catalogue_key=first_of(bases, 'catalogue_key'),
            catalogue_key_specific=first_of(bases, 'catalogue_key_specific'), form_agreement=first_of(bases, 'form_agreement'),
            writers=writers, namesake_count=namesake,
            namesake_source='evidence' if counts else 'subset' if namesake is not None else None,
            title_alias_namesake_count=alias,
            notice_check=check, notice_tokens=matched, duplicate_check=duplicate, duplicate_count=len(others),
            duplicates_with_candidates=len(rival), candidate_group=group, provider_cross_check=cross, provider_sets_nested=nested,
            providers=sorted(p for p, s in own.items() if canonical in s), **STATUS)
        signals['tier'] = tier = tier_of(signals)
        db.execute('INSERT INTO assessments VALUES (?,?,?,?,?,?,?)',
                   (key, work, provider, tier, json.dumps(signals, ensure_ascii=False), POLICY, assessed_on))
        summaries[key].append((items[0]['dataset'], provider, signals))
    for key, entries in summaries.items():
        tiers = {s['tier'] for _, _, s in entries}
        best = 'conflict' if 'conflict' in tiers else next(t for t in FAVOUR if t in tiers)
        reasons = sorted({x for _, _, s in entries for x in reasons_of(s)})
        db.execute('INSERT INTO source_summary VALUES (?,?,?,?,?,?,?,?,?)', (key, entries[0][0], best,
            entries[0][2]['distinct_works_all_providers'], json.dumps(sorted({p for _, p, _ in entries})),
            priority(best, entries), json.dumps(reasons, ensure_ascii=False), *STATUS.values()))
    return dict(assessments=len(groups), sources=len(summaries),
                best_tiers=dict(db.execute('SELECT best_tier,count(*) FROM source_summary GROUP BY 1')))


def priority(best, entries):
    """Conflict 0; otherwise tier base times two, minus one when a notice corroborates a writer."""
    corroborated = any(s['notice_check'] == 'corroborates' for _, _, s in entries)
    return 0 if best == 'conflict' else PRIORITY[best]*2 - corroborated


def tier_of(s):
    # Notices usually name the sequencer or publisher, so they never set a conflict.
    if s['duplicate_check'] == 'duplicates_conflict' or s['provider_cross_check'] == 'providers_differ':
        return 'conflict'
    if s['distinct_works'] > 1 or s['distinct_works_all_providers'] > 1:
        return 'multiple_works'
    if s['title_agreement'] in FULL_TITLE and s['creator_agreement_kind'] in FULL_CREATOR and not s.get('work_family') \
            and s['namesake_count'] is not None and s['namesake_count'] <= 3 and s.get('key_agreement') != 'disagrees' \
            and s.get('form_agreement') != 'disagrees' \
            and (not s['title_agreement'].startswith('catalogue_number') or s.get('catalogue_key_specific') is True):
        return 'single_work_full_agreement'
    return 'single_work_weaker_agreement'


def reasons_of(s):
    out = []
    if s['notice_check'] == 'corroborates':
        out.append('copyright notice mentions writer: '+', '.join(s['notice_tokens']))
    if s['notice_check'] == 'names_other_party':
        out.append('copyright notice names another party: '+', '.join(s['notice_tokens'][:6]))
    out += {'duplicates_conflict': ['a musical duplicate has disjoint work candidates'],
            'duplicates_partial': ['musical duplicates overlap only partly'],
            'duplicates_agree': ['musical duplicates share this work']}.get(s['duplicate_check'], [])
    out += {'providers_differ': ['providers found disjoint work sets'],
            'providers_overlap': ['one provider found a subset of the other' if s['provider_sets_nested']
                                  else 'providers share some works but not all'],
            'providers_agree': ['all providers found the same works']}.get(s['provider_cross_check'], [])
    if s['distinct_works_all_providers'] > 1:
        out.append(f"{s['distinct_works_all_providers']} distinct work candidates")
    if s['title_agreement'] is None or s['creator_agreement_kind'] is None:
        out.append(f"match basis incomplete (evidence policy {s['evidence_policy']})")
    if s['title_agreement'] == 'alias_normalized':
        out.append('title agrees through an alias only')
    if s['title_agreement'] == 'nickname_quoted':
        out.append('title agrees through a quoted nickname only')
    if (s['title_agreement'] or '').startswith('catalogue_number') and s.get('catalogue_key_specific') is False:
        out.append('catalogue number is a bare opus without a number inside the opus')
    if s['creator_agreement_kind'] == 'initials_candidate':
        out.append('creator agrees by initials only')
    if s['creator_agreement_kind'] == 'surname_subset':
        out.append('creator agrees by surname only (single artist credit)')
    if s['creator_agreement_kind'] == 'composer_name_single_namesake':
        out.append('composer identified by name with a single namesake')
    if s.get('key_agreement') == 'disagrees':
        out.append('work key differs from the title key')
    if s.get('form_agreement') == 'disagrees':
        out.append('work form differs from the title form')
    if s['namesake_count'] is None:
        out.append('namesake count unknown')
    if (s['namesake_count'] or 0) > 3:
        out.append(f"{s['namesake_count']} works share this title")
    if s.get('work_family'):
        out.append(f"{len(s['work_family'])} duplicate works of one composer and catalogue number"
                   + (' and title' if s.get('work_family_rule') == 'catalogue_key_and_title' else '')
                   + ' count as the lowest work id')
    elif s.get('canonical_work'):
        out.append('candidate is a part or version of another candidate work and counts as that work')
    return out


def summary(assessment: Path):
    with closing(sqlite3.connect(ro(assessment), uri=True)) as db:
        tiers = defaultdict(dict)
        for dataset, tier, n in db.execute('SELECT dataset_id,best_tier,count(*) FROM source_summary GROUP BY 1,2'):
            tiers[dataset][tier] = n
        count = lambda field: dict(db.execute(f"SELECT json_extract(signals_json,'$.{field}'),count(*) FROM assessments GROUP BY 1"))
        return dict(policy=POLICY, sources=db.execute('SELECT count(*) FROM source_summary').fetchone()[0],
                    assessments=db.execute('SELECT count(*) FROM assessments').fetchone()[0], best_tier=dict(tiers),
                    notice_check=count('notice_check'), duplicate_check=count('duplicate_check'),
                    provider_cross_check=count('provider_cross_check'),
                    providers=dict(db.execute('SELECT provider,count(*) FROM assessments GROUP BY 1')),
                    identity_verified=False, **STATUS)


def packet(assessment: Path, work_index: Path, output: Path, *, offline_index: Path | None = None, tier=None, limit=200,
           recordings_index: Path | None = None, catalogue_index: Path | None = None):
    """Write a bounded JSON review packet. Nothing in it is an accepted identity."""
    if type(limit) is not int or not 1 <= limit <= 1000 or tier not in (None, *TIERS):
        raise ValueError('invalid packet bounds')
    guard(output)
    with closing(sqlite3.connect(ro(assessment), uri=True)) as db:
        db.row_factory = sqlite3.Row
        inputs = json.loads(db.execute('SELECT inputs_json FROM provenance').fetchone()[0])
        for key, path in (('work_index', work_index), ('offline_index', offline_index), ('recordings_index', recordings_index),
                          ('catalogue_index', catalogue_index)):
            if path is not None and (key not in inputs or file_digest(path) != inputs[key]['sha256']):
                raise ValueError(f'{key} does not match assessment provenance')
        digests = {p: file_digest(p) for p in (assessment, work_index, offline_index, recordings_index, catalogue_index) if p is not None}
        db.execute('ATTACH DATABASE ? AS w', (ro(work_index),))
        rows = db.execute('SELECT * FROM source_summary'+(' WHERE best_tier=?' if tier else '')+
                          ' ORDER BY review_priority,source_key LIMIT ?', ([tier] if tier else [])+[limit]).fetchall()
        sources = []
        for row in rows:
            q = db.execute('SELECT title,creator,query_kind FROM w.queue WHERE source_key=?', (row['source_key'],)).fetchone()
            candidates = [dict(work_id=c['work_id'], work_title=s['work_title'], writers=s['writers'], provider=c['provider'],
                               tier=c['tier'], signals=s, musicbrainz_url=URL+c['work_id'])
                          for c in db.execute('SELECT * FROM assessments WHERE source_key=? ORDER BY work_id,provider', (row['source_key'],))
                          for s in [json.loads(c['signals_json'])]]
            sources.append(dict(source_key=row['source_key'], dataset_id=row['dataset_id'], source_title=q['title'],
                source_creator=q['creator'], query_kind=q['query_kind'], best_tier=row['best_tier'],
                review_priority=row['review_priority'], reasons=json.loads(row['reasons_json']),
                identity_status=row['identity_status'], rights_clearance=row['rights_clearance'], candidates=candidates))
    document = dict(header=dict(policy=POLICY, notice='Review packet only. Nothing here is an accepted identity, '
        'a review decision or a rights clearance. Musical comparison was not performed.', tier=tier, limit=limit,
        sources=len(sources), created_on=now(), identity_verified=False, **STATUS), sources=sources)
    if any(file_digest(p) != digest for p, digest in digests.items()):
        raise ValueError('input changed while writing the packet')
    temp = output.with_name(f'.{output.name}.{uuid.uuid4()}.tmp')
    temp.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding='utf-8')
    publish(temp, output)
    return dict(output=str(output), sources=len(sources), candidates=sum(len(s['candidates']) for s in sources),
                output_sha256=file_digest(output), identity_verified=False, **STATUS)


def parser():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    build = sub.add_parser('prepare')
    for name in ('work-index', 'metadata', 'output'):
        build.add_argument('--'+name, type=Path, required=True)
    build.add_argument('--offline-index', type=Path); build.add_argument('--subset', type=Path)
    build.add_argument('--recordings-index', type=Path); build.add_argument('--catalogue-index', type=Path)
    count = sub.add_parser('summary'); count.add_argument('--assessment', type=Path, required=True)
    pack = sub.add_parser('packet')
    for name in ('assessment', 'work-index', 'output'):
        pack.add_argument('--'+name, type=Path, required=True)
    pack.add_argument('--offline-index', type=Path); pack.add_argument('--recordings-index', type=Path)
    pack.add_argument('--catalogue-index', type=Path)
    pack.add_argument('--tier', choices=TIERS)
    pack.add_argument('--limit', type=int, default=200)
    return parser


def main(argv=None):
    args = parser().parse_args(argv)
    if args.command == 'prepare':
        result = prepare(args.work_index, args.metadata, args.output, offline_index=args.offline_index, subset=args.subset,
                         recordings_index=args.recordings_index, catalogue_index=args.catalogue_index)
    elif args.command == 'summary':
        result = summary(args.assessment)
    else:
        result = packet(args.assessment, args.work_index, args.output, offline_index=args.offline_index, tier=args.tier,
                        limit=args.limit, recordings_index=args.recordings_index, catalogue_index=args.catalogue_index)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
