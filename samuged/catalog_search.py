"""Read-only, bounded catalog filters and spreadsheet-safe result export."""
from __future__ import annotations
import csv
import io
import json
import math
import os
from pathlib import Path
import sqlite3
import tempfile
import time

from .catalog import FAMILIES, RIGHTS, SCHEMA_VERSION

SORTS={'repeats':'p.occurrence_count DESC,p.duration_beats,p.phrase_key',
       'duration':'p.duration_beats DESC,p.phrase_key',
       'density':'p.onset_density DESC,p.phrase_key',
       'score':'p.recurrence_score DESC,p.phrase_key',
       'title':'p.title COLLATE NOCASE,p.artist COLLATE NOCASE,p.phrase_key'}


def connect(path: Path, *, timeout=10):
    if not 0<timeout<=60:raise ValueError('query timeout must be between 0 and 60 seconds')
    path=path.resolve(strict=True)
    db=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)
    try:
        db.execute('PRAGMA query_only=ON')
        db.execute('PRAGMA trusted_schema=OFF')
        if db.execute('PRAGMA user_version').fetchone()[0]!=SCHEMA_VERSION:
            raise ValueError('unsupported catalog version')
        deadline=time.monotonic()+timeout
        db.set_progress_handler(lambda:int(time.monotonic()>deadline),10000)
        db.row_factory=sqlite3.Row
        return db
    except Exception:
        db.close();raise


def literal_like(value):
    return '%'+value.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%'


def search(path: Path, *, text=None, dataset=None, kind=None, instrument=None,
           category=None, value=None, min_repeats=2, min_beats=None, max_beats=None,
           rights=None, redistribution=None, no_warnings=False, no_search_limit=False,
           sort='repeats', limit=50, offset=0):
    if sort not in SORTS or type(limit) is not int or not 1<=limit<=500 or (type(offset) is not int or not 0<=offset<=100000):
        raise ValueError('invalid sort or result bounds')
    if kind not in {None,'melodic','percussion'} or instrument not in {None,'drums',*FAMILIES}:
        raise ValueError('invalid kind or instrument family')
    if rights not in {None,*RIGHTS} or redistribution not in {None,*RIGHTS}:
        raise ValueError('invalid rights evidence status')
    if bool(category)!=bool(value):raise ValueError('category and value must be supplied together')
    if type(min_repeats) is not int or min_repeats<1:raise ValueError('minimum repeats must be positive')
    for number in (min_beats,max_beats):
        if number is not None and (isinstance(number,bool) or not isinstance(number,(int,float)) or not math.isfinite(number) or number<0):
            raise ValueError('duration bounds must be finite and nonnegative')
    if min_beats is not None and max_beats is not None and min_beats>max_beats:
        raise ValueError('minimum duration exceeds maximum')
    for label in (text,dataset,category,value):
        if label is not None and (not isinstance(label,str) or len(label)>500):
            raise ValueError('filter text must not exceed 500 characters')
    clauses=['p.occurrence_count>=?'];params=[min_repeats]
    for column,arg in (('dataset_id',dataset),('kind',kind),('instrument_family',instrument),
                       ('composition_rights',rights),('redistribution_status',redistribution)):
        if arg is not None:clauses.append(f'p.{column}=?');params.append(arg)
    if text is not None:
        clauses.append("(p.title LIKE ? ESCAPE '\\' OR p.artist LIKE ? ESCAPE '\\')")
        params.extend([literal_like(text)]*2)
    if category:
        clauses.append('EXISTS(SELECT 1 FROM annotations a WHERE a.source_key=p.source_key AND a.category=? AND a.value=?)')
        params.extend([category,value])
    for op,number in (('>=',min_beats),('<=',max_beats)):
        if number is not None:clauses.append(f'p.duration_beats{op}?');params.append(number)
    if no_warnings:clauses.append('p.warning_count=0 AND p.repair_count=0')
    if no_search_limit:clauses.append('p.search_limited=0')
    sql='''SELECT p.phrase_key,p.phrase_id,s.source_id,s.source_path,p.dataset_id,p.artist,p.title,
        s.identity_evidence,p.kind,p.instrument_family,p.duration_beats,p.occurrence_count,p.recurrence_score,
        p.pitch_min,p.pitch_max,p.velocity_mean,p.onset_density,p.warning_count,p.repair_count,p.search_limited,
        p.curation_truncated,p.dataset_license,p.composition_rights,p.redistribution_status,p.split,p.metadata_json
        FROM phrase_catalog p JOIN sources s USING(source_key) WHERE '''+' AND '.join(clauses)
    sql+=' ORDER BY '+SORTS[sort]+' LIMIT ? OFFSET ?';params.extend([limit,offset])
    db=connect(path)
    try:
        rows=[]
        for record in db.execute(sql,params):
            row=dict(record);metadata=json.loads(row.pop('metadata_json'))
            row.update(score_license_declaration=metadata.get('license'),score_license_url=metadata.get('license_url'),
                composer=metadata.get('composer_name'),genre_raw=metadata.get('genres'))
            rows.append(row)
        return rows
    finally:db.close()


def info(path: Path, *, category=None):
    if category is not None and (not isinstance(category,str) or len(category)>500):raise ValueError('invalid category')
    db=connect(path)
    try:
        result={'schema_version':SCHEMA_VERSION,
            'source_records':db.execute('SELECT count(*) FROM sources').fetchone()[0],
            'phrase_records':db.execute('SELECT count(*) FROM phrases').fetchone()[0],
            'datasets':[dict(r) for r in db.execute('SELECT dataset_id,name,version,dataset_license,composition_rights,redistribution_status,conditions_json,evidence_json FROM datasets ORDER BY dataset_id')],
            'annotation_categories':[dict(r) for r in db.execute('SELECT category,count(*) AS labels FROM annotations GROUP BY category ORDER BY category')]}
        for dataset in result['datasets']:
            dataset['conditions']=json.loads(dataset.pop('conditions_json'))
            dataset['evidence']=json.loads(dataset.pop('evidence_json'))
        if category is not None:
            result['category_values']=[dict(r) for r in db.execute('SELECT value,count(DISTINCT source_key) AS source_records FROM annotations WHERE category=? GROUP BY value ORDER BY source_records DESC,value LIMIT 100',(category,))]
        return result
    finally:db.close()


def export(rows, output: Path, *, format='json'):
    if format not in {'json','csv'}:raise ValueError('unsupported export format')
    if output.exists() or output.is_symlink():raise FileExistsError(output)
    output.parent.mkdir(parents=True,exist_ok=True)
    if format=='json':payload=json.dumps(rows,ensure_ascii=False,indent=2,allow_nan=False)+'\n'
    else:
        stream=io.StringIO();writer=csv.DictWriter(stream,fieldnames=list(rows[0]) if rows else ['phrase_key'])
        writer.writeheader()
        for row in rows:
            # Escape spreadsheet formulas in exports. Original labels remain in the catalog and JSON.
            writer.writerow({k:"'"+v if isinstance(v,str) and (v.lstrip(' \t\r\n').startswith(('=','+','-','@')) or v.startswith(('\t','\r','\n'))) else v for k,v in row.items()})
        payload=stream.getvalue()
    with tempfile.TemporaryDirectory(prefix='samuged-export-',dir=output.parent) as temp:
        target=Path(temp)/'results';target.write_text(payload,encoding='utf-8')
        os.link(target,output)
