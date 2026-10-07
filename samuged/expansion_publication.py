"""Public Parquet files for the corpus expansion: PDMX and MAESTRO phrases plus per source metadata.

`prepare` builds a new folder that mirrors the dataset repository layout. It performs no upload and never writes
to an input. Phrase configurations reuse the published phrase schema unchanged. Artist and title come from the
combined catalog (upstream score or performance metadata), not from file paths. Every phrase is bound to its
catalog source through the catalog key `digest((build_id, source_id))` and checked against the catalog source
path, source hash and phrase row. Every exported MIDI file is hashed against its recorded `midi_sha256`.

Metadata configurations hold one row per catalog source and share the join columns `source_key`, `source_id`,
`source_sha256` and `dataset_id`. `source_id` is unique across the three corpora and joins phrases to metadata
exactly. `source_sha256` is not unique, because byte identical files occur under several sources.

Labels are evidence, not clearance. MusicBrainz candidates are unverified, and nothing in these files establishes
composition rights. The receipt records `identity_verified: false` and `rights_clearance: not_established`.
"""
from __future__ import annotations
import argparse
from collections import Counter
from contextlib import closing
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import uuid

from .corpus_release import audited_batches
from .dataset import digest, file_digest
from .publication_schema import phrase_schema
from .work_identity import now
from .work_identity_merge import FIELDS as IDENTITY_FIELDS, receipt_path

POLICY = 'expansion-publication-v1'
PHRASE_CONFIGS = ('pdmx_melodic', 'maestro_melodic')
METADATA_CONFIGS = ('source_terms', 'provenance_hints', 'work_identity')
WRITE_BATCH = 1000
SAMPLE = 1000
JOIN = ('source_key', 'source_id', 'source_sha256', 'dataset_id')
UNVERIFIED = dict(identity_verified=False, rights_clearance='not_established')

USAGE_INT = ('warning_count', 'search_limited', 'notice_truncated')
USAGE_JSON = ('corpus_conditions', 'copyright_notices', 'external_metadata_candidates', 'usage_conditions',
              'usage_evidence')
USAGE_TEXT = ('artist', 'title', 'composer', 'dataset_license', 'score_license_declaration', 'score_license_url',
              'composition_rights', 'redistribution_status', 'evidence_url', 'identity_evidence', 'status',
              'musical_sha256', 'candidate_group', 'evaluation_split', 'musical_work_license',
              'musical_work_license_status', 'musical_work_rights_holder', 'musical_work_evidence_url',
              'copyright_notice_status', 'copyright_notice_scope', 'scan_status', 'observed_sha256', 'scan_error',
              'reviewed_on', 'genre_raw', 'research_terms_status', 'redistribution_terms_status',
              'commercial_terms_status', 'overall_clearance_status', 'score_review_status', 'source_score_id',
              'score_metadata_path', 'usage_reviewed_on')
HINT_TEXT = ('claim_class', 'search_route', 'identity_status', 'rights_clearance', 'policy')
HINT_JSON = ('reasons', 'hints')
IDENTITY_TEXT = ('title', 'creator', 'query_kind', 'api_status', 'dump_works_status', 'dump_recordings_status',
                 'dump_recordings_reason', 'best_tier', 'identity_status', 'rights_clearance', 'policy')
IDENTITY_INT = ('review_priority',)
IDENTITY_JSON = ('candidates', 'assessment_reasons')

LICENSES = {
    'pdmx_melodic': dict(license='CC-BY-4.0', scope='PDMX corpus declaration',
        per_source='per score Public Domain Mark or CC0 declarations, kept in source_terms',
        source_url='https://zenodo.org/records/15571083'),
    'maestro_melodic': dict(license='CC-BY-NC-SA-4.0', scope='MAESTRO v3 declaration',
        conditions=['attribution', 'noncommercial use', 'share adapted material under the same license'],
        source_url='https://magenta.tensorflow.org/datasets/maestro'),
    **{name: dict(license='CC-BY-4.0', scope='SaMuGeD source metadata', musicbrainz_fields='CC0-1.0',
                  musicbrainz_license_url='https://musicbrainz.org/doc/About/Data_License')
       for name in METADATA_CONFIGS},
}


