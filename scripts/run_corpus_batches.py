"""Run a screened local PDMX corpus in bounded, resumable research batches.

Batch splits are extraction bookkeeping, not release or model evaluation splits.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import shutil
import time
from samuged.acquire import extract_archive
from samuged.aligned import AlignedConfig
from samuged.audit import audit
from samuged.dataset import atomic_json, build, canonical_json, digest, file_digest


def batches(rows, size):
    for start in range(0, len(rows), size):
        yield rows[start:start+size]


def run(root: Path, *, batch_size=250, workers=2, reserve_gib=10, percussion=False):
    if not 1 <= batch_size <= 1000 or not 1 <= workers <= 4 or reserve_gib < 10:
        raise ValueError('invalid bounded run settings')
    root=root.resolve(strict=True)
    receipt=json.loads((root/'acquisition.json').read_text())
    if file_digest(root/'pdmx-midi.tar.gz') != receipt['pdmx-midi.tar.gz']['sha256']:
        raise ValueError('source archive checksum changed')
    metadata=root/'pdmx_metadata.jsonl'
    rows=[]
    with metadata.open() as stream:
        for line in stream:
            row=json.loads(line)
            rows.append(row['source_path'])
    paths=sorted(set(rows))
    if not paths:
        raise ValueError('screened metadata contains no sources')
    output=root/'pdmx_full';output.mkdir(exist_ok=True)
    plan={'metadata_sha256':file_digest(metadata),'paths_sha256':digest(paths),
          'source_files':len(paths),'batch_size':batch_size,'workers':workers,
          'percussion':percussion,'algorithm':'aligned_closed',
          'split_status':'batch_local_only_not_for_model_evaluation'}
    plan_path=output/'plan.json'
    if plan_path.exists() and json.loads(plan_path.read_text()) != plan:
        raise ValueError('existing batch plan differs')
    atomic_json(plan_path,plan)
    reserve=reserve_gib*1024**3
    if shutil.disk_usage(root).free < reserve+2*1024**3:
        raise ValueError('insufficient reserve for full corpus extraction')
    corpus=root/'pdmx_full_input'
    if not corpus.exists():
        extraction=extract_archive(root/'pdmx-midi.tar.gz',corpus,
            max_bytes=1024**3,max_files=len(paths),selected=set(paths),suffixes=('.mid',))
        if extraction['files'] != len(paths):
            raise ValueError('screened archive membership count differs')
        atomic_json(output/'extraction.json',extraction)
    # Preserve source paths and official identities. Each batch has its own frozen provenance.
    completed=0;started=time.monotonic()
    for index, group in enumerate(batches(paths,batch_size)):
        if shutil.disk_usage(root).free < reserve+1024**3:
            raise ValueError('storage reserve reached, completed batches remain resumable')
        source=output/f'inputs/{index:06d}';source.mkdir(parents=True,exist_ok=True)
        for rel in group:
            src=(corpus/rel).resolve(strict=True);dst=source/rel
            if not src.is_relative_to(corpus.resolve()) or not dst.resolve().is_relative_to(source.resolve()):
                raise ValueError('unsafe source metadata path')
            dst.parent.mkdir(parents=True,exist_ok=True)
            if not dst.exists():os.link(src,dst)
        destination=output/f'builds/{index:06d}'
        summary=build(source,destination,AlignedConfig(top_k=3),workers=workers,
                      algorithm='aligned_closed',percussion=percussion)
        checked=audit(source,destination,require_full=True,reextract=True)
        if not checked['passed']:
            raise ValueError(f'batch {index} failed independent checking')
        completed+=summary['source_files']
        progress={'completed_sources':completed,'total_sources':len(paths),
                  'completed_batches':index+1,'elapsed_seconds':round(time.monotonic()-started,1),
                  'last_summary':str(destination/'summary.json'),'status':'running'}
        atomic_json(output/'progress.json',progress)
        print(canonical_json(progress),flush=True)
    progress['status']='extracted_and_batch_audited_pending_global_splits'
    atomic_json(output/'progress.json',progress)
    return progress


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--batch-size',type=int,default=250)
    parser.add_argument('--workers',type=int,default=2)
    parser.add_argument('--reserve-gib',type=int,default=10)
    parser.add_argument('--percussion',action='store_true')
    args=parser.parse_args()
    print(canonical_json(run(args.root,batch_size=args.batch_size,workers=args.workers,
                             reserve_gib=args.reserve_gib,percussion=args.percussion)))
