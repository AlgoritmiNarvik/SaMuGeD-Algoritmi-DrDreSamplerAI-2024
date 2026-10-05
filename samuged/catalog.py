"""Bounded SQLite metadata index for independently versioned corpus builds."""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import re
import shutil
import sqlite3
import tempfile

from .dataset import canonical_json, digest, file_digest

SCHEMA_VERSION = 1
MAX_LINE_BYTES = 16 * 1024 * 1024
RIGHTS = {"unknown", "declared", "verified", "restricted"}
FAMILIES = ("piano", "chromatic_percussion", "organ", "guitar", "bass", "strings",
            "ensemble", "brass", "reed", "pipe", "synth_lead", "synth_pad",
            "synth_effects", "ethnic", "percussive", "sound_effects")
SCHEMA = """
CREATE TABLE datasets(dataset_id TEXT PRIMARY KEY, name TEXT NOT NULL, version TEXT NOT NULL,
 source_url TEXT NOT NULL, dataset_license TEXT NOT NULL, composition_rights TEXT NOT NULL,
 redistribution_status TEXT NOT NULL, conditions_json TEXT NOT NULL, evidence_json TEXT NOT NULL);
CREATE TABLE builds(build_id TEXT PRIMARY KEY, dataset_id TEXT NOT NULL REFERENCES datasets,
 records_sha256 TEXT NOT NULL, imported_sources INTEGER NOT NULL);
CREATE TABLE sources(source_key TEXT PRIMARY KEY, build_id TEXT NOT NULL REFERENCES builds,
 source_id TEXT NOT NULL, source_path TEXT NOT NULL, source_sha256 TEXT, musical_sha256 TEXT,
 artist TEXT, title TEXT, identity_evidence TEXT NOT NULL, status TEXT NOT NULL, algorithm TEXT,
 note_count INTEGER, part_count INTEGER, warning_count INTEGER NOT NULL, repair_count INTEGER NOT NULL,
 search_limited INTEGER NOT NULL, curation_truncated INTEGER NOT NULL, split TEXT, split_group TEXT, metadata_json TEXT NOT NULL);
CREATE TABLE phrases(phrase_key TEXT PRIMARY KEY, source_key TEXT NOT NULL REFERENCES sources,
 phrase_id TEXT NOT NULL, kind TEXT NOT NULL, family_id TEXT, part_name TEXT, program INTEGER,
 instrument_family TEXT, start_tick INTEGER, end_tick INTEGER, duration_beats REAL,
 note_count INTEGER, occurrence_count INTEGER, recurrence_score REAL, pitch_min INTEGER,
 pitch_max INTEGER, velocity_mean REAL, onset_density REAL, meter_json TEXT,
 occurrences_json TEXT NOT NULL, matcher_flags_json TEXT NOT NULL);
CREATE TABLE annotations(source_key TEXT NOT NULL REFERENCES sources, category TEXT NOT NULL,
 value TEXT NOT NULL, evidence_url TEXT NOT NULL, method TEXT NOT NULL,
 PRIMARY KEY(source_key,category,value,evidence_url));
CREATE INDEX source_identity ON sources(artist,title);
CREATE INDEX source_sha ON sources(source_sha256);
CREATE INDEX source_musical ON sources(musical_sha256);
CREATE INDEX phrase_filters ON phrases(kind,instrument_family,occurrence_count,duration_beats);
CREATE INDEX annotations_filter ON annotations(category,value);
CREATE INDEX phrase_recurrence ON phrases(kind,occurrence_count DESC,duration_beats);
CREATE VIEW phrase_catalog AS SELECT p.*,s.artist,s.title,s.status,s.algorithm,s.source_sha256,
 s.metadata_json,s.warning_count,s.repair_count,s.search_limited,s.curation_truncated,s.split,
 d.dataset_id,d.dataset_license,d.composition_rights,d.redistribution_status
 FROM phrases p JOIN sources s USING(source_key) JOIN builds b USING(build_id)
 JOIN datasets d USING(dataset_id);
"""


def _rows(path):
    # ASVS 5.2.1: bound each record before decoding; never load a corpus in memory.
    with path.open('rb') as stream:
        while line := stream.readline(MAX_LINE_BYTES + 1):
            if len(line) > MAX_LINE_BYTES:
                raise ValueError("metadata record exceeds 16 MiB")
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError("metadata records must be objects")
            yield row


def _number(value):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
        raise ValueError("musical numeric fields must be finite numbers")
    return value


def _insert(db, table, values):
    # ASVS 1.2.4: static table names and bound parameters, including filenames and labels.
    assert table in {"datasets", "builds", "sources", "phrases", "annotations"}
    db.execute(f"INSERT INTO {table} VALUES ({','.join('?' for _ in values)})", values)


