"""Local search packets for unresolved sources, without identity promotion."""
from __future__ import annotations
import argparse
from contextlib import closing
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import time

from .dataset import file_digest
from .work_identity import label

POLICY = 'source-search-recovery-v1'


def prepare(packets: Path, work_index: Path, output: Path):
    """Build a small independent index. The validated work index remains read only."""
    if output.exists() or output.is_symlink():
        raise FileExistsError(output)
    if not output.parent.is_dir():
        raise ValueError('output directory must exist')
    if shutil.disk_usage(output.parent).free < 10.75 * 1024**3:
        raise ValueError('10 GiB storage reserve required')
    inputs = {str(p): file_digest(p) for p in (packets, work_index)}
    with tempfile.TemporaryDirectory(dir=output.parent) as temp:
        target = Path(temp)/'search.sqlite'
        with closing(sqlite3.connect(work_index.resolve().as_uri()+'?mode=ro', uri=True)) as source, closing(sqlite3.connect(target)) as db:
            expected = dict(source.execute('SELECT source_key,source_sha256 FROM queue'))
            db.execute('PRAGMA max_page_count=131072')
            db.executescript('''
                CREATE TABLE packets(source_key TEXT PRIMARY KEY,source_sha256 TEXT,
                    query_group TEXT,title TEXT,creator TEXT,source_path TEXT,route TEXT,evidence_json TEXT);
                CREATE INDEX packet_group ON packets(query_group);
                CREATE TABLE provenance(policy TEXT,inputs_json TEXT);
                CREATE VIRTUAL TABLE search USING fts5(source_key UNINDEXED,title,creator,source_path);
            ''')
            seen = set()
            with gzip.open(packets, 'rt', encoding='utf-8') as stream:
                while line := stream.readline(65537):
                    if len(line) > 65536:
                        raise ValueError('packet exceeds 64 KiB')
                    record = json.loads(line)
                    key, digest = record['source_key'], record['source_sha256']
                    if key in seen or key not in expected or expected[key] != digest:
                        raise ValueError('source binding mismatch')
                    if record.get('identity_verified') is not False or record.get('rights_clearance') != 'not_established':
                        raise ValueError('search packet must not establish identity or rights')
                    seen.add(key)
                    title, creator = label(record.get('title')), label(record.get('creator_search_hint'))
                    route = record['search_route']
                    if route not in {'title_and_creator_candidate_search', 'title_and_source_identifier_review', 'source_identifier_or_musical_review'}:
                        raise ValueError('invalid search route')
                    # Shared queries never establish a shared musical work.
                    group = hashlib.sha256(json.dumps([record['dataset_id'], route, title, creator], ensure_ascii=False).encode()).hexdigest() if title else 'source:'+key
                    evidence = dict(record, policy=POLICY, query_group_role='request_cache_only_not_verified_work',
                        title_only_candidate_requires_review=True)
                    db.execute('INSERT INTO packets VALUES (?,?,?,?,?,?,?,?)',
                        (key,digest,group,title,creator,record['original_source_path'],route,json.dumps(evidence,ensure_ascii=False)))
                    db.execute('INSERT INTO search VALUES (?,?,?,?)',(key,title,creator,record['original_source_path']))
            if seen != set(expected):
                raise ValueError('incomplete source coverage')
            if any(file_digest(Path(p)) != digest for p,digest in inputs.items()):
                raise ValueError('input changed')
            db.execute('INSERT INTO provenance VALUES (?,?)',(POLICY,json.dumps(inputs)))
            db.commit()
            result = dict(policy=POLICY,sources=len(seen),query_groups=db.execute('SELECT count(DISTINCT query_group) FROM packets').fetchone()[0],
                routes=dict(db.execute('SELECT route,count(*) FROM packets GROUP BY route')),published=False,
                identity_verified=False,rights_clearance='not_established')
        target.replace(output)
    result.update(output_sha256=file_digest(output),output_bytes=output.stat().st_size)
    return result


def search(path: Path, text: str, *, limit=20):
    if not isinstance(text,str) or not text.strip() or len(text)>250 or type(limit) is not int or not 1<=limit<=100:
        raise ValueError('invalid search bounds')
    terms = label(text).split()
    if not terms:
        return []
    # Quote each token so search punctuation cannot become FTS operators.
    query = ' AND '.join('"'+term.replace('"','""')+'"' for term in terms)
    with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)) as db:
        deadline = time.monotonic()+10
        db.set_progress_handler(lambda: int(time.monotonic()>deadline),10000)
        rows = db.execute('SELECT p.evidence_json FROM search s JOIN packets p USING(source_key) WHERE search MATCH ? ORDER BY p.source_key LIMIT ?', (query,limit))
        return [json.loads(row[0]) for row in rows]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    commands=parser.add_subparsers(dest='command',required=True)
    build=commands.add_parser('prepare')
    for name in ('packets','work-index','output'):build.add_argument('--'+name,type=Path,required=True)
    find=commands.add_parser('search');find.add_argument('--index',type=Path,required=True);find.add_argument('--text',required=True);find.add_argument('--limit',type=int,default=20)
    args=parser.parse_args()
    result=prepare(args.packets,args.work_index,args.output) if args.command=='prepare' else search(args.index,args.text,limit=args.limit)
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
