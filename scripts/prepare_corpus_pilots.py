"""Prepare deterministic MAESTRO and PDMX pilots from checksum-checked local assets."""
from __future__ import annotations
import argparse
import csv
import json
from pathlib import Path, PurePosixPath
from samuged.acquire import extract_archive
from samuged.dataset import canonical_json, digest


def present(value):
    return value if value not in ('','NA','NaN') else None


def prepare(root: Path, *, pdmx_count=16, maestro_count=8):
    if not 1 <= pdmx_count <= 10000 or not 1 <= maestro_count <= 1276:
        raise ValueError("pilot counts exceed bounded limits")
    # No network or publication. Asset checksums are recorded by the acquisition step.
    from samuged.dataset import file_digest
    receipt=json.loads((root/'acquisition.json').read_text())
    for name,entry in receipt.items():
        if file_digest(root/name)!=entry['sha256']:
            raise ValueError(f'asset checksum changed: {name}')
    candidates=[];counts={};eligible=0
    records=root/'pdmx_metadata.jsonl'
    if records.exists():raise FileExistsError(records)
    with (root/'pdmx.csv').open(newline='') as source,records.open('x') as output:
        for row in csv.DictReader(source):
            counts[row['license']]=counts.get(row['license'],0)+1
            if row['subset:no_license_conflict']!='True' or row['subset:all_valid']!='True':continue
            if row['license'] not in {'publicdomain','cc0'}:continue
            path=PurePosixPath(row['mid']).as_posix()
            record={'source_id':digest(('pdmx',path))[:24],'source_path':path,'status':'metadata_only',
                'artist_from_path':present(row['artist_name']),'title_from_path':present(row['song_name']) or present(row['title']),
                'identity_evidence':'upstream_score_metadata_unverified','phrases':[],
                'upstream_metadata':{k:present(row[k]) for k in ('composer_name','genres','groups','tags','license','license_url','n_notes','song_length.seconds','song_length.bars','complexity','best_path')}}
            output.write(canonical_json(record)+'\n');eligible+=1
            try:notes=int(row['n_notes']);seconds=float(row['song_length.seconds'])
            except (ValueError,TypeError):continue
            if 100<=notes<=1500 and 30<=seconds<=180 and row['subset:deduplicated']=='True':
                candidates.append((digest(path),path,record))
    selected=sorted(candidates)[:pdmx_count]
    extraction=extract_archive(root/'pdmx-midi.tar.gz',root/'pdmx_pilot',max_bytes=max(16*1024**2,pdmx_count*65536),max_files=pdmx_count,selected={p for _,p,_ in selected},suffixes=('.mid',))
    official=json.loads((root/'maestro/maestro-v3.0.0/maestro-v3.0.0.json').read_text())
    # Official metadata is stored column-first in MAESTRO v3.
    rows=[{k:v[index] for k,v in official.items()} for index in official['midi_filename']]
    chosen=sorted(rows,key=lambda r:(r['duration'],r['midi_filename']))[:maestro_count]
    pilot=root/'maestro_pilot';pilot.mkdir()
    import shutil
    for row in chosen:
        path=PurePosixPath(row['midi_filename'])
        source=(root/'maestro/maestro-v3.0.0'/path).resolve(strict=True)
        target=pilot/path
        if not source.is_relative_to((root/'maestro/maestro-v3.0.0').resolve()) or not target.resolve().is_relative_to(pilot.resolve()):
            raise ValueError('unsafe source metadata path')
        target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,target)
    selection={'pdmx':[r for _,_,r in selected],'maestro':chosen,'pdmx_eligible_metadata_rows':eligible,
        'pdmx_declared_license_counts':counts,'pdmx_extraction':extraction,
        'selection_policy':f'pdmx first {pdmx_count} in fixed SHA-256 order among valid conflict-free PD/CC0 deduplicated scores, 100-1500 notes and 30-180 seconds; maestro {maestro_count} shortest performances'}
    (root/'pilot_selection.json').write_text(json.dumps(selection,indent=2,ensure_ascii=False)+'\n')
    return {'pdmx_metadata_rows':eligible,'pdmx_pilot_files':len(selected),'maestro_pilot_files':len(chosen)}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--pdmx-count',type=int,default=16)
    parser.add_argument('--maestro-count',type=int,default=8)
    args=parser.parse_args()
    print(json.dumps(prepare(args.root,pdmx_count=args.pdmx_count,maestro_count=args.maestro_count),indent=2))
