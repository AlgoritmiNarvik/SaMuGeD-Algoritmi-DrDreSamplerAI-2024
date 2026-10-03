"""Curate a local, interface-only Tool MIDI listening supplement.

This script deliberately keeps the external arrangements separate from the
audited corpus. It copies only detector phrase exports into a local packet and
records the public page, direct download URL, source hashes and rights
uncertainty needed to reproduce the selection.
"""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import shutil
import sys

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from scripts.analyze_top_phrases import compact, verify_occurrences


SOURCE_PAGES = {
    "Tool/Forty_Six_&_2.mid": {
        "source_url": (
            "https://midifind.com/files/t/tool/tool_forty_six_2/"
            "1822-1-0-60518"
        ),
        "download_url": "https://midifind.com/files/0-0-1-60518-20",
    },
    "Tool/Lateralus.mid": {
        "source_url": "https://midifind.com/files/t/tool/tool_lateralus/1822-1-0-60548",
        "download_url": "https://midifind.com/files/0-0-1-60548-20",
    },
}


SELECTIONS = {
    "Tool/Forty_Six_&_2.mid": [
        (
            "cd7c48f69f6caf1b688ec310d4e860a0",
            "Justin Chancellor bass ostinato with a low pedal, five pitches and "
            "21 recurrences; it anchors the guitar phrases in a distinct low register.",
        ),
        (
            "16a9aad34d6c34b979633b904235e599",
            "Adam Jones left guitar phrase with a syncopated pickup, four pitches "
            "and an 8.5-beat candidate cycle; selected for a distinct 12-beat "
            "render signature.",
        ),
        (
            "4e81f4b0719fadbfb62bc2eeeabc8f6f",
            "Adam Jones left guitar phrase with a different low pickup and onset "
            "contour; its separate family and 8-beat render signature avoid a "
            "duplicate of the longer guitar row.",
        ),
        (
            "a75ea18ee3c40b3001d4bbe2ffacdf0d",
            "Four-beat drum cycle with six GM drum pitches and 18 hits; selected "
            "for a varied auxiliary-percussion pattern.",
        ),
        (
            "d224d82b96aa09451f8992c2b7a8fba5",
            "Four-beat drum cycle with five GM drum pitches and 21 hits; its "
            "different pitch set and onset pattern complements the first drum row.",
        ),
    ],
    "Tool/Lateralus.mid": [
        (
            "484ce8a9dc73667d16b8292c4e51981e",
            "Guitar 1 phrase with seven pitches across a 15.5-beat cycle and "
            "ten recurrences; selected as the long, changing guitar signature.",
        ),
        (
            "9d4a4f5c671a18896148e995dfbdaf07",
            "Guitar 1 phrase with six pitches across a distinct 12-beat cycle; "
            "selected as a shorter guitar family with a low pickup.",
        ),
        (
            "5d4784c6648959b6edb439af3049a105",
            "Bass phrase with four low pitches and a 4.75-beat cycle; selected "
            "to contrast the two guitar registers.",
        ),
        (
            "365bc73b271bea4d67c56f16b9f432eb",
            "Five-beat drum cycle with 32 hits and six GM drum pitches; selected "
            "as the denser source accompaniment.",
        ),
        (
            "e7cd666d3d471abeeec702141b29037d",
            "Five-beat drum cycle with 23 hits and five GM drum pitches; the "
            "different onset and pitch pattern provides a second drum texture.",
        ),
    ],
}


