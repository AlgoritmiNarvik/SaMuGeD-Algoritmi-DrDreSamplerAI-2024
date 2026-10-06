"""Derived source search, rights evidence and candidate grouping without changing extraction."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import tempfile
import time
import unicodedata

from .catalog_search import connect, export
from .dataset import file_digest


def normalized(value):
    return ' '.join(unicodedata.normalize('NFKC', value or '').casefold().split())


def prepare(catalog: Path, output: Path, *, reserve_mb=10240, max_output_mb=1024):
    if reserve_mb < 10240 or not 1 <= max_output_mb <= 2048:
        raise ValueError('invalid storage budget')
    if output.exists() or output.is_symlink():raise FileExistsError(output)
    output.parent.mkdir(parents=True,exist_ok=True)
    if shutil.disk_usage(output.parent).free < (reserve_mb+2*max_output_mb)*1024**2:
        raise ValueError('insufficient storage reserve')
    before=file_digest(catalog)
    source=connect(catalog,timeout=60)
    with tempfile.TemporaryDirectory(prefix='samuged-metadata-',dir=output.parent) as tmp:
        target=Path(tmp)/'metadata.sqlite';db=sqlite3.connect(target)
        try:
            db.execute(f'PRAGMA max_page_count={max_output_mb*256}')
            db.executescript('''
            CREATE TABLE provenance(catalog_sha256 TEXT,reviewed_on TEXT,grouping_policy TEXT);
            CREATE TABLE records(source_key TEXT PRIMARY KEY,dataset_id TEXT,artist TEXT,title TEXT,
             composer TEXT,genre_json TEXT,dataset_license TEXT,score_license_declaration TEXT,
             score_license_url TEXT,composition_rights TEXT,redistribution_status TEXT,
             evidence_url TEXT,conditions_json TEXT,identity_evidence TEXT,status TEXT,
             source_sha256 TEXT,musical_sha256 TEXT,candidate_group TEXT,
             evaluation_split TEXT,warning_count INTEGER,search_limited INTEGER);
            CREATE VIRTUAL TABLE search_text USING fts5(source_key UNINDEXED,artist,title,composer,genres);
            CREATE INDEX metadata_license ON records(dataset_id,score_license_declaration);
            CREATE INDEX metadata_composer ON records(composer);
            CREATE INDEX metadata_groups ON records(candidate_group);
            CREATE TABLE external_links(source_key TEXT,provider TEXT,entity_id TEXT,title TEXT,artist TEXT,
             evidence_url TEXT,metadata_license TEXT,match_status TEXT,method TEXT,retrieved_on TEXT,
             PRIMARY KEY(source_key,provider,entity_id));
            CREATE INDEX external_entity ON external_links(provider,entity_id);
            ''')
            parents={};fingerprints={};count=0
            def find(key):
                while parents[key]!=key:
                    parents[key]=parents[parents[key]];key=parents[key]
                return key
            query='''SELECT s.*,d.dataset_id,d.dataset_license,d.composition_rights,d.redistribution_status,
                d.source_url,d.conditions_json FROM sources s JOIN builds b USING(build_id)
                JOIN datasets d USING(dataset_id) ORDER BY s.source_key'''
            for row in source.execute(query):
                meta=json.loads(row['metadata_json']);key=row['source_key'];parents[key]=key
                # Matching complete files/arrangements only. No identity or rights inference.
                for kind in ('source_sha256','musical_sha256'):
                    h=row[kind]
                    if not h or (kind=='musical_sha256' and not row['note_count']):continue
                    previous=fingerprints.get((kind,h))
                    if previous is not None:
                        a,b=find(key),find(previous);parents[max(a,b)]=min(a,b)
                    else:fingerprints[kind,h]=key
                genre=meta.get('genres');composer=meta.get('composer_name')
                values=(key,row['dataset_id'],row['artist'],row['title'],composer,json.dumps(genre,ensure_ascii=False),
                    row['dataset_license'],meta.get('license'),meta.get('license_url'),row['composition_rights'],
                    row['redistribution_status'],row['source_url'],row['conditions_json'],row['identity_evidence'],
                    row['status'],row['source_sha256'],row['musical_sha256'],None,'unassigned',
                    row['warning_count'],row['search_limited'])
                db.execute('INSERT INTO records VALUES ('+','.join('?' for _ in values)+')',values)
                db.execute('INSERT INTO search_text VALUES (?,?,?,?,?)',
                    tuple(v.replace('_',' ') for v in (key,row['artist'] or '',row['title'] or '',composer or '',json.dumps(genre,ensure_ascii=False))))
                count+=1
            for key in parents:db.execute('UPDATE records SET candidate_group=? WHERE source_key=?',(find(key),key))
            policy='global byte or normalized arrangement candidate union, not verified composition identity; evaluation splits unassigned'
            db.execute('INSERT INTO provenance VALUES (?,?,?)',(before,datetime.now(timezone.utc).date().isoformat(),policy))
            db.execute('PRAGMA user_version=1');db.commit()
            if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('metadata integrity failed')
            groups=db.execute('SELECT count(DISTINCT candidate_group) FROM records').fetchone()[0]
            if file_digest(catalog)!=before:raise ValueError('input catalog changed')
            db.close();os.link(target,output)
            return dict(source_records=count,candidate_groups=groups,catalog_sha256=before,
                        metadata_sha256=file_digest(output),bytes=output.stat().st_size,
                        evaluation_split='unassigned',published=False)
        finally:
            db.close();source.close()


def search(path: Path, *, text=None, dataset=None, composer=None, score_license=None, limit=50):
    if type(limit) is not int or not 1<=limit<=500:raise ValueError('invalid result limit')
    for v in (text,dataset,composer,score_license):
        if v is not None and (not isinstance(v,str) or not 1<=len(v)<=500):raise ValueError('invalid filter text')
    db=sqlite3.connect(path.resolve(strict=True).as_uri()+'?mode=ro',uri=True);db.row_factory=sqlite3.Row
    try:
        db.execute('PRAGMA query_only=ON');db.execute('PRAGMA trusted_schema=OFF')
        if db.execute('PRAGMA user_version').fetchone()[0]!=1:raise ValueError('unsupported metadata index')
        deadline=time.monotonic()+10
        db.set_progress_handler(lambda:int(time.monotonic()>deadline),10000)
        clauses=[];params=[]
        if text:
            tokens=re.findall(r'\w+',text.replace('_',' '),flags=re.UNICODE)
            if not tokens:return []
            query=' AND '.join('"'+t.replace('"','""')+'"' for t in tokens)
            clauses.append('r.source_key IN (SELECT source_key FROM search_text WHERE search_text MATCH ?)');params.append(query)
        for field,v in [('dataset_id',dataset),('composer',composer),('score_license_declaration',score_license)]:
            if v is not None:clauses.append(f'r.{field}=?');params.append(v)
        sql='SELECT r.* FROM records r'+(' WHERE '+' AND '.join(clauses) if clauses else '')+' ORDER BY r.source_key LIMIT ?'
        return [dict(r) for r in db.execute(sql,params+[limit])]
    finally:db.close()


def import_links(path: Path, rows: list[dict]):
    """Import bounded external candidate evidence. Never overwrite identity or rights."""
    if not isinstance(rows,list) or len(rows)>1000:raise ValueError('link import must contain at most 1000 records')
    db=sqlite3.connect(path.resolve(strict=True))
    try:
        if db.execute('PRAGMA user_version').fetchone()[0]!=1:raise ValueError('unsupported metadata index')
        for r in rows:
            if not db.execute('SELECT 1 FROM records WHERE source_key=?',(r['source_key'],)).fetchone():raise ValueError('unknown source')
            if r['provider']!='musicbrainz' or r['metadata_license']!='CC0-1.0' or r['match_status']!='candidate':
                raise ValueError('only MusicBrainz core metadata candidates are supported')
            if not re.fullmatch(r'[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}',r['entity_id']):raise ValueError('invalid entity ID')
            if r['evidence_url']!='https://musicbrainz.org/recording/'+r['entity_id']:raise ValueError('invalid evidence URL')
            vals=tuple(r[k] for k in ['source_key','provider','entity_id','title','artist','evidence_url','metadata_license','match_status','method','retrieved_on'])
            if any(not isinstance(v,str) or len(v)>2000 for v in vals):raise ValueError('invalid link values')
            db.execute('INSERT OR IGNORE INTO external_links VALUES (?,?,?,?,?,?,?,?,?,?)',vals)
        db.commit()
    except Exception:db.rollback();raise
    finally:db.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='command',required=True)
    b=sub.add_parser('prepare');b.add_argument('--catalog',type=Path,required=True);b.add_argument('--output',type=Path,required=True)
    s=sub.add_parser('search');s.add_argument('--metadata',type=Path,required=True)
    for flag in ['text','dataset','composer','score-license']:s.add_argument('--'+flag)
    s.add_argument('--limit',type=int,default=50);s.add_argument('--output',type=Path)
    a=parser.parse_args()
    if a.command=='prepare':result=prepare(a.catalog,a.output)
    else:
        result=search(a.metadata,text=a.text,dataset=a.dataset,composer=a.composer,score_license=a.score_license,limit=a.limit)
        if a.output:export(result,a.output)
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
