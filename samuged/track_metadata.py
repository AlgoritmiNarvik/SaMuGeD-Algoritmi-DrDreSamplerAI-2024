"""Audit every source label and retain evidence for additional work search hints."""
from __future__ import annotations
import argparse
from contextlib import closing
import csv
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import uuid

from .dataset import file_digest
from .source_usage import source_path
from .work_identity import now, open_db, label

FIELDS = ('title', 'song_name', 'artist_name', 'composer_name', 'genres', 'license',
          'license_url', 'license_conflict', 'metadata', 'is_original', 'is_official')
EMPTY = {'', 'na', 'n/a', 'none', 'null', 'nan', 'unknown', 'not specified'}


def clean(value):
    if value is None or str(value).strip().casefold() in EMPTY:
        return None
    return str(value).strip()[:2000]


def creator_kind(value):
    value = clean(value)
    if not value:
        return 'missing'
    normalized = label(value)
    if re.search(r'\b(traditional|trad|anonymous|anon|unbekannt|unknown|folk)\b', normalized):
        return 'unattributed'
    # Unknown author markers, also when concatenated with following text ('Urheber unbekanntDatum').
    if value.strip() in {'?', '??', '-'} or re.search(
            r'unbekannt|unknown|inconnu|desconocido|sconosciuto|\banon|\b(ukjent|okand|n n)\b', normalized):
        return 'unattributed'
    if normalized.startswith(('misc ', 'various ', 'arr ', 'arranged ', 'after ')) or normalized in {'misc', 'various'}:
        return 'generic_or_ambiguous'
    if re.search(r'\b(https?|www)\b', normalized) or encoding_suspect(value):
        return 'suspect'
    return 'named_claim'


def encoding_suspect(value):
    return bool(value and ('\ufffd' in value or len(re.findall(r'[ÃÂØÙ]', value)) >= 3))


def describe(record, score=None):
    """Never promote an artist, filename or publisher to a verified composer."""
    title = clean(record['title']); composer = clean(record['composer']); artist = clean(record['artist'])
    source = dict(title=title, composer=composer, artist=artist)
    alternatives = {}
    if score is not None:
        alternatives = {k: clean(score.get(k)) for k in FIELDS}
    search_title = title
    title_basis = 'catalog_title'
    if alternatives.get('song_name') and not encoding_suspect(alternatives['song_name']):
        search_title = alternatives['song_name']; title_basis = 'upstream_song_name'
    title_status = 'missing' if not search_title else ('suspect_encoding' if encoding_suspect(search_title) else 'usable')
    if search_title and re.fullmatch(r'\[?ID[\s\d\-a-z]+\]?', search_title, re.I):
        title_status = 'identifier_only'
    kind = 'recording' if record['dataset_id'] == 'lakh' else 'work'
    primary = artist if kind == 'recording' else composer
    creator = primary if creator_kind(primary) == 'named_claim' else None
    basis = 'catalog_artist' if kind == 'recording' else 'catalog_composer'
    if not creator and creator_kind(alternatives.get('artist_name')) == 'named_claim':
        creator = alternatives['artist_name']; basis = 'upstream_artist_role_unverified'
    gaps = ['composition_rights_unverified', 'arrangement_rights_unverified', 'performance_rights_unverified']
    if title_status != 'usable':gaps.append('title_'+title_status)
    if not creator:gaps.append('creator_unresolved')
    elif basis == 'upstream_artist_role_unverified':gaps.append('creator_role_unverified')
    return dict(original=source, upstream=alternatives, search_title=search_title,
        title_basis=title_basis, title_status=title_status, search_creator=creator,
        creator_basis=basis if creator else 'unresolved', creator_status=creator_kind(primary),
        query_kind=kind, gaps=gaps, identity_status='unresolved', clearance_status='not_established')


