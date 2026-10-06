"""Hash bound MIDI copyright evidence. Notices and score declarations are not work clearance."""
from __future__ import annotations
import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
from hashlib import sha256
import io
import gzip
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile

import mido
from .catalog_search import connect
from .dataset import atomic_json, file_digest
from .midi import _unwrap_midi_payload
from .metadata_recovery import recover_invalid_key_signatures

MAX_BYTES=8*1024*1024


def scan(task):
    key,rel,expected,root=task
    result=dict(source_key=key,scan_status='unavailable',copyright_notices=[],notice_truncated=False,
                observed_sha256=None,scan_error=None)
    try:
        base=Path(root).resolve(strict=True);path=(base/rel).resolve(strict=True)
        if not path.is_relative_to(base):raise ValueError('source path escapes corpus root')
        with path.open('rb') as stream:raw=stream.read(MAX_BYTES+1)
        if len(raw)>MAX_BYTES:
            result['scan_status']='size_limit';return result
        actual=sha256(raw).hexdigest();result['observed_sha256']=actual
        if not expected or actual!=expected:
            result['scan_status']='hash_mismatch';return result
        payload,_=_unwrap_midi_payload(raw)
        repaired=False
        try:midi=mido.MidiFile(file=io.BytesIO(payload))
        except mido.KeySignatureError:
            recovery=recover_invalid_key_signatures(payload)
            midi=mido.MidiFile(file=io.BytesIO(recovery.data));repaired=True
        notices=[]
        for track_index,track in enumerate(midi.tracks):
            tick=0
            for message in track:
                tick+=message.time
                if message.type=='copyright':
                    text=message.text
                    if len(notices)<64:
                        notices.append(dict(text=text[:8192],track=track_index,tick=tick))
                        if len(text)>8192:result['notice_truncated']=True
                    else:result['notice_truncated']=True
        result.update(scan_status='scanned_metadata_repaired' if repaired else 'scanned',copyright_notices=notices)
    except Exception as exc:
        result.update(scan_status='read_or_parse_error',scan_error=type(exc).__name__)
    return result


def prepare(metadata: Path,catalog: Path,output: Path,roots: dict,*,workers=4,progress: Path|None=None):
    if type(workers) is not int or not 1<=workers<=4:raise ValueError('worker count must be 1 to 4')
    if output.exists() or output.is_symlink():raise FileExistsError(output)
    output.parent.mkdir(parents=True,exist_ok=True)
    if shutil.disk_usage(output.parent).free<12*1024**3:raise ValueError('insufficient storage reserve')
    metadata_hash=file_digest(metadata);catalog_hash=file_digest(catalog)
    source=connect(catalog,timeout=60)
    catalog_rows=list(source.execute('SELECT s.source_key,s.source_path,s.source_sha256,b.dataset_id FROM sources s JOIN builds b USING(build_id) ORDER BY s.source_key'));source.close()
    if any(r['dataset_id'] not in roots for r in catalog_rows):raise ValueError('missing corpus root')
    tasks=[(r['source_key'],r['source_path'],r['source_sha256'],str(roots[r['dataset_id']])) for r in catalog_rows]
    with tempfile.TemporaryDirectory(prefix='samuged-rights-',dir=output.parent) as temp:
        target=Path(temp)/'rights.sqlite';shutil.copyfile(metadata,target);db=sqlite3.connect(target)
        db.execute('PRAGMA max_page_count=524288')
        db.execute('PRAGMA foreign_keys=ON')
        try:
            bound=db.execute('SELECT catalog_sha256 FROM provenance').fetchone()[0]
            if bound!=catalog_hash:raise ValueError('metadata belongs to another catalog')
            if db.execute('SELECT count(*) FROM records').fetchone()[0]!=len(tasks):raise ValueError('source coverage differs')
            db.executescript('''
            CREATE TABLE source_rights(source_key TEXT PRIMARY KEY REFERENCES records,
             musical_work_license TEXT,musical_work_license_status TEXT NOT NULL,
             musical_work_rights_holder TEXT,musical_work_evidence_url TEXT,
             copyright_notices_json TEXT NOT NULL,copyright_notice_status TEXT NOT NULL,
             copyright_notice_scope TEXT NOT NULL,notice_truncated INTEGER NOT NULL,
             scan_status TEXT NOT NULL,observed_sha256 TEXT,scan_error TEXT,reviewed_on TEXT NOT NULL);
            CREATE INDEX rights_scan ON source_rights(scan_status,copyright_notice_status);
            CREATE INDEX rights_work_license ON source_rights(musical_work_license_status,musical_work_license);
            CREATE VIRTUAL TABLE copyright_text USING fts5(source_key UNINDEXED,notice);
            ''')
            counts=Counter();with_notice=0;date=datetime.now(timezone.utc).date().isoformat()
            with ProcessPoolExecutor(max_workers=workers) as pool:
                for index,r in enumerate(pool.map(scan,tasks,chunksize=32),1):
                    key=r['source_key']
                    if not db.execute('SELECT 1 FROM records WHERE source_key=?',(key,)).fetchone():raise ValueError('unknown scanned source')
                    status='present_unverified' if r['copyright_notices'] else ('absent' if r['scan_status'].startswith('scanned') else 'unavailable')
                    values=(key,None,'unknown',None,None,json.dumps(r['copyright_notices'],ensure_ascii=False),status,
                            'MIDI file notice, composition or transcription scope not established',int(r['notice_truncated']),
                            r['scan_status'],r['observed_sha256'],r['scan_error'],date)
                    db.execute('INSERT INTO source_rights VALUES ('+','.join('?' for _ in values)+')',values)
                    for notice in r['copyright_notices']:db.execute('INSERT INTO copyright_text VALUES (?,?)',(key,notice['text']))
                    counts[r['scan_status']]+=1;with_notice+=bool(r['copyright_notices'])
                    if progress and index%1000==0:atomic_json(progress,dict(status='scanning',processed=index,total=len(tasks),scan_status=dict(counts)))
            db.commit()
            if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('rights index integrity failed')
            if file_digest(metadata)!=metadata_hash or file_digest(catalog)!=catalog_hash:raise ValueError('input changed during scan')
            # Verify coverage in both directions, not only row counts.
            if db.execute('SELECT count(*) FROM records r LEFT JOIN source_rights s USING(source_key) WHERE s.source_key IS NULL').fetchone()[0]:raise ValueError('missing rights records')
            db.close();os.link(target,output)
            receipt=dict(source_records=len(tasks),scan_status=dict(counts),sources_with_notices=with_notice,
                musical_work_license_unknown=len(tasks),metadata_input_sha256=metadata_hash,catalog_sha256=catalog_hash,
                output_sha256=file_digest(output),bytes=output.stat().st_size,published=False)
            if progress:atomic_json(progress,dict(status='completed',**receipt))
            return receipt
        finally:db.close()



