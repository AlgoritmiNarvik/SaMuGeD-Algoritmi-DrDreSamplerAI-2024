from __future__ import annotations

from copy import deepcopy

import pytest

from samuged.midi import MidiSong, Note, Part
from scripts.curate_familiar_hooks import (
    SELECTION_SPECS,
    supplement_phrase_id,
    supplement_phrase_row,
    validate_phrase_source_coordinates,
)


def _source() -> dict:
    return {
        "artist_from_path": "Exact_Artist_Label",
        "config": {},
        "song_key": "1" * 24,
        "source_id": "2" * 24,
        "source_path": "Exact_Artist_Label/Exact_Title_Label.mid",
        "source_sha256": "3" * 64,
        "split": "train",
        "split_group": "4" * 24,
        "title_from_path": "Exact_Title_Label",
    }


def _candidate() -> dict:
    pairs = [[index, index] for index in range(6)]
    occurrence = {
        "deleted_prototype_note_indices": [],
        "edit_count": 0,
        "end_tick": 700,
        "inserted_note_indices": [],
        "matched_note_pairs": pairs,
        "max_duration_error_beats": 0.0,
        "max_timing_error_beats": 0.0,
        "note_count": 6,
        "note_index": 0,
        "similarity": 1.0,
        "source_verified": True,
        "start_tick": 100,
        "substituted_note_pairs": [],
        "transpose_semitones": 0,
    }
    return {
        "channel": 2,
        "duration_beats": 6.0,
        "durations_beats": [0.5] * 6,
        "end_tick": 700,
        "family_id": "5" * 64,
        "matcher_flags": {
            "fixed_transposition": True,
            "monotone_alignment": True,
            "similarity_only_acceptance": False,
            "source_verified": True,
            "tempo_warp": False,
            "terminal_gaps_allowed": False,
        },
        "note_count": 6,
        "occurrence_count": 2,
        "occurrences": [occurrence, {**occurrence, "start_tick": 800, "end_tick": 1400}],
        "onsets_beats": [0, 1, 2, 3, 4, 5],
        "part_index": 7,
        "part_name": "Lead",
        "pitches": [60, 62, 64, 65, 67, 69],
        "program": 82,
        "prototype_note_index": 0,
        "raw_occurrence_count": 2,
        "recurrence_score": 0.9,
        "score_components": {"match_quality": 1.0},
        "source_track": 3,
        "start_tick": 100,
        "velocities": [80] * 6,
    }


def _song() -> MidiSong:
    prototype = [
        Note(100 + index * 100, 150 + index * 100, pitch, 80)
        for index, pitch in enumerate([60, 62, 64, 65, 67, 69])
    ]
    repeated = [
        Note(800 + index * 100, 900 + index * 100, pitch, 80)
        for index, pitch in enumerate([60, 62, 64, 65, 67, 69])
    ]
    part = Part(7, 3, 2, 82, "Lead", False, prototype + repeated)
    return MidiSong(100, [part], [(0, 500_000)], [(0, 4, 4)], [])


def test_demo_order_retains_published_recognition_order_then_earworm() -> None:
    recognition = [
        spec.published_rank
        for spec in SELECTION_SPECS
        if spec.evidence_type == "hooked_on_music_song_recognition"
    ]

    assert recognition == [1, 2, 3, 5, 6, 7, 8, 9, 10]
    assert len(SELECTION_SPECS) == 10
    assert SELECTION_SPECS[-1].source_path == "Journey/Dont_Stop_Believin.2.mid"
    assert (
        SELECTION_SPECS[-1].evidence_type
        == "self_reported_involuntary_musical_imagery_song"
    )
    assert sum(spec.lead is not None for spec in SELECTION_SPECS) == 3
    assert all(
        (spec.saved_phrase_id is None) != (spec.lead is None)
        for spec in SELECTION_SPECS
    )
    assert all("Queen/" not in spec.source_path for spec in SELECTION_SPECS)
    tiger = next(
        spec
        for spec in SELECTION_SPECS
        if spec.source_path.endswith("Eye_Of_The_Tiger.mid")
    )
    assert tiger.lead is not None
    assert tiger.lead.part_name == "Melody"


def test_supplement_mapping_is_stable_and_preserves_source_coordinates() -> None:
    source, candidate, song = _source(), _candidate(), _song()

    first = supplement_phrase_row(source, candidate, song)
    second = supplement_phrase_row(deepcopy(source), deepcopy(candidate), song)

    assert first == second
    assert first["phrase_id"] == supplement_phrase_id(source, candidate)
    assert len(first["phrase_id"]) == 32
    assert first["source_path"] == source["source_path"]
    assert first["part_index"] == 7
    assert first["source_track"] == 3
    assert first["start_tick"] == 100
    assert first["end_tick"] == 700
    assert first["matcher_flags"]["source_verified"] is True
    assert all(row["source_verified"] for row in first["occurrences"])
    assert validate_phrase_source_coordinates(first, source, song) is song.parts[0]

    moved = deepcopy(candidate)
    moved["start_tick"] = 200
    assert supplement_phrase_id(source, moved) != first["phrase_id"]


def test_coordinate_validation_rejects_a_note_absent_from_source() -> None:
    source, candidate, song = _source(), _candidate(), _song()
    row = supplement_phrase_row(source, candidate, song)
    row["pitches"][2] = 63

    with pytest.raises(ValueError, match="prototype note is absent"):
        validate_phrase_source_coordinates(row, source, song)