def build_catalog(manifest_path: Path, output: Path, *, max_output_mb=256, min_free_mb=1024):
    """Build a new index atomically. Refuse to overwrite an existing catalog."""
    if max_output_mb < 1 or min_free_mb < 0:
        raise ValueError("invalid storage budget")
    manifest = json.loads(manifest_path.read_text())
    if manifest.get('schema_version') != SCHEMA_VERSION:
        raise ValueError("unsupported manifest version")
    if output.exists() or output.is_symlink():
        raise FileExistsError(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(output.parent).free < (2 * max_output_mb + min_free_mb) * 1024**2:
        raise ValueError("insufficient free space for index and reserve")
    datasets = manifest['datasets']
    if not datasets or not manifest['builds']:
        raise ValueError("manifest needs datasets and builds")
    with tempfile.TemporaryDirectory(prefix='samuged-catalog-', dir=output.parent) as tmp:
        temp = Path(tmp) / 'catalog.sqlite'
        db = sqlite3.connect(temp)
        try:
            db.execute('PRAGMA foreign_keys=ON')
            db.execute('PRAGMA journal_mode=DELETE')
            db.execute('PRAGMA page_size=4096')
            db.execute(f'PRAGMA max_page_count={int(max_output_mb * 1024**2 // 4096)}')
            db.executescript(SCHEMA)
            db.execute(f'PRAGMA user_version={SCHEMA_VERSION}')
            for d in datasets:
                if not re.fullmatch(r'[a-z0-9_]+', d['dataset_id']):
                    raise ValueError("dataset IDs must use lowercase letters, numbers or underscores")
                if d['composition_rights'] not in RIGHTS or d['redistribution_status'] not in RIGHTS:
                    raise ValueError("invalid rights evidence status")
                if (d['composition_rights'] == 'verified' or d['redistribution_status'] == 'verified') and not d.get('evidence'):
                    raise ValueError("verified rights require evidence")
                _insert(db, 'datasets', (d['dataset_id'], d['name'], d['version'], d['source_url'],
                    d['dataset_license'], d['composition_rights'], d['redistribution_status'],
                    canonical_json(d.get('conditions', [])), canonical_json(d.get('evidence', []))))
            total_sources = total_phrases = 0
            for build in manifest['builds']:
                path = (manifest_path.parent / build['records']).resolve(strict=True)
                records_hash = file_digest(path)
                build_id = digest((build['dataset_id'], records_hash))
                _insert(db, 'builds', (build_id, build['dataset_id'], records_hash, 0))
                count = 0
                for r in _rows(path):
                    key = digest((build_id, r['source_id']))
                    _insert(db, 'sources', (key, build_id, r['source_id'], r['source_path'],
                        r.get('source_sha256'), r.get('musical_sha256'), r.get('artist_from_path'),
                        r.get('title_from_path'), r.get('identity_evidence','source_filename_unverified'), r['status'],
                        r.get('algorithm'), r.get('note_count'), r.get('part_count'),
                        len(r.get('warnings', [])), len(r.get('metadata_repairs', [])),
                        int(bool(r.get('search_limited'))), int(bool(r.get('curation_truncated'))),
                        r.get('split'), r.get('split_group'),canonical_json(r.get('upstream_metadata',{}))))
                    for p in r.get('phrases', []):
                        pitches = p.get('pitches', [])
                        velocities = p.get('velocities', [])
                        duration = _number(p.get('duration_beats'))
                        program = p.get('program')
                        if program is not None and (type(program) is not int or not 0 <= program <= 127):
                            raise ValueError('invalid MIDI program')
                        kind = p['kind']
                        if kind not in {'melodic', 'percussion'}:
                            raise ValueError('invalid phrase kind')
                        family = 'drums' if kind == 'percussion' else (FAMILIES[program // 8] if program is not None else None)
                        _insert(db, 'phrases', (digest((key,p['phrase_id'])), key, p['phrase_id'], kind,
                            p.get('family_id'), p.get('part_name'), program, family,
                            p.get('start_tick'), p.get('end_tick'), duration, p.get('note_count'),
                            p.get('occurrence_count'), _number(p.get('recurrence_score')),
                            min(pitches) if pitches else None, max(pitches) if pitches else None,
                            sum(velocities)/len(velocities) if velocities else None,
                            len(set(p.get('onsets_beats', [])))/duration if duration and duration > 0 else None,
                            canonical_json(p['meter']) if 'meter' in p else None,
                            canonical_json([{k:o[k] for k in ('start_tick','end_tick','transpose_semitones','edit_count','similarity','source_verified') if k in o} for o in p.get('occurrences', [])]), canonical_json(p.get('matcher_flags', {}))))
                        total_phrases += 1
                    for annotation in [*r.get('annotations', []), *build.get('annotations', {}).get(r['source_id'], [])]:
                        if not all(annotation.get(k) for k in ('category','value','evidence_url','method')):
                            raise ValueError('annotations require a category, value, evidence URL and method')
                        _insert(db,'annotations',(key,annotation['category'],annotation['value'],annotation['evidence_url'],annotation['method']))
                    count += 1
                    if count % 1000 == 0:
                        db.commit()
                if file_digest(path) != records_hash:
                    raise ValueError('input records changed during catalog import')
                db.execute('UPDATE builds SET imported_sources=? WHERE build_id=?',(count,build_id))
                total_sources += count
            db.commit()
            if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise ValueError('catalog integrity check failed')
        finally:
            db.close()
        # Publish only a completed database. Temporary files disappear on any failure.
        if output.exists():
            raise FileExistsError(output)
        # Same-filesystem link publishes atomically and refuses existing destinations.
        os.link(temp, output)
    return {'schema_version':SCHEMA_VERSION,'datasets':len(datasets),'sources':total_sources,
            'phrases':total_phrases,'bytes':output.stat().st_size,'sha256':file_digest(output)}
