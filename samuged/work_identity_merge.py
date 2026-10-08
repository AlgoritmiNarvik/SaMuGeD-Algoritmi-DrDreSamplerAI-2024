"""Portable per source work identity export that merges the API, dump works, dump recordings and dump catalogue indexes.

The module reads the API work index (v05), the offline dump works index, the offline dump recordings index, the
optional offline dump catalogue index and a candidate assessment, all read only, and writes one gzip JSON line per
API queue source, sorted by source key, plus a receipt next to the output. It never uses the network, never writes
to an input, never promotes a candidate to an accepted identity and never turns any field into a rights clearance.

Every source key of the dump indexes, the assessment and the metadata file must exist in the API queue with
the same source hash (the assessment has no hash and is bound by key), and the metadata file must cover the
API queue exactly. Any mismatch stops the run before an output exists.

Row schema (fixed, policy work-identity-merge-v3):

    source_key, source_sha256, dataset_id, title, creator, query_kind   API queue labels, unchanged
    api_status                  API queue status: candidate, no_candidate, pending, missing_labels
    dump_works_status           dump works queue status or null when the source is not in that queue
    dump_recordings_status      dump recordings queue status or null (only Lakh rows are queued there)
    dump_recordings_reason      dump recordings queue reason or null
    dump_catalogue_status       dump catalogue queue status or null (no catalogue index, or source absent there)
    dump_catalogue_reason       dump catalogue queue reason or null
    candidates                  list sorted by work_id, one entry per distinct MusicBrainz work:
        work_id, work_title, iswcs, providers, writers [{role, artist_id, name}],
        best_tier (assessment tier across providers, null when unassessed),
        title_agreement (strongest recorded), creator_agreement (strongest recorded kind),
        counts_as (the work id this candidate counts as in the assessment: the catalogue work whose part or
        version it is, or the lowest id of its duplicate family; null when it counts as itself or is unassessed)
        providers are musicbrainz, musicbrainz_json_dump, musicbrainz_fullexport and musicbrainz_fullexport_catalogue
    best_tier                   source_summary.best_tier or null
    review_priority             source_summary.review_priority or null
    assessment_reasons          source_summary reasons list, empty when unassessed
    identity_status             candidate_unverified when a candidate exists, else unresolved
    rights_clearance            always not_established
    policy                      work-identity-merge-v3

`pending` API rows are historical. The API chain stopped before they were looked up and the dump indexes
cover those sources instead.
"""
from __future__ import annotations
import argparse
from collections import Counter
from contextlib import closing, ExitStack
import fcntl
import gzip
import json
import os
from pathlib import Path
import sqlite3
import tempfile

from .candidate_assessment import FAVOUR, creator_kind
from .dataset import file_digest
from .work_identity import now

POLICY = 'work-identity-merge-v3'
API_PROVIDER, WORKS_PROVIDER, RECORDINGS_PROVIDER = 'musicbrainz', 'musicbrainz_json_dump', 'musicbrainz_fullexport'
CATALOGUE_PROVIDER = 'musicbrainz_fullexport_catalogue'
WRITER_ROLES = ('composer', 'writer', 'lyricist', 'librettist')
TITLES = ('canonical_title_normalized', 'recording_title_normalized', 'catalogue_number_attribute', 'catalogue_number_title',
          'alias_normalized', 'nickname_quoted')
CREATORS = ('normalized_tokens', 'composer_identity', 'initials_candidate', 'composer_name_single_namesake',
            'surname_subset')
FIELDS = ('source_key', 'source_sha256', 'dataset_id', 'title', 'creator', 'query_kind', 'api_status',
          'dump_works_status', 'dump_recordings_status', 'dump_recordings_reason', 'dump_catalogue_status',
          'dump_catalogue_reason', 'candidates', 'best_tier', 'review_priority', 'assessment_reasons',
          'identity_status', 'rights_clearance', 'policy')
CANDIDATE_FIELDS = ('work_id', 'work_title', 'iswcs', 'providers', 'writers', 'best_tier', 'title_agreement',
                    'creator_agreement', 'counts_as')
UNVERIFIED = dict(identity_verified=False, rights_clearance='not_established')


def _ro(path):
    return sqlite3.connect(Path(path).resolve(strict=True).as_uri()+'?mode=ro', uri=True)