def metadata_schema(name):
    """Explicit Parquet schema of one metadata configuration."""
    import pyarrow as pa
    text = lambda names: [pa.field(n, pa.string()) for n in names]
    if name == 'source_terms':
        fields = text(JOIN) + text(USAGE_TEXT) + [pa.field(n, pa.int64()) for n in USAGE_INT] \
            + text(n+'_json' for n in USAGE_JSON)
    elif name == 'provenance_hints':
        fields = text(JOIN) + text(HINT_TEXT) + text(n+'_json' for n in HINT_JSON)
    elif name == 'work_identity':
        fields = text(JOIN) + text(IDENTITY_TEXT) + [pa.field('candidate_count', pa.int64())] \
            + [pa.field(n, pa.int64()) for n in IDENTITY_INT] + text(n+'_json' for n in IDENTITY_JSON)
    else:
        raise ValueError(f'unknown metadata configuration {name}')
    return pa.schema(fields)


def schema_of(name):
    return phrase_schema() if name in PHRASE_CONFIGS else metadata_schema(name)


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def _text(value):
    if value is None or isinstance(value, str):
        return value
    raise ValueError('expected a text value')


def _int(value):
    if value is None or type(value) is int:
        return value
    raise ValueError('expected an integer value')


def _jsonl(path: Path):
    opener = gzip.open if path.suffix == '.gz' else open
    with opener(path, 'rt', encoding='utf-8') as stream:
        for line in stream:
            yield json.loads(line)


class ShardWriter:
    """Streams rows into data/<name>/part-NNNNN.parquet files of at most `rows_per_file` rows."""
    def __init__(self, root: Path, name: str, schema, rows_per_file: int):
        self.folder, self.schema, self.limit = root/'data'/name, schema, rows_per_file
        self.folder.mkdir(parents=True)
        self.writer, self.buffer, self.rows, self.in_file, self.files = None, [], 0, 0, []

    def add(self, row):
        import pyarrow.parquet as pq
        if self.writer is None:
            path = self.folder/f'part-{len(self.files):05d}.parquet'
            self.writer = pq.ParquetWriter(path, self.schema, compression='zstd')
            self.files.append(path)
        self.buffer.append(row)
        self.rows += 1
        self.in_file += 1
        if len(self.buffer) >= WRITE_BATCH:
            self._flush()
        if self.in_file >= self.limit:
            self._flush()
            self.writer.close()
            self.writer, self.in_file = None, 0

    def _flush(self):
        import pyarrow as pa
        if self.buffer:
            self.writer.write_table(pa.Table.from_pylist(self.buffer, schema=self.schema))
            self.buffer.clear()

    def close(self):
        if self.writer is not None:
            self._flush()
            self.writer.close()
            self.writer = None


class Catalog:
    """Read only catalog lookups by primary key. Source keys are recomputed from build id and source id."""
    def __init__(self, path: Path):
        self.db = sqlite3.connect(Path(path).resolve(strict=True).as_uri()+'?mode=ro', uri=True)
        self.builds = {}
        for build_id, dataset in self.db.execute('SELECT build_id,dataset_id FROM builds'):
            if dataset in self.builds:
                raise ValueError('catalog has several builds for one dataset')
            self.builds[dataset] = build_id
        self.last = None

    def source(self, dataset, phrase):
        """Catalog source row for one phrase, verified against the phrase's own source fields."""
        build = self.builds.get(dataset)
        if build is None:
            raise ValueError(f'catalog has no {dataset} build')
        key = digest((build, phrase['source_id']))
        if self.last is None or self.last[0] != key:
            row = self.db.execute('SELECT source_key,source_id,source_path,source_sha256,artist,title,split_group '
                                  'FROM sources WHERE source_key=?', (key,)).fetchone()
            if row is None:
                raise ValueError('phrase source missing from the catalog')
            self.last = row
        _, source_id, path, sha, *_ = self.last
        if (source_id, path, sha) != (phrase['source_id'], phrase['source_path'], phrase['source_sha256']):
            raise ValueError('phrase source differs from the catalog')
        found = self.db.execute('SELECT kind FROM phrases WHERE phrase_key=?', (digest((key, phrase['phrase_id'])),)).fetchone()
        if found is None or found[0] != phrase['kind']:
            raise ValueError('phrase missing from the catalog')
        return self.last

    def by_key(self, key):
        return self.db.execute('''SELECT s.source_id,s.source_sha256,b.dataset_id FROM sources s JOIN builds b USING(build_id)
            WHERE s.source_key=?''', (key,)).fetchone()

    def count(self):
        return self.db.execute('SELECT count(*) FROM sources').fetchone()[0]

    def close(self):
        self.db.close()