def prepare(metadata: Path, catalog: Path, pdmx_csv: Path, work_index: Path, output: Path):
    if output.exists() or output.is_symlink():raise FileExistsError(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(output.parent).free < 12*1024**3:raise ValueError('10 GiB storage reserve required')
    inputs={str(p):file_digest(p) for p in (metadata,catalog,pdmx_csv,work_index)}
    target=output.with_name(output.name+'.'+str(uuid.uuid4())+'.tmp')
    try:
        with closing(open_db(work_index)) as source, closing(open_db(target,create=True)) as db:
            if source.execute('SELECT metadata_sha256 FROM provenance').fetchone()[0] != inputs[str(metadata)]:
                raise ValueError('metadata binding mismatch')
            source.backup(db)
            db.execute('ATTACH DATABASE ? AS metadata',(metadata.resolve().as_uri()+'?mode=ro',))
            db.execute('ATTACH DATABASE ? AS catalog',(catalog.resolve().as_uri()+'?mode=ro',))
            if db.execute('SELECT catalog_sha256 FROM metadata.provenance').fetchone()[0] != inputs[str(catalog)]:
                raise ValueError('catalog binding mismatch')
            db.executescript('''CREATE TABLE track_metadata(source_key TEXT PRIMARY KEY REFERENCES queue,
                title_status TEXT,creator_status TEXT,creator_basis TEXT,gaps_json TEXT,evidence_json TEXT);
                CREATE INDEX track_gaps ON track_metadata(title_status,creator_basis);
                CREATE TABLE label_provenance(input_hashes_json TEXT,policy TEXT,created_on TEXT);''')
            paths={source_path(r[0]):r[1] for r in db.execute("SELECT s.source_path,s.source_key FROM catalog.sources s JOIN catalog.builds b USING(build_id) WHERE b.dataset_id='pdmx'")}
            if len(paths)!=db.execute("SELECT count(*) FROM catalog.sources s JOIN catalog.builds b USING(build_id) WHERE b.dataset_id='pdmx'").fetchone()[0]:raise ValueError('duplicate catalog MIDI paths')
            scores={}
            with pdmx_csv.open(encoding='utf-8',newline='') as stream:
                reader=csv.DictReader(stream)
                if not {'mid',*FIELDS}.issubset(reader.fieldnames or []):raise ValueError('missing CSV fields')
                for row in reader:
                    path=source_path(row['mid']) if clean(row['mid']) else None
                    if path not in paths:continue
                    key=paths[path]
                    if key in scores:raise ValueError('duplicate full MIDI path')
                    scores[key]={k:row[k] for k in FIELDS}
            if len(scores)!=len(paths):raise ValueError('incomplete PDMX full path join')
            changed=0
            for record in db.execute('SELECT * FROM metadata.records ORDER BY source_key'):
                key=record['source_key']; old=db.execute('SELECT * FROM queue WHERE source_key=?',(key,)).fetchone()
                if old is None or old['source_sha256']!=record['source_sha256']:raise ValueError('source binding mismatch')
                evidence=describe(record,scores.get(key))
                evidence.update(source_sha256=record['source_sha256'],metadata_sha256=inputs[str(metadata)],
                    pdmx_csv_sha256=inputs[str(pdmx_csv)] if key in scores else None,
                    join_method='exact_full_MIDI_archive_path' if key in scores else 'source_key_and_hash',
                    upstream_fields_verified=False)
                eligible=evidence['title_status']=='usable' and bool(evidence['search_creator'])
                title=evidence['search_title']; creator=evidence['search_creator']
                if old['title']!=title or old['creator']!=creator or not eligible and old['status']!='missing_labels':
                    if db.execute('SELECT 1 FROM reviews WHERE source_key=? UNION ALL SELECT 1 FROM rights_observations WHERE source_key=?',(key,key)).fetchone():
                        raise ValueError('reviewed identity needs explicit label reconciliation')
                    db.execute('DELETE FROM work_candidates WHERE source_key=?',(key,))
                    db.execute('UPDATE queue SET title=?,creator=?,status=?,error=NULL,updated_on=? WHERE source_key=?',
                        (title,creator,'pending' if eligible else 'missing_labels',now(),key));changed+=1
                db.execute('INSERT INTO track_metadata VALUES (?,?,?,?,?,?)',
                    (key,evidence['title_status'],evidence['creator_status'],evidence['creator_basis'],
                     json.dumps(evidence['gaps']),json.dumps(evidence,ensure_ascii=False)))
            db.execute('INSERT INTO label_provenance VALUES (?,?,?)',(json.dumps(inputs),'source-label-audit-v1',now()))
            if any(file_digest(Path(p))!=sha for p,sha in inputs.items()):raise ValueError('input changed')
            db.commit()
            if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok' or db.execute('PRAGMA foreign_key_check').fetchall():raise ValueError('index validation failed')
            receipt=dict(source_records=db.execute('SELECT count(*) FROM track_metadata').fetchone()[0],
                pdmx_full_path_matches=len(scores),changed_search_labels=changed,
                title_status=dict(db.execute('SELECT title_status,count(*) FROM track_metadata GROUP BY title_status')),
                creator_basis=dict(db.execute('SELECT creator_basis,count(*) FROM track_metadata GROUP BY creator_basis')),
                queue_status=dict(db.execute('SELECT status,count(*) FROM queue GROUP BY status')),
                inputs=inputs,policy='source-label-audit-v1',published=False)
        os.link(target,output)
    finally:target.unlink(missing_ok=True)
    receipt.update(output_sha256=file_digest(output),bytes=output.stat().st_size)
    return receipt



def duplicate_hints(work_index: Path, output: Path):
    """Use equal MIDI bytes as metadata hints only. Never transfer permissions."""
    if output.exists() or output.is_symlink():raise FileExistsError(output)
    if shutil.disk_usage(output.parent).free < 12*1024**3:raise ValueError('10 GiB storage reserve required')
    before=file_digest(work_index);target=output.with_name(output.name+'.'+str(uuid.uuid4())+'.tmp')
    counts={'creator_hints':0,'conflicting_hint_records':0,'new_searchable_sources':0}
    try:
        with closing(open_db(work_index)) as source,closing(open_db(target,create=True)) as db:
            source.backup(db)
            rows=db.execute('SELECT source_key,source_sha256,creator FROM queue').fetchall()
            donors={}
            for row in rows:
                if not row['source_sha256'] or not row['creator']:continue
                names=donors.setdefault(row['source_sha256'],{})
                names.setdefault(' '.join(sorted(label(row['creator']).split())),[]).append(dict(row))
            for row in rows:
                if row['creator'] or not row['source_sha256']:continue
                names=donors.get(row['source_sha256'],{})
                if not names:continue
                key=row['source_key']
                if db.execute('SELECT 1 FROM reviews WHERE source_key=? UNION ALL SELECT 1 FROM rights_observations WHERE source_key=?',(key,key)).fetchone():
                    raise ValueError('reviewed identity needs explicit duplicate reconciliation')
                stored=db.execute('SELECT evidence_json FROM track_metadata WHERE source_key=?',(key,)).fetchone()
                evidence=json.loads(stored[0]);gaps=evidence['gaps']
                candidates=[item for group in names.values() for item in group]
                evidence['duplicate_metadata_hints']=dict(method='equal_source_MIDI_bytes_not_verified_work_identity',
                    donor_count=len(candidates),donors=candidates[:20],truncated=len(candidates)>20,
                    work_index_input_sha256=before)
                if len(names)>1:
                    gaps.append('conflicting_duplicate_metadata');counts['conflicting_hint_records']+=1
                else:
                    creator=candidates[0]['creator'];evidence['search_creator']=creator
                    evidence['creator_basis']='equal_MIDI_bytes_creator_hint'
                    gaps[:]=[g for g in gaps if g!='creator_unresolved']
                    gaps.append('duplicate_creator_hint_unverified');counts['creator_hints']+=1
                    eligible=evidence['title_status']=='usable'
                    db.execute('UPDATE queue SET creator=?,status=?,updated_on=? WHERE source_key=?',
                        (creator,'pending' if eligible else 'missing_labels',now(),key))
                    counts['new_searchable_sources']+=int(eligible)
                db.execute('UPDATE track_metadata SET creator_basis=?,gaps_json=?,evidence_json=? WHERE source_key=?',
                    (evidence['creator_basis'],json.dumps(gaps),json.dumps(evidence,ensure_ascii=False),key))
            db.execute('INSERT INTO label_provenance VALUES (?,?,?)',
                (json.dumps({str(work_index):before}),'equal-byte-metadata-hints-v1',now()))
            if file_digest(work_index)!=before:raise ValueError('input changed')
            db.commit()
            if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('integrity failed')
        os.link(target,output)
    finally:target.unlink(missing_ok=True)
    return dict(counts,input_sha256=before,output_sha256=file_digest(output),bytes=output.stat().st_size,published=False)

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for field in ('metadata','catalog','pdmx-csv','work-index','output'):parser.add_argument('--'+field,type=Path,required=True)
    args=parser.parse_args()
    print(json.dumps(prepare(args.metadata,args.catalog,args.pdmx_csv,args.work_index,args.output),indent=2))
