"""Join official pilot identities and source event metadata without changing extraction artifacts."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from samuged.dataset import canonical_json
from samuged.midi import load_midi


def enrich(root: Path):
    selection=json.loads((root/'pilot_selection.json').read_text())
    pdmx={r['source_path']:r for r in selection['pdmx']}
    maestro={r['midi_filename']:r for r in selection['maestro']}
    counts={}
    for corpus in ('pdmx','maestro'):
        count=0
        target=root/f'{corpus}_enriched.jsonl'
        if target.exists():raise FileExistsError(target)
        temp=target.with_suffix('.jsonl.tmp')
        try:
            with (root/f'{corpus}_closed/sources.jsonl').open() as source,temp.open('x') as out:
                for line in source:
                    r=json.loads(line)
                    if corpus=='pdmx':
                        metadata=pdmx[r['source_path']]
                        for k in ('artist_from_path','title_from_path','identity_evidence','upstream_metadata'):r[k]=metadata[k]
                    else:
                        metadata=maestro[r['source_path']]
                        r.update(artist_from_path=None,title_from_path=metadata['canonical_title'],
                            identity_evidence='official_maestro_metadata',upstream_metadata=metadata)
                    source_root=(root/f'{corpus}_pilot').resolve()
                    source_path=(source_root/r['source_path']).resolve(strict=True)
                    if not source_path.is_relative_to(source_root):
                        raise ValueError('unsafe source record path')
                    song=load_midi(source_path,recover_invalid_keys=True)
                    r['upstream_metadata']={**r['upstream_metadata'],
                        'source_tempo_events':[{'tick':tick,'microseconds_per_quarter':tempo} for tick,tempo in song.tempos],
                        'source_meter_events':[{'tick':tick,'numerator':n,'denominator':d} for tick,n,d in song.meters],
                        'ticks_per_beat':song.ticks_per_beat,
                        'source_parts':[{'index':p.index,'name':p.name,'program':p.program,'is_drum':p.is_drum} for p in song.parts]}
                    out.write(canonical_json(r)+'\n');count+=1
            temp.rename(target)
        finally:
            temp.unlink(missing_ok=True)
        counts[corpus]=count
    return counts


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--root',type=Path,required=True)
    print(json.dumps(enrich(parser.parse_args().root),indent=2))