def _audited(folder: Path):
    """Audit check for a single build folder, mirroring corpus_release.audited_batches."""
    audit = json.loads((folder/'audit.json').read_text())
    if not audit.get('passed'):
        raise ValueError('build audit failed')
    if not audit.get('full_source_coverage_required') or not audit.get('reextraction_required'):
        raise ValueError('build needs full independent replay')
    for name, field in (('sources.jsonl', 'source_manifest_sha256'), ('phrases.jsonl', 'phrase_manifest_sha256'),
                        ('build_config.json', 'build_config_sha256'), ('summary.json', 'summary_sha256')):
        if file_digest(folder/name) != audit[field]:
            raise ValueError('build artifact changed after audit')
    return audit


def phrase_row(folder: Path, record: dict, source, schema) -> dict:
    """One public phrase row. MIDI is read from the audited build and checked against its recorded hash."""
    relative = Path(record['midi_path'])
    if relative.is_absolute() or '..' in relative.parts:
        raise ValueError('MIDI hash or path mismatch')
    midi = (folder/relative).resolve(strict=True)
    if not midi.is_relative_to(folder.resolve()):
        raise ValueError('MIDI hash or path mismatch')
    payload = midi.read_bytes()
    if hashlib.sha256(payload).hexdigest() != record['midi_sha256']:
        raise ValueError('MIDI hash or path mismatch')
    key, _, path, sha, artist, title, group = source
    row = {k: record.get(k) for k in schema.names}
    row.update(source_path=path, source_sha256=sha, artist=artist, title=title, split='unassigned',
               split_group=group or key,
               occurrences_json=json.dumps(record['occurrences'], separators=(',', ':')),
               matcher_flags_json=json.dumps(record.get('matcher_flags', {}), sort_keys=True), midi_bytes=payload)
    return row


def _phrases(folder: Path, dataset: str, catalog: Catalog, writer: ShardWriter, schema, audit: dict, kinds: Counter):
    with (folder/'phrases.jsonl').open() as stream:
        for line in stream:
            record = json.loads(line)
            if record['kind'] != 'melodic':
                raise ValueError('expansion phrase configurations are melodic only')
            writer.add(phrase_row(folder, record, catalog.source(dataset, record), schema))
            kinds[dataset] += 1
    if file_digest(folder/'phrases.jsonl') != audit['phrase_manifest_sha256']:
        raise ValueError('phrase manifest changed during preparation')


def _metadata_row(name, record, catalog: Catalog, expected):
    """Map one input record to a metadata row with the fixed key set, bound to the catalog source."""
    if set(record) != expected:
        raise ValueError(f'{name} record keys differ from the expected schema')
    key = record['source_key']
    found = catalog.by_key(key)
    if found is None:
        raise ValueError(f'{name} source missing from the catalog')
    source_id, sha, dataset = found
    if (record['source_sha256'], record['dataset_id']) != (sha, dataset):
        raise ValueError(f'{name} source differs from the catalog')
    row = dict(source_key=key, source_id=source_id, source_sha256=sha, dataset_id=dataset)
    if name == 'source_terms':
        row.update({k: _text(record[k]) for k in USAGE_TEXT})
        row.update({k: _int(record[k]) for k in USAGE_INT})
        row.update({k+'_json': _json(record[k]) for k in USAGE_JSON})
    elif name == 'provenance_hints':
        row.update({k: _text(record[k]) for k in HINT_TEXT})
        row.update({k+'_json': _json(record[k]) for k in HINT_JSON})
    else:
        row.update({k: _text(record[k]) for k in IDENTITY_TEXT})
        row.update({k: _int(record[k]) for k in IDENTITY_INT})
        row.update(candidate_count=len(record['candidates']))
        row.update({k+'_json': _json(record[k]) for k in IDENTITY_JSON})
    if row.get('rights_clearance', 'not_established') != 'not_established':
        raise ValueError('a metadata row claims rights clearance')
    return row


