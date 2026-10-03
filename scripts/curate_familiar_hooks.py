#!/usr/bin/env python3
"""Build a familiarity informed ten phrase demo without a corpus rerun.

Seven rows are copied unchanged from the audited closed phrase manifest. Three
additional rows are extracted from explicitly named lead parts in three source
files. Published song recognition or earworm evidence determines membership
and ordering only. It does not validate any selected MIDI fragment as a hook.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
import shutil
import sys
import tempfile
from typing import Any


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from samuged.aligned import AlignedConfig
from samuged.aligned_indexed import detect_indexed_part
from samuged.dataset import canonical_json, file_digest
from samuged.midi import MidiSong, Note, Part, export_phrase, load_midi


VERSION = "familiar-hook-demo-v1"
SUPPLEMENT_NAMESPACE = "samuged-familiar-hooks-v1"
HOOKED_STUDY_URL = (
    "https://www.mcg.uva.nl/mcg-2023/papers/Burgoyne-et-al-2013.pdf"
)
HOOKED_RANKING_TABLE_URL = (
    "https://mever.gr/publications/"
    "Data-Driven%20Song%20Recognition%20Estimation%20Using%20"
    "Collective%20Memory%20Dynamics%20Models.pdf"
)
HOOKED_UVA_URL = "https://www.mcg.uva.nl/news/"
EARWORM_PAPER_URL = "https://www.apa.org/pubs/journals/releases/aca-aca0000090.pdf"
EARWORM_GOLDSMITHS_URL = (
    "https://www.gold.ac.uk/news/scientists-find-key-to-writing-catchy-pop-hits/"
)


@dataclass(frozen=True)
class LeadExtraction:
    part_index: int
    part_name: str
    program: int
    source_track: int
    channel: int
    family_id: str
    start_tick: int
    end_tick: int


@dataclass(frozen=True)
class SelectionSpec:
    source_path: str
    evidence_type: str
    published_rank: int | None
    rationale: str
    saved_phrase_id: str | None = None
    lead: LeadExtraction | None = None


# The first nine entries retain the published Hooked on Music recognition
# order. Rank four, Lady Gaga/Just Dance, has no exact source label in the
# closed corpus. Journey is appended as a separate earworm occurrence result.
SELECTION_SPECS: tuple[SelectionSpec, ...] = (
    SelectionSpec(
        "Spice_Girls/Wannabe.1.mid",
        "hooked_on_music_song_recognition",
        1,
        "The saved top three select bass or guitar accompaniment. Extract the "
        "labelled Girls lead part instead.",
        lead=LeadExtraction(
            5,
            "Girls",
            82,
            1,
            0,
            "9e33c0f5dce4e7d8502a72586c285449ae6ccc41b3af2df30ac36a2b7c00e007",
            29184,
            33968,
        ),
    ),
    SelectionSpec(
        "Lou_Bega/Mambo_No._5_A_Little_Bit_Of..._.mid",
        "hooked_on_music_song_recognition",
        2,
        "Repeated upper brass figure with two closely matching units.",
        saved_phrase_id="6af3fc6b5a1110e8b4dc9168e9641ccd",
    ),
    SelectionSpec(
        "Survivor/Eye_Of_The_Tiger.mid",
        "hooked_on_music_song_recognition",
        3,
        "The saved top three are bass phrases. Extract the labelled Melody part.",
        lead=LeadExtraction(
            6,
            "Melody",
            85,
            3,
            3,
            "7c45af6db33f5a81d284ba5e2e8335e330fb239388c4fb32e6853a5c49185826",
            30720,
            34207,
        ),
    ),
    SelectionSpec(
        "ABBA/S.O.S.1.mid",
        "hooked_on_music_song_recognition",
        5,
        "Repeated upper line built from descending three note cells and holds.",
        saved_phrase_id="cc392b44b7887e4378a9a387bc4e94aa",
    ),
    SelectionSpec(
        "Roy_Orbison/Oh_Pretty_Woman.2.mid",
        "hooked_on_music_song_recognition",
        6,
        "Repeated Guitar 2 figure with a stable eight note pitch shape.",
        saved_phrase_id="c94ffa5f10cac504d772b96144401147",
    ),
    SelectionSpec(
        "Michael_Jackson/Beat_It.mid",
        "hooked_on_music_song_recognition",
        7,
        "Repeated Guitar 1 phrase rather than bass or percussion.",
        saved_phrase_id="16803dc5abfa9acf39847280a9c704de",
    ),
    SelectionSpec(
        "Whitney_Houston/I_Will_Always_Love_You.4.mid",
        "hooked_on_music_song_recognition",
        8,
        "The saved top three are bass or keyboard accompaniment. Extract the "
        "labelled CANTO part.",
        lead=LeadExtraction(
            0,
            "CANTO",
            49,
            10,
            8,
            "9969871ec95a5d934db25927107cf04ca8ecce46214fdbfa4f5e23da9c2fc93f",
            18412,
            21194,
        ),
    ),
    SelectionSpec(
        "The_Human_League/Dont_You_Want_Me.1.mid",
        "hooked_on_music_song_recognition",
        9,
        "Repeated high synth brass line containing two similar units.",
        saved_phrase_id="4a0f92440855b5ee6bb0f4c6d53fe9df",
    ),
    SelectionSpec(
        "Aerosmith/I_Dont_Want_to_Miss_a_Thing.1.mid",
        "hooked_on_music_song_recognition",
        10,
        "Repeated monophonic high register phrase on the song named part.",
        saved_phrase_id="99583a7102836be60c7deb86b130939f",
    ),
    SelectionSpec(
        "Journey/Dont_Stop_Believin.2.mid",
        "self_reported_involuntary_musical_imagery_song",
        None,
        "Repeated half beat piano ostinato. Earworm evidence applies to the song, "
        "not this fragment.",
        saved_phrase_id="66f32a4efbabe5d2dc7cca2181963647",
    ),
)


def _jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text(
        "".join(canonical_json(row) + "\n" for row in rows), encoding="utf-8"
    )


def _json(path: Path, value: object) -> None:
    path.write_text(canonical_json(value) + "\n", encoding="utf-8")


def _safe_source(root: Path, relative: str) -> Path:
    pure = PurePosixPath(relative)
    if pure.is_absolute() or ".." in pure.parts or "\\" in relative:
        raise ValueError(f"unsafe source path: {relative}")
    resolved_root = root.resolve(strict=True)
    path = (resolved_root / pure).resolve(strict=True)
    if not path.is_file() or not path.is_relative_to(resolved_root):
        raise ValueError(f"source path is absent or escapes the source root: {relative}")
    return path


def _read_selected_phrases(path: Path) -> dict[str, dict[str, Any]]:
    wanted = {
        spec.saved_phrase_id for spec in SELECTION_SPECS if spec.saved_phrase_id
    }
    rows: dict[str, dict[str, Any]] = {}
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            phrase_id = row.get("phrase_id") if isinstance(row, dict) else None
            if phrase_id in wanted:
                if phrase_id in rows:
                    raise ValueError(
                        f"duplicate selected phrase ID at line {line_number}: {phrase_id}"
                    )
                rows[phrase_id] = row
    missing = sorted(wanted - set(rows))
    if missing:
        raise ValueError(f"saved phrase IDs are absent from the closed manifest: {missing}")
    return rows


def _read_selected_sources(
    path: Path, source_ids: set[str], source_paths: set[str]
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    by_id: dict[str, dict[str, Any]] = {}
    by_path: dict[str, dict[str, Any]] = {}
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError(f"invalid source row at line {line_number}")
            source_id, source_path = row.get("source_id"), row.get("source_path")
            if source_id in source_ids or source_path in source_paths:
                if source_id in by_id or source_path in by_path:
                    raise ValueError(f"duplicate selected source at line {line_number}")
                by_id[source_id] = row
                by_path[source_path] = row
    missing_ids = sorted(source_ids - set(by_id))
    missing_paths = sorted(source_paths - set(by_path))
    if missing_ids or missing_paths:
        raise ValueError(
            f"selected source records are absent: ids={missing_ids}, paths={missing_paths}"
        )
    return by_id, by_path


def supplement_phrase_id(source: dict[str, Any], candidate: dict[str, Any]) -> str:
    """Return a stable ID in the familiarity supplement namespace."""

    material = (
        SUPPLEMENT_NAMESPACE,
        source["source_id"],
        source["source_sha256"],
        "melodic",
        candidate["part_index"],
        candidate["family_id"],
        candidate["start_tick"],
    )
    return sha256(canonical_json(material).encode("utf-8")).hexdigest()[:32]


def _part(song: MidiSong, lead: LeadExtraction) -> Part:
    matches = [part for part in song.parts if part.index == lead.part_index]
    if len(matches) != 1 or matches[0].is_drum:
        raise ValueError(f"lead part {lead.part_index} is unavailable")
    part = matches[0]
    observed = (part.name, part.program, part.track, part.channel)
    expected = (lead.part_name, lead.program, lead.source_track, lead.channel)
    if observed != expected:
        raise ValueError(
            f"lead part identity differs: observed={observed!r}, expected={expected!r}"
        )
    return part


def _candidate(
    song: MidiSong, part: Part, source: dict[str, Any], lead: LeadExtraction
) -> tuple[dict[str, Any], dict[str, Any]]:
    config_value = source.get("config")
    if not isinstance(config_value, dict):
        raise ValueError("source record has no detector config")
    config = AlignedConfig(**config_value)
    candidates, audit = detect_indexed_part(song, part, config)
    matches = [
        candidate
        for candidate in candidates
        if candidate["family_id"] == lead.family_id
        and candidate["start_tick"] == lead.start_tick
        and candidate["end_tick"] == lead.end_tick
    ]
    if len(matches) != 1:
        raise ValueError(
            "bounded lead extraction did not reproduce the frozen candidate identity"
        )
    return matches[0], audit


def _row_notes(row: dict[str, Any], ticks_per_beat: int) -> list[Note]:
    values = (
        row.get("onsets_beats"),
        row.get("durations_beats"),
        row.get("pitches"),
        row.get("velocities"),
    )
    if not all(isinstance(value, list) for value in values):
        raise ValueError("melodic phrase arrays are missing")
    if len({len(value) for value in values}) != 1 or len(values[0]) != row.get(
        "note_count"
    ):
        raise ValueError("melodic phrase arrays differ in length")
    start = row["start_tick"]
    return [
        Note(
            start + round(onset * ticks_per_beat),
            start + round((onset + duration) * ticks_per_beat),
            pitch,
            velocity,
        )
        for onset, duration, pitch, velocity in zip(*values)
    ]


def validate_phrase_source_coordinates(
    row: dict[str, Any], source: dict[str, Any], song: MidiSong
) -> Part:
    """Verify manifest identity, part coordinates and source backed occurrences."""

    for field in (
        "source_id",
        "source_path",
        "source_sha256",
        "song_key",
        "split",
        "split_group",
        "artist_from_path",
        "title_from_path",
    ):
        if row.get(field) != source.get(field):
            raise ValueError(f"phrase {field} differs from its source record")
    if row.get("ticks_per_beat") != song.ticks_per_beat:
        raise ValueError("phrase ticks_per_beat differs from source MIDI")
    matches = [part for part in song.parts if part.index == row.get("part_index")]
    if len(matches) != 1 or matches[0].is_drum:
        raise ValueError("phrase references an unavailable melodic part")
    part = matches[0]
    for field, actual in (
        ("source_track", part.track),
        ("channel", part.channel),
        ("program", part.program),
        ("part_name", part.name),
    ):
        if row.get(field) != actual:
            raise ValueError(f"phrase {field} differs from source MIDI")
    source_notes = {(note.start, note.end, note.pitch, note.velocity) for note in part.notes}
    for note in _row_notes(row, song.ticks_per_beat):
        if (note.start, note.end, note.pitch, note.velocity) not in source_notes:
            raise ValueError("prototype note is absent from the source part")
    occurrences = row.get("occurrences")
    if not isinstance(occurrences, list) or len(occurrences) != row.get(
        "occurrence_count"
    ):
        raise ValueError("phrase occurrence count differs from occurrence rows")
    source_end = max((note.end for note in part.notes), default=0)
    for occurrence in occurrences:
        if occurrence.get("source_verified") is not True:
            raise ValueError("phrase contains a non source verified occurrence")
        start, end = occurrence.get("start_tick"), occurrence.get("end_tick")
        if (
            not isinstance(start, int)
            or not isinstance(end, int)
            or start < 0
            or end <= start
            or end > source_end
        ):
            raise ValueError("phrase contains invalid source occurrence coordinates")
    return part


def supplement_phrase_row(
    source: dict[str, Any], candidate: dict[str, Any], song: MidiSong
) -> dict[str, Any]:
    """Map a bounded detector candidate into the public phrase schema."""

    row = {
        **candidate,
        "artist_from_path": source["artist_from_path"],
        "kind": "melodic",
        "phrase_id": supplement_phrase_id(source, candidate),
        "rank_in_file": 1,
        "song_key": source["song_key"],
        "source_id": source["source_id"],
        "source_path": source["source_path"],
        "source_sha256": source["source_sha256"],
        "split": source["split"],
        "split_group": source["split_group"],
        "ticks_per_beat": song.ticks_per_beat,
        "title_from_path": source["title_from_path"],
    }
    validate_phrase_source_coordinates(row, source, song)
    return row


def _evidence_urls(spec: SelectionSpec) -> list[str]:
    if spec.evidence_type == "hooked_on_music_song_recognition":
        return [HOOKED_STUDY_URL, HOOKED_RANKING_TABLE_URL, HOOKED_UVA_URL]
    return [EARWORM_PAPER_URL, EARWORM_GOLDSMITHS_URL]


def _limits(audit: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "candidate_limit_reached",
        "comparison_limit_reached",
        "group_limit_reached",
        "note_limit_reached",
        "window_limit_reached",
        "candidates_truncated",
        "saturated_seed_buckets",
    )
    return {key: audit[key] for key in keys}


def _copy_saved_midi(dataset: Path, row: dict[str, Any], destination: Path) -> None:
    relative = row.get("midi_path")
    if not isinstance(relative, str):
        raise ValueError(f"saved phrase {row.get('phrase_id')} has no MIDI path")
    source = (dataset / relative).resolve(strict=True)
    if not source.is_file() or not source.is_relative_to(dataset.resolve()):
        raise ValueError(f"saved phrase MIDI escapes the dataset: {relative}")
    if file_digest(source) != row.get("midi_sha256"):
        raise ValueError(f"saved phrase MIDI hash differs: {row.get('phrase_id')}")
    target = destination / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)


def _export_supplement_midi(
    destination: Path, row: dict[str, Any], song: MidiSong, part: Part
) -> None:
    relative = Path("midi") / "melodic" / f"{row['phrase_id']}.mid"
    target = destination / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    export_phrase(
        song,
        part,
        _row_notes(row, song.ticks_per_beat),
        row["start_tick"],
        row["end_tick"],
        target,
    )
    row["midi_path"] = relative.as_posix()
    row["midi_sha256"] = file_digest(target)


def _existing_output_is_generated(output: Path) -> bool:
    allowed = {"midi", "phrases.jsonl", "selection.json", "sources.jsonl"}
    return output.is_dir() and all(path.name in allowed for path in output.iterdir())


def _install(staging: Path, output: Path) -> None:
    if not output.exists():
        staging.replace(output)
        return
    if not _existing_output_is_generated(output):
        raise ValueError(f"refusing to replace non generated output directory: {output}")
    backup = output.with_name(output.name + ".previous")
    if backup.exists():
        raise ValueError(f"stale output backup exists: {backup}")
    output.replace(backup)
    try:
        staging.replace(output)
    except Exception:
        backup.replace(output)
        raise
    shutil.rmtree(backup)


def curate_familiar_hooks(dataset: Path, source_root: Path, output: Path) -> dict:
    """Create the ten item manifest, MIDI bundle and selection receipt."""

    dataset = dataset.resolve(strict=True)
    source_root = source_root.resolve(strict=True)
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    saved_rows = _read_selected_phrases(dataset / "phrases.jsonl")
    source_ids = {row["source_id"] for row in saved_rows.values()}
    lead_paths = {spec.source_path for spec in SELECTION_SPECS if spec.lead}
    sources_by_id, sources_by_path = _read_selected_sources(
        dataset / "sources.jsonl", source_ids, lead_paths
    )

    staging = Path(
        tempfile.mkdtemp(prefix=f".{output.name}-", dir=str(output.parent))
    )
    try:
        phrase_rows: list[dict[str, Any]] = []
        source_rows: list[dict[str, Any]] = []
        selections: list[dict[str, Any]] = []
        seen_sources: set[str] = set()
        for demo_order, spec in enumerate(SELECTION_SPECS, 1):
            extraction_limits: dict[str, Any] | None = None
            if spec.saved_phrase_id:
                row = saved_rows[spec.saved_phrase_id]
                source = sources_by_id[row["source_id"]]
                if row["source_path"] != spec.source_path:
                    raise ValueError(
                        f"saved phrase source differs from selection: {row['phrase_id']}"
                    )
                _copy_saved_midi(dataset, row, staging)
                method = "closed_manifest_saved_phrase"
            else:
                if spec.lead is None:
                    raise ValueError("selection has neither a saved phrase nor a lead")
                source = sources_by_path[spec.source_path]
                source_path = _safe_source(source_root, spec.source_path)
                if file_digest(source_path) != source.get("source_sha256"):
                    raise ValueError(f"source MIDI hash differs: {spec.source_path}")
                song = load_midi(source_path, recover_invalid_keys=True)
                part = _part(song, spec.lead)
                candidate, audit = _candidate(song, part, source, spec.lead)
                row = supplement_phrase_row(source, candidate, song)
                _export_supplement_midi(staging, row, song, part)
                extraction_limits = _limits(audit)
                method = "bounded_labelled_lead_part_extraction"

            phrase_rows.append(row)
            if source["source_id"] not in seen_sources:
                source_rows.append(source)
                seen_sources.add(source["source_id"])
            candidate_receipt = {
                "artist_from_path": row["artist_from_path"],
                "demo_order": demo_order,
                "evidence_urls": _evidence_urls(spec),
                "fragment_evidence": (
                    "Symbolic part role and recurrence only. No listener recognition, "
                    "recall or earworm response was measured for this fragment."
                ),
                "phrase_id": row["phrase_id"],
                "published_recognition_rank": spec.published_rank,
                "rationale": spec.rationale,
                "selection_method": method,
                "song_evidence_type": spec.evidence_type,
                "source_id": row["source_id"],
                "source_path": row["source_path"],
                "title_from_path": row["title_from_path"],
            }
            if extraction_limits is not None:
                candidate_receipt["bounded_extraction"] = {
                    "config": source["config"],
                    "limits": extraction_limits,
                    "namespace": SUPPLEMENT_NAMESPACE,
                    "part": {
                        "channel": row["channel"],
                        "index": row["part_index"],
                        "name": row["part_name"],
                        "program": row["program"],
                        "source_track": row["source_track"],
                    },
                }
            selections.append(candidate_receipt)

        phrase_ids = [row["phrase_id"] for row in phrase_rows]
        if len(phrase_ids) != 10 or len(set(phrase_ids)) != 10:
            raise ValueError("familiar hook selection must contain ten unique phrases")
        _jsonl(staging / "phrases.jsonl", phrase_rows)
        _jsonl(staging / "sources.jsonl", source_rows)
        selection = {
            "version": VERSION,
            "candidates": selections,
            "claim": (
                "Familiarity informed recurrent MIDI phrase demonstration. Song level "
                "evidence does not validate fragment level recognisability or earworm status."
            ),
            "ordering": (
                "Nine exact corpus labels in published Hooked on Music recognition order "
                "with the absent rank four omitted, followed by one separately labelled "
                "song from the published earworm occurrence list. This is not a measured "
                "fragment ranking."
            ),
            "phrase_ids": phrase_ids,
            "source_dataset": {
                "path": str(dataset),
                "phrases_jsonl_sha256": file_digest(dataset / "phrases.jsonl"),
                "sources_jsonl_sha256": file_digest(dataset / "sources.jsonl"),
            },
            "output_artifacts": {
                "phrases.jsonl": file_digest(staging / "phrases.jsonl"),
                "sources.jsonl": file_digest(staging / "sources.jsonl"),
            },
            "source_record_policy": (
                "The complete closed build source record is copied without field changes. "
                "Supplement phrase provenance is carried by the phrase row and this receipt."
            ),
        }
        _json(staging / "selection.json", selection)
        _install(staging, output)
        return selection
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset",
        type=Path,
        default=REPOSITORY_ROOT / "research_local/lakh_aligned_closed_v01",
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=REPOSITORY_ROOT / "datasets/Lakh MIDI Clean",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=REPOSITORY_ROOT / "research_local/publication_v01/familiar",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    selection = curate_familiar_hooks(args.dataset, args.source, args.output)
    print(
        f"Wrote {len(selection['candidates'])} familiarity informed phrases to "
        f"{args.output.resolve()}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