RIGHTS = (
    "MIDIfind pages provide free MIDI downloads and describe creative use, but "
    "no explicit SPDX or redistribution license was located and the original "
    "arrangement authors are unspecified. This is a local interface-only "
    "supplement outside the audited Lakh corpus; do not publish the full source "
    "songs or treat these rows as Lakh attribution evidence."
)


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def curate(dataset: Path, sources: Path, output: Path) -> dict:
    if output.exists():
        raise FileExistsError(f"output already exists: {output}")
    rows = {row["phrase_id"]: row for row in _read_jsonl(dataset / "phrases.jsonl")}
    source_rows = {row["source_path"]: row for row in _read_jsonl(dataset / "sources.jsonl")}
    selected = []
    selected_ids = set()
    source_packets = []

    for source_path, choices in SELECTIONS.items():
        if source_path not in SOURCE_PAGES or source_path not in source_rows:
            raise ValueError(f"missing source metadata: {source_path}")
        source = source_rows[source_path]
        source_file = sources / source_path
        if not source_file.is_file():
            raise FileNotFoundError(source_file)
        source_hash = sha256(source_file.read_bytes()).hexdigest()
        if source_hash != source["source_sha256"]:
            raise ValueError(f"source hash mismatch: {source_path}")

        chosen_for_source = []
        melodic = percussion = 0
        for phrase_id, rationale in choices:
            if phrase_id in selected_ids:
                raise ValueError(f"duplicate selected phrase: {phrase_id}")
            row = rows.get(phrase_id)
            if row is None or row["source_path"] != source_path:
                raise ValueError(f"phrase does not belong to source: {phrase_id}")
            verify_occurrences(row)
            if row["kind"] == "melodic":
                melodic += 1
            elif row["kind"] == "percussion":
                percussion += 1
            else:
                raise ValueError(f"unsupported phrase kind: {row['kind']}")
            selected_ids.add(phrase_id)
            chosen_for_source.append((phrase_id, rationale))

        if len(chosen_for_source) != 5 or melodic != 3 or percussion != 2:
            raise ValueError(
                f"{source_path} must have 3 melodic and 2 percussion selections"
            )

        source_packets.append(
            {
                "source_path": source_path,
                "source_sha256": source_hash,
                "source_url": SOURCE_PAGES[source_path]["source_url"],
                "download_url": SOURCE_PAGES[source_path]["download_url"],
                "source_status": source["status"],
                "drum_available": bool(source.get("drum_stats", {}).get("input_hits")),
                "drum_source_tracks": source.get("drum_stats", {}).get("source_tracks", []),
                "drum_source_part_indices": source.get("drum_stats", {}).get("source_part_indices", []),
                "search_limited": source["search_limited"],
                "curation_truncated": source["curation_truncated"],
                "selected_phrase_ids": [phrase_id for phrase_id, _ in chosen_for_source],
            }
        )

    output.mkdir(parents=True)
    (output / "midi").mkdir()
    candidates = []
    chosen_notes = []
    rank = 0
    for source_path, choices in SELECTIONS.items():
        source = source_rows[source_path]
        page = SOURCE_PAGES[source_path]
        for phrase_id, rationale in choices:
            rank += 1
            row = rows[phrase_id]
            verify_occurrences(row)
            exported = dataset / row["midi_path"]
            if sha256(exported.read_bytes()).hexdigest() != row["midi_sha256"]:
                raise ValueError(f"detector MIDI hash mismatch: {phrase_id}")
            target = output / row["midi_path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(exported, target)
            candidate = compact(row)
            candidate.update(
                {
                    "rank": rank,
                    "midi_file": row["midi_path"],
                    "midi_sha256": row["midi_sha256"],
                    "source_sha256": source["source_sha256"],
                    "search_limited": source["search_limited"],
                    "curation_truncated": source["curation_truncated"],
                    "occurrence_ticks": [
                        {"start": occurrence["start_tick"], "end": occurrence["end_tick"]}
                        for occurrence in row["occurrences"]
                    ],
                    "rationale": rationale,
                    "source_url": page["source_url"],
                    "external_source_url": page["source_url"],
                    "download_url": page["download_url"],
                }
            )
            candidates.append(candidate)
            chosen_notes.append(
                {
                    "rank": rank,
                    "phrase_id": phrase_id,
                    "source_path": source_path,
                    "kind": row["kind"],
                    "part_name": row.get("part_name", "source drum merge"),
                    "cycle_beats": row["duration_beats"],
                    "why": rationale,
                }
            )

    selected_rows = [rows[phrase_id] for phrase_id in selected_ids]
    selected_rows.sort(key=lambda row: next(item["rank"] for item in candidates if item["phrase_id"] == row["phrase_id"]))
    (output / "phrases.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in selected_rows),
        encoding="utf-8",
    )
    (output / "sources.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in source_rows.values()),
        encoding="utf-8",
    )
    for name in ("build_config.json", "summary.json"):
        shutil.copyfile(dataset / name, output / name)

    packet = {
        "version": "samuged-external-tool-listening-v1",
        "scope": "local interface-only supplemental selection",
        "claim": "Editorial listening selection outside the audited Lakh corpus; no recognition or popularity claim.",
        "rights": RIGHTS,
        "attribution": "MIDIfind.com public Tool MIDI pages; arrangement authors were not identified on the pages.",
        "source_pages": source_packets,
        "candidates": candidates,
        "chosen_ids_and_why": chosen_notes,
        "inputs": {
            name: {"sha256": sha256((dataset / name).read_bytes()).hexdigest(), "bytes": (dataset / name).stat().st_size}
            for name in ("phrases.jsonl", "sources.jsonl", "build_config.json", "summary.json")
        },
        "selected_source_files": 2,
        "selected_phrase_count": len(candidates),
        "selected_melodic_count": sum(row["kind"] == "melodic" for row in candidates),
        "selected_percussion_count": sum(row["kind"] == "percussion" for row in candidates),
    }
    (output / "selection.json").write_text(json.dumps(packet, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return packet


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    packet = curate(args.dataset, args.source, args.output)
    print(json.dumps({"selected_ids": [row["phrase_id"] for row in packet["candidates"]], "count": len(packet["candidates"])}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
