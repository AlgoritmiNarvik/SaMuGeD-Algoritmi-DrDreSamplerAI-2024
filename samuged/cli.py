"""Command line entry point for local, reproducible MIDI phrase research."""
import argparse
import json
from pathlib import Path

from .dataset import build
from .phrases import Config


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    command = sub.add_parser("build", help="extract a local MIDI corpus; resume matching runs")
    command.add_argument("--source", type=Path, required=True)
    command.add_argument("--output", type=Path, required=True)
    command.add_argument("--workers", type=int, default=4)
    command.add_argument("--limit", type=int)
    command.add_argument("--algorithm", choices=("reference", "aligned", "aligned_indexed", "aligned_closed", "aligned_melody"), default="reference")
    command.add_argument("--mode", choices=("exact", "transposed", "approximate"), default=None,
                         help="reference matching mode (default: approximate)")
    command.add_argument("--top-k", type=int, default=3)
    command.add_argument("--seed-bucket-limit", type=int,
                         help="aligned algorithms only: seed postings per key, 1 to 2048 (default: 192)")
    command.add_argument("--no-midi", action="store_true")
    command.add_argument("--percussion", action="store_true")
    command.add_argument("--recover-invalid-keys", action="store_true",
                         help="ignore structurally validated invalid key metadata, recording every repair")
    catalog = sub.add_parser("catalog", help="index existing corpus results without downloading data")
    catalog.add_argument("--manifest", type=Path, required=True)
    catalog.add_argument("--output", type=Path, required=True)
    catalog.add_argument("--max-output-mb", type=int, default=256)
    catalog.add_argument("--min-free-mb", type=int, default=1024)
    search = sub.add_parser("catalog-search", help="filter catalog phrases without writing to the index")
    search.add_argument("--catalog",type=Path,required=True)
    for name in ("text","dataset","category","value"):
        search.add_argument("--"+name)
    search.add_argument("--kind",choices=("melodic","percussion"))
    from .catalog import FAMILIES, RIGHTS
    search.add_argument("--instrument",choices=(*FAMILIES,"drums"))
    search.add_argument("--rights",choices=sorted(RIGHTS))
    search.add_argument("--redistribution",choices=sorted(RIGHTS))
    search.add_argument("--min-repeats",type=int,default=2)
    search.add_argument("--min-beats",type=float)
    search.add_argument("--max-beats",type=float)
    search.add_argument("--no-warnings",action="store_true")
    search.add_argument("--no-search-limit",action="store_true")
    search.add_argument("--sort",choices=("repeats","duration","density","score","title"),default="repeats")
    search.add_argument("--limit",type=int,default=50)
    search.add_argument("--offset",type=int,default=0)
    search.add_argument("--output",type=Path)
    search.add_argument("--format",choices=("json","csv"),default="json")
    info = sub.add_parser("catalog-info",help="list catalog sources, annotation categories and values")
    info.add_argument("--catalog",type=Path,required=True)
    info.add_argument("--category")
    args = parser.parse_args()
    if args.command == "catalog-info":
        from .catalog_search import info
        print(json.dumps(info(args.catalog,category=args.category),ensure_ascii=False,indent=2))
        return
    if args.command == "catalog-search":
        from .catalog_search import search, export
        filters={k:getattr(args,k) for k in ("text","dataset","kind","instrument","category","value","rights", "redistribution","min_repeats","min_beats","max_beats","no_warnings","no_search_limit","sort","limit","offset")}
        try:
            result=search(args.catalog,**filters)
            if args.output:export(result,args.output,format=args.format)
            elif args.format!="json":parser.error("CSV export requires --output")
            else:print(json.dumps(result,ensure_ascii=False,indent=2))
        except ValueError as exc:parser.error(str(exc))
        return
    if args.command == "catalog":
        from .catalog import build_catalog
        result = build_catalog(args.manifest, args.output,
                               max_output_mb=args.max_output_mb, min_free_mb=args.min_free_mb)
        print(json.dumps(result, indent=2))
        return
    if args.command == "build":
        if args.algorithm in {"aligned", "aligned_indexed", "aligned_closed", "aligned_melody"}:
            if args.mode is not None:
                parser.error("--mode is only supported with --algorithm reference")
            if args.seed_bucket_limit is not None and not 1 <= args.seed_bucket_limit <= 2048:
                parser.error("--seed-bucket-limit must be between 1 and 2048")
            from .aligned import AlignedConfig
            overrides = {} if args.seed_bucket_limit is None else {"max_bucket": args.seed_bucket_limit}
            config = AlignedConfig(top_k=args.top_k, **overrides)
        else:
            if args.seed_bucket_limit is not None:
                parser.error("--seed-bucket-limit requires an aligned algorithm")
            config = Config(mode=args.mode or "approximate", top_k=args.top_k)
        result = build(args.source, args.output, config,
                       workers=args.workers, limit=args.limit, export=not args.no_midi,
                       percussion=args.percussion, algorithm=args.algorithm,
                       recover_invalid_keys=args.recover_invalid_keys)
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