METADATA_KEYS = {
    'source_terms': {'source_key', 'source_sha256', 'dataset_id', *USAGE_TEXT, *USAGE_INT, *USAGE_JSON},
    'provenance_hints': {'source_key', 'source_sha256', 'dataset_id', *HINT_TEXT, *HINT_JSON},
    'work_identity': set(IDENTITY_FIELDS),
}


def _inventory(root: Path, paths):
    files = {}
    for path in sorted(paths):
        files[path.relative_to(root).as_posix()] = dict(bytes=path.stat().st_size, sha256=file_digest(path))
    return files


def prepare(output: Path, *, pdmx_root: Path, maestro_dataset: Path, catalog: Path, usage: Path, hints: Path,
            identity: Path, assessment: Path, registry: Path, rows_per_file=50000):
    """Build the expansion folder atomically. The output must not exist."""
    import pyarrow  # noqa: F401  Fail before any work when the publication dependency is missing.
    if type(rows_per_file) is not int or rows_per_file < 1:
        raise ValueError('rows_per_file must be a positive integer')
    output, pdmx_root, maestro_dataset = Path(output), Path(pdmx_root), Path(maestro_dataset)
    if output.exists() or output.is_symlink():
        raise FileExistsError(output)
    if pdmx_root.name != 'pdmx_full':
        raise ValueError('pdmx_root must be the pdmx_full extraction folder')
    output.parent.mkdir(parents=True, exist_ok=True)
    selected, plan, finished = audited_batches(pdmx_root.parent)
    maestro_audit = _audited(maestro_dataset)
    identity_receipt = json.loads(receipt_path(Path(identity)).read_text())
    files = dict(catalog=catalog, usage=usage, hints=hints, identity=identity, identity_receipt=receipt_path(Path(identity)),
                 assessment=assessment, registry=registry)
    inputs = {k: dict(path=str(p), sha256=file_digest(Path(p))) for k, p in files.items()}
    if identity_receipt.get('output_sha256') != inputs['identity']['sha256']:
        raise ValueError('work identity export differs from its receipt')
    if identity_receipt['inputs']['assessment']['sha256'] != inputs['assessment']['sha256']:
        raise ValueError('work identity export was built from another assessment')
    registry_rows = {d['dataset_id']: d for d in json.loads(Path(registry).read_text())['sources']}
    for dataset, expected in (('pdmx', 'CC-BY-4.0'), ('maestro', 'CC-BY-NC-SA-4.0'), ('lakh', 'CC-BY-4.0')):
        if registry_rows.get(dataset, {}).get('dataset_license') != expected:
            raise ValueError(f'registry license for {dataset} differs from the card')
    inputs['pdmx'] = dict(path=str(pdmx_root), plan_sha256=file_digest(pdmx_root/'plan.json'), batches=len(selected),
        complete_extraction=finished, run_key=selected[0][2]['run_key'], code_sha256=selected[0][2]['code_sha256'],
        batch_audits_sha256=digest([(b.name, file_digest(b/'audit.json')) for b, _, _ in selected]))
    inputs['maestro'] = dict(path=str(maestro_dataset), audit_sha256=file_digest(maestro_dataset/'audit.json'),
        phrase_manifest_sha256=maestro_audit['phrase_manifest_sha256'])
    stage = output.with_name(f'.{output.name}.{uuid.uuid4().hex}.tmp')
    stage.mkdir()
    lookup = Catalog(Path(catalog))
    writers = []
    try:
        rows = Counter()
        pdmx = ShardWriter(stage, 'pdmx_melodic', phrase_schema(), rows_per_file); writers.append(pdmx)
        for batch, audit, _ in selected:
            _phrases(batch, 'pdmx', lookup, pdmx, pdmx.schema, audit, rows)
        pdmx.close()
        maestro = ShardWriter(stage, 'maestro_melodic', phrase_schema(), rows_per_file); writers.append(maestro)
        _phrases(maestro_dataset, 'maestro', lookup, maestro, maestro.schema, maestro_audit, rows)
        maestro.close()
        expected_phrases = sum(a['phrase_rows'] for _, a, _ in selected)
        if rows['pdmx'] != expected_phrases or rows['maestro'] != maestro_audit['phrase_rows']:
            raise ValueError('phrase rows differ from the audited counts')
        sources = lookup.count()
        keysets, datasets = {}, Counter()
        for name, path in (('source_terms', usage), ('provenance_hints', hints), ('work_identity', identity)):
            writer = ShardWriter(stage, name, metadata_schema(name), rows_per_file); writers.append(writer)
            seen = set()
            for record in _jsonl(Path(path)):
                row = _metadata_row(name, record, lookup, METADATA_KEYS[name])
                if row['source_key'] in seen:
                    raise ValueError(f'duplicate source key in {name}')
                seen.add(row['source_key'])
                if name == 'source_terms':
                    datasets[row['dataset_id']] += 1
                writer.add(row)
            writer.close()
            if len(seen) != sources:
                raise ValueError(f'{name} does not cover every catalog source')
            keysets[name] = seen
        if not keysets['source_terms'] == keysets['provenance_hints'] == keysets['work_identity']:
            raise ValueError('metadata configurations cover different sources')
        changed = [k for k, v in inputs.items() if 'sha256' in v and file_digest(Path(v['path'])) != v['sha256']]
        if changed:
            raise ValueError(f'input changed during preparation: {changed}')
        if file_digest(maestro_dataset/'audit.json') != inputs['maestro']['audit_sha256']:
            raise ValueError('MAESTRO audit changed during preparation')
        counts = dict(pdmx_melodic=rows['pdmx'], maestro_melodic=rows['maestro'],
                      **{n: len(keysets[n]) for n in METADATA_CONFIGS})
        configs = {w.folder.name: dict(rows=counts[w.folder.name], files=[p.relative_to(stage).as_posix() for p in w.files],
                                       fields=w.schema.names, **LICENSES[w.folder.name]) for w in writers}
        receipt = dict(policy=POLICY, created_on=now(), inputs=inputs, configs=configs, rows_per_file=rows_per_file,
            catalog_join='phrase source_key = digest((build_id, source_id)); catalog source path, source hash and phrase row checked',
            split_status='unassigned_pending_global_policy', sources=sources,
            dataset_sources=dict(sorted(datasets.items())),
            identity_export=dict(policy=identity_receipt['policy'], rows=identity_receipt['rows']), **UNVERIFIED)
        evidence = stage/'evidence'
        evidence.mkdir()
        (evidence/'expansion_build_receipt.json').write_text(json.dumps(receipt, indent=2, sort_keys=True)+'\n')
        listed = [p for p in stage.rglob('*') if p.is_file()]
        inventory = dict(policy=POLICY, files=_inventory(stage, listed))
        (evidence/'expansion_inventory.json').write_text(json.dumps(inventory, indent=2, sort_keys=True)+'\n')
        if output.exists():
            raise FileExistsError(output)
        stage.rename(output)
    finally:
        for writer in writers:
            if writer.writer is not None:
                writer.writer.close()
        lookup.close()
        if stage.exists():
            shutil.rmtree(stage)
    return dict(output=str(output), rows=counts, **UNVERIFIED)