def _guard(output: Path):
    receipt = receipt_path(output)
    if output.exists() or output.is_symlink() or receipt.exists() or receipt.is_symlink():
        raise FileExistsError(output)
    if not output.parent.is_dir():
        raise ValueError('output directory must exist')


def receipt_path(output: Path) -> Path:
    return output.with_name(output.name+'.receipt.json')


def _metadata_hashes(path: Path):
    """Source key to source hash from a usage metadata JSON lines file (gzip or plain)."""
    opener = gzip.open if path.suffix == '.gz' else open
    hashes = {}
    with opener(path, 'rt', encoding='utf-8') as stream:
        for line in stream:
            row = json.loads(line)
            key = row['source_key']
            if key in hashes:
                raise ValueError('duplicate source key in metadata')
            hashes[key] = row['source_sha256']
    return hashes


def _strongest(values, order):
    return next((v for v in order if v in values), None)


def _best_tier(tiers):
    tiers = set(tiers)
    if not tiers:
        return None
    if 'conflict' in tiers:
        return 'conflict'
    return next((t for t in FAVOUR if t in tiers), None)


def _writers(work):
    found = []
    for relation in [*(work.get('relations') or []), *(work.get('artist_relations') or [])]:
        if not isinstance(relation, dict) or relation.get('type') not in WRITER_ROLES:
            continue
        artist = relation.get('artist') or {}
        found.append((relation['type'], artist.get('id'), artist.get('name')))
    return found


def _candidates(db, key, provider):
    """Candidate rows of one index for one source, checked to be unverified queue candidates."""
    rows = []
    for work_id, title, encoded, match in db.execute(
            'SELECT work_id,title,evidence_json,match_status FROM work_candidates WHERE source_key=? '
            'ORDER BY work_id,recording_id', (key,)):
        evidence = json.loads(encoded or '{}')
        basis = evidence.get('match_basis') or {}
        if match != 'candidate' or basis.get('source_identity_verified') is True or evidence.get('identity_verified') is True:
            raise ValueError('candidate is not an unverified queue candidate')
        if evidence.get('provider', provider) != provider:
            raise ValueError('candidate provider differs from its index')
        rows.append((work_id, title, evidence, basis))
    return rows


def merge_candidates(groups, tiers, counts_as=None):
    """Merge (provider, rows) groups by work id. `tiers` maps work id to the assessed tiers of every provider and
    `counts_as` maps work id to the canonical work recorded by the assessment, when any."""
    merged = {}
    for provider, rows in groups:
        for work_id, title, evidence, basis in rows:
            work = evidence.get('work') or {}
            entry = merged.setdefault(work_id, dict(titles=[], iswcs=set(), providers=set(), writers=set(),
                                                    title_agreement=set(), creator_agreement=set()))
            entry['titles'].append((provider, work.get('title') or title))
            entry['iswcs'].update(work.get('iswcs') or [])
            entry['providers'].add(provider)
            entry['writers'].update(_writers(work))
            entry['title_agreement'].add(basis.get('title_agreement'))
            entry['creator_agreement'].add(creator_kind(basis.get('creator_agreement')))
    result = []
    for work_id in sorted(merged):
        e = merged[work_id]
        # Prefer the catalogue title, then the most recent dump, then the API title.
        order = {CATALOGUE_PROVIDER: 0, RECORDINGS_PROVIDER: 1, WORKS_PROVIDER: 2, API_PROVIDER: 3}
        title = next((t for _, t in sorted(e['titles'], key=lambda x: order.get(x[0], 3)) if t), None)
        result.append(dict(work_id=work_id, work_title=title, iswcs=sorted(e['iswcs']), providers=sorted(e['providers']),
            writers=[dict(role=r, artist_id=a, name=n) for r, a, n in
                     sorted(e['writers'], key=lambda w: tuple('' if x is None else x for x in w))],
            best_tier=_best_tier(tiers.get(work_id, ())),
            title_agreement=_strongest(e['title_agreement'], TITLES),
            creator_agreement=_strongest(e['creator_agreement'], CREATORS), counts_as=(counts_as or {}).get(work_id)))
    return result


def _lock(stack, work_index: Path):
    """Hold the work index lock when it exists, so a lookup runner started meanwhile fails fast."""
    path = Path(work_index).with_suffix('.lock')
    if not path.exists():
        return
    handle = stack.enter_context(path.open('rb'))
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise ValueError('work index lock held') from None
    stack.callback(fcntl.flock, handle, fcntl.LOCK_UN)