def export_records(index: Path, output: Path, *, max_output_mb=256):
    """Portable gzip JSONL rights metadata with bounded storage and no MIDI payload."""
    if not 1<=max_output_mb<=1024:raise ValueError('invalid export budget')
    if output.exists() or output.is_symlink():raise FileExistsError(output)
    output.parent.mkdir(parents=True,exist_ok=True)
    if shutil.disk_usage(output.parent).free<(10240+max_output_mb)*1024**2:raise ValueError('insufficient storage reserve')
    before=file_digest(index);db=sqlite3.connect(index.resolve(strict=True).as_uri()+'?mode=ro',uri=True);db.row_factory=sqlite3.Row
    try:
        db.execute('PRAGMA query_only=ON');db.execute('PRAGMA trusted_schema=OFF')
        if db.execute('PRAGMA user_version').fetchone()[0]!=1:raise ValueError('unsupported metadata index')
        if db.execute('SELECT count(*) FROM records LEFT JOIN source_rights USING(source_key) WHERE source_rights.source_key IS NULL').fetchone()[0]:raise ValueError('incomplete rights coverage')
        has_usage=bool(db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='source_usage'").fetchone())
        if has_usage and db.execute('SELECT count(*) FROM records LEFT JOIN source_usage USING(source_key) WHERE source_usage.source_key IS NULL').fetchone()[0]:raise ValueError('incomplete usage coverage')
        with tempfile.TemporaryDirectory(prefix='samuged-rights-export-',dir=output.parent) as tmp:
            target=Path(tmp)/'rights.jsonl.gz';count=0
            with target.open('xb') as raw:
                with gzip.GzipFile(filename='',mode='wb',fileobj=raw,mtime=0) as zipped:
                    for record in db.execute('SELECT r.*,w.* FROM records r JOIN source_rights w USING(source_key) ORDER BY r.source_key'):
                        row=dict(record)
                        for original,field in [('genre_json','genre_raw'),('conditions_json','corpus_conditions'),('copyright_notices_json','copyright_notices')]:
                            row[field]=json.loads(row.pop(original))
                        row['external_metadata_candidates']=[dict(x) for x in db.execute('SELECT * FROM external_links WHERE source_key=?',(row['source_key'],))]
                        if has_usage:
                            usage=dict(db.execute('SELECT * FROM source_usage WHERE source_key=?',(row['source_key'],)).fetchone());usage.pop('source_key')
                            for original,field in [('usage_conditions_json','usage_conditions'),('usage_evidence_json','usage_evidence')]:usage[field]=json.loads(usage.pop(original))
                            row.update(usage)
                        zipped.write((json.dumps(row,ensure_ascii=False,allow_nan=False)+'\n').encode())
                        count+=1
                        if raw.tell()>max_output_mb*1024**2:raise ValueError('export storage budget reached')
            if target.stat().st_size>max_output_mb*1024**2:raise ValueError('export storage budget reached')
            if file_digest(index)!=before:raise ValueError('index changed during export')
            os.link(target,output)
            return dict(source_records=count,input_sha256=before,sha256=file_digest(output),bytes=output.stat().st_size,published=False)
    finally:db.close()

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for arg in ['metadata','catalog','output','roots','progress']:p.add_argument('--'+arg,type=Path,required=arg=='output')
    p.add_argument('--workers',type=int,default=4);p.add_argument('--export-index',type=Path);a=p.parse_args()
    if a.export_index:result=export_records(a.export_index,a.output)
    else:
        if not all((a.metadata,a.catalog,a.roots)):p.error('scan requires --metadata, --catalog and --roots')
        result=prepare(a.metadata,a.catalog,a.output,json.loads(a.roots.read_text()),workers=a.workers,progress=a.progress)
    print(json.dumps(result,indent=2))

if __name__=='__main__':main()
