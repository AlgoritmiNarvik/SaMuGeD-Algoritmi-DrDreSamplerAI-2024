from __future__ import annotations

from hashlib import sha256
from pathlib import Path

import mido
import pytest

from scripts.plot_recurrence_examples import (
    distinct_occurrence_intervals,
    select_rows,
    verified_example,
)


def _write_source(path: Path) -> None:
    path.parent.mkdir(parents=True)
    midi = mido.MidiFile(ticks_per_beat=480)
    track = mido.MidiTrack()
    midi.tracks.append(track)
    events = []
    for origin, pitches in (
        (0, (60, 62, 64, 65)),
        (960, (65, 67, 69, 70)),
        (1920, (67, 69, 71, 72)),
    ):
        for index, pitch in enumerate(pitches):
            start = origin + index * 120
            events.append((start, 1, mido.Message("note_on", note=pitch, velocity=90)))
            events.append((start + 60, 0, mido.Message("note_off", note=pitch, velocity=0)))
    previous = 0
    for tick, _order, message in sorted(events, key=lambda item: (item[0], item[1])):
        message.time = tick - previous
        track.append(message)
        previous = tick
    midi.save(path)


def _row(phrase_id: str = "phrase", kind: str = "melodic") -> dict:
    return {
        "source_id": "source",
        "source_path": "source.mid",
        "source_sha256": "pending",
        "split_group": "group",
        "phrase_id": phrase_id,
        "family_id": f"family-{phrase_id}",
        "kind": kind,
        "part_index": 0,
        "start_tick": 0,
        "end_tick": 420,
        "note_count": 4,
        "prototype_note_index": 0,
        "occurrence_count": 3,
        "occurrences": [
            {"start_tick": 0, "end_tick": 420, "note_index": 0},
            {"start_tick": 960, "end_tick": 1380, "note_index": 4},
            {"start_tick": 1920, "end_tick": 2340, "note_index": 8},
        ],
        "pitches": [1, 2, 3, 4],
    }


def test_occurrence_intervals_require_three_distinct_saved_coordinates() -> None:
    row = _row()
    row["occurrences"].insert(1, dict(row["occurrences"][0]))
    row["occurrence_count"] = 4
    assert distinct_occurrence_intervals(row) == [(0, 420), (960, 1380), (1920, 2340)]
    row["occurrences"] = row["occurrences"][:3]
    with pytest.raises(ValueError, match="three distinct"):
        distinct_occurrence_intervals(row)


def test_selection_is_order_independent_and_kind_specific() -> None:
    rows = [_row("m-z"), _row("m-a"), _row("d-z", "percussion"), _row("d-a", "percussion")]
    first = select_rows(rows, "fixed-seed")
    second = select_rows(reversed(rows), "fixed-seed")
    assert {kind: row["phrase_id"] for kind, row in first.items()} == {
        kind: row["phrase_id"] for kind, row in second.items()
    }
    assert set(first) == {"melodic", "percussion"}

    invalid = _row("invalid")
    invalid["occurrences"][1]["end_tick"] = invalid["occurrences"][1]["start_tick"]
    with pytest.raises(ValueError, match="invalid occurrence interval"):
        select_rows([*rows, invalid], "fixed-seed")


def test_verified_example_reads_source_notes_and_distinct_slices(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    midi_path = source_root / "source.mid"
    _write_source(midi_path)
    source_hash = sha256(midi_path.read_bytes()).hexdigest()
    row = _row()
    row["source_sha256"] = source_hash
    source_record = {
        "source_id": "source",
        "source_path": "source.mid",
        "source_sha256": source_hash,
        "status": "ok",
        "split_group": "group",
        "config": {"onset_merge_beats": 1 / 24},
    }
    example = verified_example(row, source_record, source_root.resolve())
    assert [[note["pitch"] for note in snippet["notes"]] for snippet in example["snippets"]] == [
        [60, 62, 64, 65],
        [65, 67, 69, 70],
        [67, 69, 71, 72],
    ]
    assert len({(item["start_tick"], item["end_tick"]) for item in example["snippets"]}) == 3
    assert [1, 2, 3, 4] not in [
        [note["pitch"] for note in snippet["notes"]] for snippet in example["snippets"]
    ]
    source_record["source_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="hashes disagree"):
        verified_example(row, source_record, source_root.resolve())