def _bind(work, index, sql, label):
    """Every key of another index must exist in the API queue with the same source hash."""
    for key, sha in index.execute(sql):
        row = work.execute('SELECT source_sha256 FROM queue WHERE source_key=?', (key,)).fetchone()
        if row is None:
            raise ValueError(f'{label} source missing from the work index')
        if sha is not None and row[0] != sha:
            raise ValueError(f'{label} source hash differs from the work index')


def prepare(work_index: Path, offline_index: Path, recordings_index: Path, assessment: Path, output: Path, *,
            metadata: Path, catalogue_index: Path | None = None):
    """Write the merged export and its receipt. Inputs are opened read only and re-hashed at the end."""
    work_index, offline_index, recordings_index, assessment, metadata, output = map(
        Path, (work_index, offline_index, recordings_index, assessment, metadata, output))
    _guard(output)
    paths = dict(work_index=work_index, offline_index=offline_index, recordings_index=recordings_index,
                 assessment=assessment, metadata=metadata)
    if catalogue_index is not None:
        catalogue_index = Path(catalogue_index)
        paths['catalogue_index'] = catalogue_index
    inputs = {k: dict(path=str(p), sha256=file_digest(p)) for k, p in paths.items()}
    counts = {k: Counter() for k in ('api_status', 'dump_works_status', 'dump_recordings_status',
                                     'dump_catalogue_status', 'identity_status', 'best_tier', 'dataset_id',
                                     'candidate_providers')}
    rows = candidates = 0
    with ExitStack() as stack:
        _lock(stack, work_index)
        work, offline, recordings, assessed = (stack.enter_context(closing(_ro(p))) for p in
                                               (work_index, offline_index, recordings_index, assessment))
        catalogue = None if catalogue_index is None else stack.enter_context(closing(_ro(catalogue_index)))
        hashes = _metadata_hashes(metadata)
        _bind(work, offline, 'SELECT source_key,source_sha256 FROM queue', 'dump works')
        _bind(work, recordings, 'SELECT source_key,source_sha256 FROM queue', 'dump recordings')
        if catalogue is not None:
            _bind(work, catalogue, 'SELECT source_key,source_sha256 FROM queue', 'dump catalogue')
        _bind(work, assessed, 'SELECT source_key,NULL FROM source_summary', 'assessment')
        temp_dir = stack.enter_context(tempfile.TemporaryDirectory(dir=output.parent))
        target = Path(temp_dir)/'export.jsonl.gz'
        with target.open('wb') as raw, gzip.GzipFile(fileobj=raw, mode='wb', mtime=0) as stream:
            for key, sha, dataset, title, creator, kind, api_status in work.execute(
                    'SELECT source_key,source_sha256,dataset_id,title,creator,query_kind,status FROM queue ORDER BY source_key'):
                if hashes.pop(key, None) != sha:
                    raise ValueError('metadata source hash differs from the work index')
                works = offline.execute('SELECT status FROM queue WHERE source_key=?', (key,)).fetchone()
                recs = recordings.execute('SELECT status,reason FROM queue WHERE source_key=?', (key,)).fetchone()
                cat = None if catalogue is None else catalogue.execute(
                    'SELECT status,reason FROM queue WHERE source_key=?', (key,)).fetchone()
                tiers, counts_as = {}, {}
                for work_id, tier, canonical in assessed.execute(
                        "SELECT work_id,tier,json_extract(signals_json,'$.canonical_work') FROM assessments WHERE source_key=?", (key,)):
                    tiers.setdefault(work_id, []).append(tier)
                    if canonical:
                        counts_as[work_id] = canonical
                summary = assessed.execute('SELECT best_tier,review_priority,reasons_json FROM source_summary '
                                           'WHERE source_key=?', (key,)).fetchone()
                groups = [(API_PROVIDER, _candidates(work, key, API_PROVIDER)),
                          (WORKS_PROVIDER, _candidates(offline, key, WORKS_PROVIDER)),
                          (RECORDINGS_PROVIDER, _candidates(recordings, key, RECORDINGS_PROVIDER))]
                if catalogue is not None:
                    groups.append((CATALOGUE_PROVIDER, _candidates(catalogue, key, CATALOGUE_PROVIDER)))
                merged = merge_candidates(groups, tiers, counts_as)
                record = dict(source_key=key, source_sha256=sha, dataset_id=dataset, title=title, creator=creator,
                    query_kind=kind, api_status=api_status, dump_works_status=works[0] if works else None,
                    dump_recordings_status=recs[0] if recs else None, dump_recordings_reason=recs[1] if recs else None,
                    dump_catalogue_status=cat[0] if cat else None, dump_catalogue_reason=cat[1] if cat else None,
                    candidates=merged, best_tier=summary[0] if summary else None,
                    review_priority=summary[1] if summary else None,
                    assessment_reasons=json.loads(summary[2] or '[]') if summary else [],
                    identity_status='candidate_unverified' if merged else 'unresolved',
                    rights_clearance='not_established', policy=POLICY)
                stream.write((json.dumps(record, ensure_ascii=False)+'\n').encode())
                rows += 1
                candidates += len(merged)
                for field in ('api_status', 'dump_works_status', 'dump_recordings_status', 'dump_catalogue_status',
                              'identity_status', 'best_tier', 'dataset_id'):
                    counts[field][str(record[field])] += 1
                for c in merged:
                    counts['candidate_providers']['+'.join(c['providers'])] += 1
        if hashes:
            raise ValueError('metadata has sources missing from the work index')
        if any(file_digest(Path(v['path'])) != v['sha256'] for v in inputs.values()):
            raise ValueError('input changed during prepare')
        receipt = dict(policy=POLICY, created_on=now(), inputs=inputs, rows=rows, candidates=candidates,
                       counts={k: dict(sorted(v.items())) for k, v in counts.items()}, fields=list(FIELDS),
                       candidate_fields=list(CANDIDATE_FIELDS), **UNVERIFIED)
        os.link(target, output)  # Fails rather than overwrite an output created meanwhile.
    receipt.update(output=str(output), output_sha256=file_digest(output), output_bytes=output.stat().st_size)
    with receipt_path(output).open('x') as stream:
        stream.write(json.dumps(receipt, indent=2, sort_keys=True)+'\n')
    return receipt


