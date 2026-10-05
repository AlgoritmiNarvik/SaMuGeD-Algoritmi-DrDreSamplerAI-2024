"""Prepare audited PDMX metadata and MIDI snapshots without publishing a release."""
from __future__ import annotations

from collections import Counter
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile

from .catalog import _rows
from .dataset import _Union, atomic_json, canonical_json, file_digest
from .midi import load_midi


def audited_batches(root: Path, *, allow_partial=False):
    full=root/'pdmx_full'
    plan=json.loads((full/'plan.json').read_text())
    progress=json.loads((full/'progress.json').read_text())
    finished=progress['status']=='extracted_and_batch_audited_pending_global_splits'
    if not finished and not allow_partial:
        raise ValueError('full extraction is not finished; partial snapshots require an explicit option')
    selected=[];codes=set();keys=set()
    for batch in sorted((full/'builds').iterdir()):
        report=batch/'audit.json'
        if not report.exists():continue
        audit=json.loads(report.read_text())
        if not audit['passed']:raise ValueError('batch audit failed')
        if not audit.get('full_source_coverage_required') or not audit.get('reextraction_required'):
            raise ValueError('batch needs full independent replay')
        for name,field in (('sources.jsonl','source_manifest_sha256'),('phrases.jsonl','phrase_manifest_sha256'),
                           ('build_config.json','build_config_sha256'),('summary.json','summary_sha256')):
            if file_digest(batch/name)!=audit[field]:raise ValueError('batch artifact changed after audit')
        config=json.loads((batch/'build_config.json').read_text())
        codes.add(config['code_sha256']);keys.add(config['run_key'])
        selected.append((batch,audit,config))
    if not selected or len(codes)!=1 or len(keys)!=1:
        raise ValueError('snapshot requires audited batches from one detector configuration')
    count=sum(a['source_files'] for _,a,_ in selected)
    if finished and count!=plan['source_files']:
        raise ValueError('completed plan coverage differs from audited sources')
    return selected,plan,finished


