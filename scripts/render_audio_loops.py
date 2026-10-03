#!/usr/bin/env python3
"""Render source-derived MIDI and audio loops for selected phrase IDs."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from samuged.audio_loops import render_audio_loops


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--phrase-ids-json",
        required=True,
        type=Path,
        help="JSON list of phrase IDs or object containing candidates",
    )
    parser.add_argument(
        "--dataset",
        required=True,
        type=Path,
        help="dataset directory containing phrases.jsonl, or the manifest itself",
    )
    parser.add_argument(
        "--source", required=True, type=Path, help="root of the source MIDI corpus"
    )
    parser.add_argument("--soundfont", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--fluidsynth",
        type=Path,
        default=Path("/opt/homebrew/bin/fluidsynth"),
    )
    parser.add_argument(
        "--ffmpeg", type=Path, default=Path("/opt/homebrew/bin/ffmpeg")
    )
    parser.add_argument("--mp3", action="store_true", help="also create loop.mp3")
    parser.add_argument("--flac", action="store_true", help="also create loop.flac")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest = render_audio_loops(
        args.phrase_ids_json,
        args.dataset,
        args.source,
        args.soundfont,
        args.output,
        fluidsynth=args.fluidsynth,
        ffmpeg=args.ffmpeg,
        make_mp3=args.mp3,
        make_flac=args.flac,
    )
    print(
        f"Rendered {len(manifest['entries'])} source-derived loops to "
        f"{args.output.resolve()}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
