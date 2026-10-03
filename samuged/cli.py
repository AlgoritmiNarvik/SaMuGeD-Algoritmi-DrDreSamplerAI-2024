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
    command.add_argument("--no-midi", action="store_true")
    command.add_argument("--percussion", action="store_true")
    command.add_argument("--recover-invalid-keys", action="store_true",
                         help="ignore structurally validated invalid key metadata, recording every repair")
    args = parser.parse_args()
    if args.command == "build":
        if args.algorithm in {"aligned", "aligned_indexed", "aligned_closed", "aligned_melody"}:
            if args.mode is not None:
                parser.error("--mode is only supported with --algorithm reference")
            from .aligned import AlignedConfig
            config = AlignedConfig(top_k=args.top_k)
        else:
            config = Config(mode=args.mode or "approximate", top_k=args.top_k)
        result = build(args.source, args.output, config,
                       workers=args.workers, limit=args.limit, export=not args.no_midi,
                       percussion=args.percussion, algorithm=args.algorithm,
                       recover_invalid_keys=args.recover_invalid_keys)
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