def _sample(total, size=SAMPLE):
    """Deterministic evenly spaced row indices, every row when the table is small."""
    if total <= size:
        return list(range(total))
    return sorted({i*total//size for i in range(size)} | {total-1})


def verify(output: Path):
    """Re-read the folder: inventory hashes, schemas, row counts, sampled MIDI hashes and metadata coverage."""
    import pyarrow.parquet as pq
    output = Path(output)
    receipt = json.loads((output/'evidence'/'expansion_build_receipt.json').read_text())
    inventory = json.loads((output/'evidence'/'expansion_inventory.json').read_text())['files']
    for path, entry in inventory.items():
        target = output/path
        if not target.is_file() or target.stat().st_size != entry['bytes'] or file_digest(target) != entry['sha256']:
            raise ValueError(f'inventory mismatch for {path}')
    result, keysets, phrase_sources = {}, {}, set()
    for name in (*PHRASE_CONFIGS, *METADATA_CONFIGS):
        files = sorted((output/'data'/name).glob('*.parquet'))
        if [f.relative_to(output).as_posix() for f in files] != receipt['configs'][name]['files']:
            raise ValueError(f'{name} files differ from the receipt')
        expected = schema_of(name)
        handles = [pq.ParquetFile(f) for f in files]
        if any(not h.schema_arrow.equals(expected) for h in handles):
            raise ValueError(f'{name} schema differs from the expected schema')
        total = sum(h.metadata.num_rows for h in handles)
        if total != receipt['configs'][name]['rows']:
            raise ValueError(f'{name} row count differs from the receipt')
        if name in PHRASE_CONFIGS:
            wanted, offset, checked = set(_sample(total)), 0, 0
            for handle in handles:
                for group in range(handle.num_row_groups):
                    size = handle.metadata.row_group(group).num_rows
                    local = [i-offset for i in range(offset, offset+size) if i in wanted]
                    if local:
                        table = handle.read_row_group(group, columns=['midi_bytes', 'midi_sha256'])
                        payloads, hashes = table.column('midi_bytes'), table.column('midi_sha256')
                        for i in local:
                            if hashlib.sha256(payloads[i].as_py()).hexdigest() != hashes[i].as_py():
                                raise ValueError(f'{name} MIDI bytes differ from midi_sha256')
                            checked += 1
                    offset += size
                phrase_sources.update(handle.read(columns=['source_id']).column('source_id').to_pylist())
            result[name] = dict(rows=total, files=len(files), midi_checked=checked)
        else:
            keys, ids = [], set()
            for handle in handles:
                table = handle.read(columns=['source_key', 'source_id'])
                keys += table.column('source_key').to_pylist()
                ids.update(table.column('source_id').to_pylist())
            if len(set(keys)) != len(keys):
                raise ValueError(f'{name} source_key is not unique')
            keysets[name] = (set(keys), ids)
            result[name] = dict(rows=total, files=len(files))
    sets = [keysets[n][0] for n in METADATA_CONFIGS]
    if not sets[0] == sets[1] == sets[2]:
        raise ValueError('metadata configurations cover different sources')
    if not phrase_sources <= keysets['source_terms'][1]:
        raise ValueError('phrase source missing from source_terms')
    return dict(passed=True, configs=result, inventory_files=len(inventory), **UNVERIFIED)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    commands = parser.add_subparsers(dest='command', required=True)
    build = commands.add_parser('prepare')
    build.add_argument('--output', type=Path, required=True)
    for name in ('pdmx-root', 'maestro-dataset', 'catalog', 'usage', 'hints', 'identity', 'assessment', 'registry'):
        build.add_argument('--'+name, type=Path, required=True)
    build.add_argument('--rows-per-file', type=int, default=50000)
    commands.add_parser('verify').add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.command == 'prepare':
        result = prepare(args.output, pdmx_root=args.pdmx_root, maestro_dataset=args.maestro_dataset,
                         catalog=args.catalog, usage=args.usage, hints=args.hints, identity=args.identity,
                         assessment=args.assessment, registry=args.registry, rows_per_file=args.rows_per_file)
    else:
        result = verify(args.output)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
