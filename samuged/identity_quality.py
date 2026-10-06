"""Per source identity risks and searchable evidence, without permission inference."""
from __future__ import annotations
import argparse
from collections import Counter
from contextlib import closing
import gzip
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import tempfile

from .dataset import file_digest
from .work_identity import label, now, open_db

POLICY = 'identity-quality-v1'


def risk_flags(title, creator, *, creator_basis, title_creators=0, query_forms=0):
    flags = []
    normalized = label(title)
    if not normalized:
        flags.append('identity_title_missing')
    elif re.fullmatch(r'(untitled|song|track|unknown|new song|composition)( \d+)?', normalized):
        flags.append('identity_title_generic')
    if not creator:
        flags.append('identity_creator_missing')
    elif any(len(token) == 1 for token in label(creator).split()):
        flags.append('identity_creator_initials')
    if creator_basis in {'upstream_artist_role_unverified', 'equal_MIDI_bytes_creator_hint'}:
        flags.append('identity_creator_hint_unverified')
    if title_creators > 1:
        flags.append('identity_title_multiple_creators')
    if query_forms > 1:
        flags.append('identity_normalization_collision')
    return flags


def prepare(work_index: Path, metadata: Path, catalog: Path, output: Path):
    if output.exists() or output.is_symlink():
        raise FileExistsError(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    # ASVS 5.2.4: bound the output and preserve the corpus storage reserve.
    if shutil.disk_usage(output.parent).free < 12 * 1024**3:
        raise ValueError('10 GiB storage reserve required')
    inputs = {str(p): file_digest(p) for p in (work_index, metadata, catalog)}
    with tempfile.TemporaryDirectory(prefix='samuged-identity-quality-', dir=output.parent) as temp:
        target = Path(temp)/'index.sqlite'
        with closing(open_db(work_index)) as source, closing(open_db(target, create=True)) as db:
            source.backup(db)
            # ASVS 1.2.4: fixed SQL structure and bound input paths.
            db.execute('ATTACH DATABASE ? AS metadata', (metadata.resolve().as_uri()+'?mode=ro',))
            db.execute('ATTACH DATABASE ? AS catalog', (catalog.resolve().as_uri()+'?mode=ro',))
            if db.execute('SELECT metadata_sha256 FROM provenance').fetchone()[0] != inputs[str(metadata)]:
                raise ValueError('metadata binding mismatch')
            if db.execute('SELECT catalog_sha256 FROM metadata.provenance').fetchone()[0] != inputs[str(catalog)]:
                raise ValueError('catalog binding mismatch')
            for table in ('metadata.records', 'catalog.sources'):
                if db.execute(f'SELECT count(*) FROM queue q LEFT JOIN {table} s USING(source_key) WHERE s.source_key IS NULL OR q.source_sha256 IS NOT s.source_sha256').fetchone()[0]:
                    raise ValueError('source binding mismatch')
                if db.execute(f'SELECT count(*) FROM {table} s LEFT JOIN queue q USING(source_key) WHERE q.source_key IS NULL').fetchone()[0]:
                    raise ValueError('source coverage mismatch')
            db.executescript('''
                CREATE TABLE source_identity_quality(source_key TEXT PRIMARY KEY REFERENCES queue,
                    normalized_title TEXT, normalized_creator TEXT, source_path TEXT,
                    risks_json TEXT, evidence_json TEXT);
                CREATE INDEX quality_title ON source_identity_quality(normalized_title);
                CREATE INDEX quality_creator ON source_identity_quality(normalized_creator);
                CREATE TABLE identity_quality_provenance(input_hashes_json TEXT, policy TEXT, created_on TEXT);
            ''')
            rows = db.execute('''SELECT q.*, t.creator_basis, t.evidence_json AS audit,
                s.source_path, s.note_count, s.part_count, s.warning_count, s.search_limited,
                s.identity_evidence, w.scan_status, w.copyright_notice_status
                FROM queue q JOIN track_metadata t USING(source_key)
                JOIN catalog.sources s USING(source_key)
                JOIN metadata.source_rights w USING(source_key) ORDER BY source_key''').fetchall()
            if len(rows) != db.execute('SELECT count(*) FROM queue').fetchone()[0]:
                raise ValueError('incomplete source audit or rights coverage')
            titles, queries = {}, {}
            for row in rows:
                title, creator = label(row['title']), ' '.join(sorted(label(row['creator']).split()))
                if title and creator:
                    titles.setdefault(title, set()).add(creator)
                    queries.setdefault((title, creator), set()).add((row['title'], row['creator']))
            counts = Counter()
            for row in rows:
                title, creator = label(row['title']), ' '.join(sorted(label(row['creator']).split()))
                flags = risk_flags(row['title'], row['creator'], creator_basis=row['creator_basis'],
                    title_creators=len(titles.get(title, ())), query_forms=len(queries.get((title, creator), ())))
                audit = json.loads(row['audit'])
                if 'conflicting_duplicate_metadata' in audit['gaps']:
                    flags.append('identity_duplicate_creator_conflict')
                if not row['scan_status'].startswith('scanned'):
                    flags.append('copyright_notice_scan_unavailable')
                if row['warning_count'] or row['search_limited']:
                    flags.append('musical_extraction_warnings')
                counts.update(flags)
                evidence = dict(policy=POLICY, source_sha256=row['source_sha256'],
                    source_path=row['source_path'], filename_role='source_locator_and_search_hint_only',
                    original_identity_evidence=row['identity_evidence'],
                    query_title=row['title'], query_creator=row['creator'], creator_basis=row['creator_basis'],
                    title_distinct_creator_labels=len(titles.get(title, ())),
                    query_distinct_raw_label_forms=len(queries.get((title, creator), ())),
                    risks=flags, note_count=row['note_count'], part_count=row['part_count'],
                    warning_count=row['warning_count'], extraction_search_limited=bool(row['search_limited']),
                    copyright_notice_status=row['copyright_notice_status'], copyright_scan_status=row['scan_status'],
                    audit_identity_verification='not_performed', musical_comparison='not_performed',
                    overall_clearance_status='not_established')
                db.execute('INSERT INTO source_identity_quality VALUES (?,?,?,?,?,?)',
                    (row['source_key'], title, creator, row['source_path'], json.dumps(flags), json.dumps(evidence, ensure_ascii=False)))
            db.execute('INSERT INTO identity_quality_provenance VALUES (?,?,?)', (json.dumps(inputs), POLICY, now()))
            db.commit()
            if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok' or db.execute('PRAGMA foreign_key_check').fetchall():
                raise ValueError('index integrity failed')
            if any(file_digest(Path(p)) != sha for p, sha in inputs.items()):
                raise ValueError('input changed')
        os.link(target, output)
    return dict(policy=POLICY, sources=len(rows), risks=dict(counts), input_hashes=inputs,
        output_sha256=file_digest(output), bytes=output.stat().st_size, published=False)


def evidence(db, source_key):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='source_identity_quality'").fetchone():
        return None
    row = db.execute('SELECT evidence_json FROM source_identity_quality WHERE source_key=?', (source_key,)).fetchone()
    return json.loads(row[0]) if row else None


def export(index: Path, output: Path, *, max_output_mb=256):
    if type(max_output_mb) is not int or not 1 <= max_output_mb <= 512:
        raise ValueError('invalid export budget')
    if output.exists() or output.is_symlink():
        raise FileExistsError(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(output.parent).free < (10240+max_output_mb)*1024**2:
        raise ValueError('10 GiB storage reserve required')
    before = file_digest(index)
    with tempfile.TemporaryDirectory(prefix='samuged-quality-export-', dir=output.parent) as temp:
        target = Path(temp)/'quality.jsonl.gz'
        with closing(open_db(index)) as db, target.open('xb') as raw, gzip.GzipFile(filename='', fileobj=raw, mode='wb', mtime=0) as zipped:
            db.execute('PRAGMA query_only=ON')
            count = 0
            for row in db.execute('''SELECT q.source_key,q.dataset_id,q.status AS identity_search_status,
                t.evidence_json AS source_audit,s.evidence_json AS identity_quality
                FROM queue q JOIN track_metadata t USING(source_key)
                JOIN source_identity_quality s USING(source_key) ORDER BY q.source_key'''):
                item = dict(row)
                item['source_audit'] = json.loads(item['source_audit'])
                item['identity_quality'] = json.loads(item['identity_quality'])
                item['work_candidates'] = [dict(work_id=r['work_id'], title=r['title'], recording_id=r['recording_id'],
                    evidence=json.loads(r['evidence_json'])) for r in db.execute('SELECT * FROM work_candidates WHERE source_key=?', (row['source_key'],))]
                item['identity_reviews'] = [dict(r) for r in db.execute('SELECT * FROM reviews WHERE source_key=? ORDER BY revision', (row['source_key'],))]
                item['rights_observations'] = [dict(r) for r in db.execute('SELECT * FROM rights_observations WHERE source_key=? ORDER BY revision', (row['source_key'],))]
                zipped.write((json.dumps(item, ensure_ascii=False, allow_nan=False)+'\n').encode())
                count += 1
                if raw.tell() > max_output_mb*1024**2:
                    raise ValueError('export storage budget reached')
            if count != db.execute('SELECT count(*) FROM queue').fetchone()[0]:
                raise ValueError('export source coverage mismatch')
        if target.stat().st_size > max_output_mb*1024**2 or file_digest(index) != before:
            raise ValueError('export changed or storage budget reached')
        os.link(target, output)
    return dict(sources=count, input_sha256=before, output_sha256=file_digest(output), bytes=output.stat().st_size, published=False)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    for field in ('work-index', 'metadata', 'catalog', 'output'):
        p.add_argument('--'+field, type=Path, required=True)
    a = p.parse_args()
    print(json.dumps(prepare(a.work_index, a.metadata, a.catalog, a.output), indent=2))
