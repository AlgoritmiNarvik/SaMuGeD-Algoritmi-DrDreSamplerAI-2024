"""Select saved Tool melodic and percussion patterns for the listening case study."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from scripts.analyze_top_phrases import compact, rank_key


def signature(row: dict) -> tuple:
    """Compare pitch and timing content independently of absolute song position."""
    onsets = row.get("onsets_beats", [])
    origin = onsets[0] if onsets else 0
    return (row["kind"], row.get("program"), tuple(row["pitches"]),
            tuple(round(value - origin, 6) for value in onsets),
            tuple(round(value, 6) for value in row.get("durations_beats", [])))


def select(dataset: Path, melodic_per_song: int = 3, drums_per_song: int = 2) -> dict:
    if melodic_per_song < 1 or drums_per_song < 1:
        raise ValueError("per song limits must be positive")
    manifest = dataset / "phrases.jsonl"
    rows = []
    source_paths = set()
    for line in manifest.open(encoding="utf-8"):
        row = json.loads(line)
        if row["artist_from_path"].replace("_", " ").strip().casefold() != "tool":
            continue
        source_paths.add(row["source_path"])
        rows.append(row)
    counts, seen, selected = {}, set(), []
    for row in sorted(rows, key=rank_key):
        group = (row["song_key"], row["kind"])
        fingerprint = (row["song_key"], signature(row))
        limit = drums_per_song if row["kind"] == "percussion" else melodic_per_song
        if counts.get(group, 0) >= limit or fingerprint in seen:
            continue
        selected.append(row)
        seen.add(fingerprint)
        counts[group] = counts.get(group, 0) + 1
    source_manifest = dataset / "sources.jsonl"
    wanted = {row["source_id"] for row in selected}
    sources = {}
    for line in source_manifest.open(encoding="utf-8"):
        source = json.loads(line)
        if source["source_id"] in wanted:
            sources[source["source_id"]] = source
    candidates = []
    for rank, row in enumerate(selected, 1):
        candidate = compact(row)
        source = sources[row["source_id"]]
        candidate.update(
            rank=rank,
            search_limited=source["search_limited"],
            curation_truncated=source["curation_truncated"],
            rationale="Selected for recurrence and different pitch or timing content within this song. Bass riffs, longer phrases and contrasting source parts are retained. This is a structural listening selection, not a listener rating.",
        )
        candidates.append(candidate)
    if not candidates:
        raise ValueError("no Tool phrases in the supplied manifest")
    return {
        "candidates": candidates,
        "source_paths": len(source_paths),
        "phrase_manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
        "source_manifest_sha256": hashlib.sha256(source_manifest.read_bytes()).hexdigest(),
        "available_candidates": len(rows),
        "limits": {"melodic_per_song": melodic_per_song, "drums_per_song": drums_per_song},
        "selection_policy": "descending recurrence ranking, deduplicate identical pitch and timing content within each song, retain the configured number of melodic and percussion phrases per song including bass riffs",
        "claim": "personal listening case study, no perceptual labels or measured complex rhythm accuracy",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--melodic-per-song", type=int, default=3)
    parser.add_argument("--drums-per-song", type=int, default=2)
    args = parser.parse_args()
    with args.output.open("x", encoding="utf-8") as output:
        json.dump(select(args.dataset, args.melodic_per_song, args.drums_per_song), output, indent=2)
        output.write("\n")