def prepare(root: Path, output: Path, *, registry: Path, allow_partial=False,
            max_output_mb=8192, reserve_mb=10240):
    root=root.resolve(strict=True);output=output.resolve()
    if output.exists():raise FileExistsError(output)
    if max_output_mb<1 or reserve_mb<10240:raise ValueError('invalid snapshot storage budget')
    output.parent.mkdir(parents=True,exist_ok=True)
    if shutil.disk_usage(output.parent).free < (max_output_mb+reserve_mb+1024)*1024**2:
        raise ValueError('insufficient snapshot storage reserve')
    selected,plan,finished=audited_batches(root,allow_partial=allow_partial)
    metadata=root/'pdmx_metadata.jsonl'
    if file_digest(metadata)!=plan['metadata_sha256']:raise ValueError('screened metadata changed')
    dataset=next(d for d in json.loads(registry.read_text())['sources'] if d['dataset_id']=='pdmx')
    evidence=dataset['source_url'];limit=max_output_mb*1024**2
    with tempfile.TemporaryDirectory(prefix='samuged-release-',dir=output.parent) as temp:
        stage=Path(temp)/'snapshot';stage.mkdir()
        lookup=sqlite3.connect(Path(temp)/'metadata.sqlite')
        try:
            lookup.execute('PRAGMA max_page_count=262144')
            lookup.execute('CREATE TABLE metadata(path TEXT PRIMARY KEY,record TEXT NOT NULL)')
            for row in _rows(metadata):
                lookup.execute('INSERT INTO metadata VALUES (?,?)',(row['source_path'],canonical_json(row)))
            lookup.commit()
            # Group byte matches and normalized fingerprint candidates, never a shared folder.
            identities=[];links={};pairs=[]
            for batch,_,_ in selected:
                for r in _rows(batch/'sources.jsonl'):
                    identities.append(r['source_id'])
                    for key in (("bytes",r.get('source_sha256')),("notes",r.get('musical_sha256') if r.get('note_count') else None)):
                        if not key[1]:continue
                        if key in links:pairs.append((r['source_id'],links[key]))
                        else:links[key]=r['source_id']
            if len(set(identities))!=len(identities):raise ValueError('duplicate source identity across batches')
            groups=_Union(identities)
            for a,b in pairs:groups.join(a,b)
            counts=Counter();seen=0;size=0
            target=stage/'sources.jsonl'
            with target.open('x') as out:
                for batch,audit,config in selected:
                    for r in _rows(batch/'sources.jsonl'):
                        match=lookup.execute('SELECT record FROM metadata WHERE path=?',(r['source_path'],)).fetchone()
                        if match is None:raise ValueError('extracted source missing screened metadata')
                        official=json.loads(match[0])
                        original_split=r.get('split')
                        r.update(artist_from_path=official.get('artist_from_path'),
                                 title_from_path=official.get('title_from_path'),
                                 identity_evidence=official['identity_evidence'],split='unassigned',split_group=None)
                        upstream={**official['upstream_metadata'],
                            'extraction_split':original_split,'duplicate_group':groups.find(r['source_id']),
                            'duplicate_group_method':'byte_or_normalized_fingerprint_candidate',
                            'extraction_identity_keys':{k:r.pop(k,None) for k in ('artist_key','song_key')},
                            'extraction_provenance':{'batch':batch.name,'run_key':config['run_key'],
                                'code_sha256':config['code_sha256'],'source_manifest_sha256':audit['source_manifest_sha256'],
                                'audit_sha256':file_digest(batch/'audit.json')}}
                        source=(root/'pdmx_full_input'/r['source_path']).resolve(strict=True)
                        if not source.is_relative_to((root/'pdmx_full_input').resolve()):raise ValueError('unsafe source path')
                        if file_digest(source)!=r['source_sha256']:raise ValueError('source changed after audit')
                        if r['status']=='ok':
                            song=load_midi(source)
                            upstream.update(source_tempo_events=[{'tick':t,'microseconds_per_quarter':v} for t,v in song.tempos],
                                source_meter_events=[{'tick':t,'numerator':n,'denominator':d} for t,n,d in song.meters],
                                source_parts=[{'index':p.index,'name':p.name,'program':p.program,'is_drum':p.is_drum} for p in song.parts])
                        r['upstream_metadata']=upstream
                        annotations=[]
                        for category,key in (('composer','composer_name'),('genre_raw','genres'),('group_raw','groups'),
                                             ('tag_raw','tags'),('license_declaration','license')):
                            value=upstream.get(key)
                            if value:
                                annotations.append({'category':category,'value':str(value),
                                    'evidence_url':upstream.get('license_url') if key=='license' and upstream.get('license_url') else evidence,
                                    'method':'upstream_score_metadata_unverified'})
                        annotations.append({'category':'duplicate_group','value':groups.find(r['source_id']),
                            'evidence_url':evidence,'method':'byte_or_normalized_fingerprint_candidate'})
                        r['annotations']=annotations
                        # Keep compact coordinates. Detailed alignments remain bound to the original audited batch.
                        r.pop('selection_trace',None)
                        for p in r.get('phrases',[]):
                            p['occurrences']=[{k:v for k,v in o.items() if k!='matched_note_pairs'} for o in p.get('occurrences',[])]
                            if p.get('midi_path'):
                                rel=Path(p['midi_path'])
                                if rel.is_absolute() or '..' in rel.parts:raise ValueError('unsafe MIDI artifact path')
                                midi=(batch/rel).resolve(strict=True)
                                if not midi.is_relative_to(batch.resolve()):raise ValueError('unsafe MIDI artifact path')
                                if file_digest(midi)!=p['midi_sha256']:raise ValueError('MIDI artifact changed after audit')
                                dest=stage/p['midi_path'];dest.parent.mkdir(parents=True,exist_ok=True)
                                os.link(midi,dest);size+=midi.stat().st_size
                            counts[p['kind']]+=1
                        line=canonical_json(r)+'\n';size+=len(line.encode())
                        if size>limit:raise ValueError('snapshot exceeds storage budget')
                        out.write(line);seen+=1
                        if seen%1000==0 and shutil.disk_usage(stage).free<reserve_mb*1024**2:
                            raise ValueError('snapshot storage reserve reached')
            for batch,audit,_ in selected:
                if file_digest(batch/'sources.jsonl')!=audit['source_manifest_sha256']:
                    raise ValueError('batch source manifest changed during preparation')
            if seen!=sum(a['source_files'] for _,a,_ in selected):raise ValueError('snapshot source coverage differs')
            if file_digest(metadata)!=plan['metadata_sha256']:raise ValueError('screened metadata changed during preparation')
            manifest={'schema_version':1,'datasets':[dataset],'builds':[{'dataset_id':'pdmx','records':'sources.jsonl'}]}
            atomic_json(stage/'catalog_manifest.json',manifest)
            receipt={'schema_version':1,'status':'metadata_prepared_pending_release_review',
                'complete_extraction':finished,'source_files':seen,'planned_source_files':plan['source_files'],
                'phrase_counts':dict(counts),'duplicate_groups':len({groups.find(x) for x in identities}),
                'deduplicated':False,'duplicate_group_status':'candidates_not_verified_song_identity',
                'split_status':'unassigned_pending_global_policy','records_sha256':file_digest(target),
                'source_metadata_sha256':plan['metadata_sha256'],'midi_included':True,'logical_bytes':size}
            atomic_json(stage/'receipt.json',receipt)
            stage.rename(output)
        finally:lookup.close()
    return receipt
