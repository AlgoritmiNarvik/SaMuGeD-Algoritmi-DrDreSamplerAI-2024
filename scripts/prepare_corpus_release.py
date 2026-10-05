"""Prepare a local audited PDMX snapshot. Nothing is published."""
import argparse
import json
from pathlib import Path
from samuged.corpus_release import prepare

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--registry',type=Path,default=Path('docs/research/corpus/sources.json'))
    parser.add_argument('--allow-partial',action='store_true')
    parser.add_argument('--max-output-mb',type=int,default=8192)
    args=parser.parse_args()
    print(json.dumps(prepare(args.root,args.output,registry=args.registry,
        allow_partial=args.allow_partial,max_output_mb=args.max_output_mb),indent=2))