def status(path: Path):
    """Counts of an export, recomputed from its rows and compared with the receipt when present."""
    path = Path(path)
    counts = {k: Counter() for k in ('api_status', 'dump_works_status', 'dump_recordings_status',
                                     'dump_catalogue_status', 'identity_status', 'best_tier', 'dataset_id',
                                     'candidate_providers')}
    rows = candidates = 0
    previous = None
    with gzip.open(path, 'rt', encoding='utf-8') as stream:
        for line in stream:
            record = json.loads(line)
            if tuple(record) != FIELDS or record['rights_clearance'] != 'not_established':
                raise ValueError('row does not match the export schema')
            if previous is not None and record['source_key'] <= previous:
                raise ValueError('rows are not sorted by unique source key')
            previous = record['source_key']
            rows += 1
            candidates += len(record['candidates'])
            for field in ('api_status', 'dump_works_status', 'dump_recordings_status', 'dump_catalogue_status',
                          'identity_status', 'best_tier', 'dataset_id'):
                counts[field][str(record[field])] += 1
            for c in record['candidates']:
                counts['candidate_providers']['+'.join(c['providers'])] += 1
    result = dict(policy=POLICY, rows=rows, candidates=candidates,
                  counts={k: dict(sorted(v.items())) for k, v in counts.items()}, **UNVERIFIED)
    receipt = receipt_path(path)
    if receipt.exists():
        stored = json.loads(receipt.read_text())
        result['receipt_matches'] = (stored['rows'] == rows and stored['candidates'] == candidates
                                     and stored['counts'] == result['counts']
                                     and stored.get('output_sha256') == file_digest(path))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    commands = parser.add_subparsers(dest='command', required=True)
    build = commands.add_parser('prepare')
    for name in ('work-index', 'offline-index', 'recordings-index', 'assessment', 'metadata', 'output'):
        build.add_argument('--'+name, type=Path, required=True)
    build.add_argument('--catalogue-index', type=Path, help='optional offline dump catalogue index')
    commands.add_parser('status').add_argument('--export', type=Path, required=True)
    args = parser.parse_args()
    if args.command == 'prepare':
        result = prepare(args.work_index, args.offline_index, args.recordings_index, args.assessment, args.output,
                         metadata=args.metadata, catalogue_index=args.catalogue_index)
    else:
        result = status(args.export)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
