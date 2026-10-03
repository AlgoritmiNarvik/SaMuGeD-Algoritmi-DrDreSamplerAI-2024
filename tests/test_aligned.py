from dataclasses import asdict
import random

import pytest

from samuged.aligned import AlignedConfig, extract_aligned
from samuged.midi import MidiSong, Note, Part


PPQ = 480
PITCHES = [60, 62, 65, 64, 67, 65, 62, 60]
ONSETS = [0.0, 0.75, 1.5, 2.25, 3.0, 3.75, 4.5, 5.25]


def pattern(start, pitches=PITCHES, onsets=ONSETS, durations=None):
    durations = durations or [0.4] * len(pitches)
    return [
        Note(round((start + onset) * PPQ), round((start + onset + duration) * PPQ), pitch, 90)
        for pitch, onset, duration in zip(pitches, onsets, durations)
    ]


def song_with(second_pitches=PITCHES, second_onsets=ONSETS, *, first_start=4.0, second_start=16.0):
    context = [Note(i * 250, i * 250 + 100, 40 + i * 3, 60) for i in range(5)]
    notes = context + pattern(first_start) + pattern(second_start, second_pitches, second_onsets)
    notes += [Note(11000 + i * 300, 11100 + i * 300, 50 + i * 2, 60) for i in range(5)]
    notes.sort(key=lambda note: (note.start, note.pitch))
    return MidiSong(PPQ, [Part(0, 1, 0, 0, "melody", False, notes)], [(0, 500000)], [(0, 4, 4)], [])


def matching_phrase(result, expected):
    for phrase in result["phrases"]:
        intervals = [(row["start_tick"], row["end_tick"]) for row in phrase["occurrences"]]
        if intervals == expected:
            return phrase
    return None


def test_exact_boundaries_and_source_provenance():
    song = song_with()
    expected = [(1920, 4632), (7680, 10392)]
    result = extract_aligned(song, AlignedConfig(top_k=10))
    phrase = matching_phrase(result, expected)
    assert phrase is not None
    assert phrase["matcher_flags"] == {
        "source_verified": True,
        "monotone_alignment": True,
        "fixed_transposition": True,
        "tempo_warp": False,
        "terminal_gaps_allowed": False,
        "similarity_only_acceptance": False,
    }
    assert [row["note_count"] for row in phrase["occurrences"]] == [8, 8]
    assert all(row["source_verified"] for row in phrase["occurrences"])
    assert all(row["matched_note_pairs"][0] == [0, 0] for row in phrase["occurrences"])
    assert result["part_stats"][0]["exact_signature_hits"] > 0
    assert result["part_stats"][0]["dp_calls"] == 0


@pytest.mark.parametrize("edit", ["insert", "delete"])
def test_internal_insertion_and_deletion_recovery(edit):
    pitches, onsets = list(PITCHES), list(ONSETS)
    if edit == "insert":
        pitches.insert(4, 66)
        onsets.insert(4, 2.7)
    else:
        del pitches[4]
        del onsets[4]
    song = song_with(pitches, onsets)
    expected = [(1920, 4632), (7680, 10392)]
    phrase = matching_phrase(extract_aligned(song, AlignedConfig(top_k=10)), expected)
    assert phrase is not None
    edited = phrase["occurrences"][1]
    assert edited["note_count"] == len(pitches)
    assert edited["edit_count"] == 1
    if edit == "insert":
        assert edited["inserted_note_indices"]
    else:
        assert edited["deleted_prototype_note_indices"]


def test_transposition_and_one_substitution_use_one_fixed_shift():
    pitches = [pitch + 5 for pitch in PITCHES]
    pitches[4] += 1
    result = extract_aligned(song_with(pitches), AlignedConfig(top_k=10))
    phrase = matching_phrase(result, [(1920, 4632), (7680, 10392)])
    assert phrase is not None
    edited = phrase["occurrences"][1]
    assert edited["transpose_semitones"] == 5
    assert edited["substituted_note_pairs"] == [[4, 4]]


@pytest.mark.parametrize("index", [0, -1])
def test_boundary_pitch_substitution_keeps_varied_source_interval(index):
    pitches = [pitch + 5 for pitch in PITCHES]
    pitches[index] += 1
    expected = [(1920, 4632), (7680, 10392)]
    phrase = matching_phrase(extract_aligned(song_with(pitches), AlignedConfig(top_k=10)), expected)
    assert phrase is not None
    edited = phrase["occurrences"][1]
    expected_index = 0 if index == 0 else len(PITCHES) - 1
    assert edited["substituted_note_pairs"] == [[expected_index, expected_index]]
    assert (edited["start_tick"], edited["end_tick"]) == expected[1]


def test_repeated_pitch_alignment_uses_rhythm_admissible_traceback():
    left_pitches = [60, 60, 62, 64, 65, 67]
    left_onsets = [0.0, 0.8, 1.6, 2.4, 3.2, 4.0]
    right_pitches = [60, 60, 60, 62, 64, 65, 67]
    right_onsets = [0.0, 0.35, 0.8, 1.6, 2.4, 3.2, 4.0]
    first = pattern(4.0, left_pitches, left_onsets)
    second = pattern(16.0, right_pitches, right_onsets)
    notes = sorted(first + second, key=lambda note: (note.start, note.pitch))
    song = MidiSong(PPQ, [Part(0, 1, 0, 0, "melody", False, notes)], [(0, 500000)], [(0, 4, 4)], [])
    expected = [(first[0].start, first[-1].end), (second[0].start, second[-1].end)]
    phrase = matching_phrase(extract_aligned(song, AlignedConfig(top_k=10)), expected)
    assert phrase is not None
    edited = phrase["occurrences"][1]
    assert edited["edit_count"] == 1
    assert edited["inserted_note_indices"] in ([1], [2])
    assert edited["max_timing_error_beats"] == 0.0


def test_scaled_rhythm_and_variable_pitch_shift_are_hard_negatives():
    scaled = [onset * 1.45 for onset in ONSETS]
    assert not extract_aligned(song_with(PITCHES, scaled), AlignedConfig(top_k=10))["phrases"]
    shifts = [0, 2, -2, 4, -4, 1, -1, 3]
    adversarial = [pitch + shift for pitch, shift in zip(PITCHES, shifts)]
    assert not extract_aligned(song_with(adversarial), AlignedConfig(top_k=10))["phrases"]


def test_order_invariance_no_mutation_and_visible_limits():
    song = song_with()
    before = asdict(song)
    first = extract_aligned(song, AlignedConfig(top_k=10))
    assert asdict(song) == before
    random.Random(5).shuffle(song.parts[0].notes)
    second = extract_aligned(song, AlignedConfig(top_k=10))
    assert first == second
    limited = extract_aligned(song, AlignedConfig(max_windows=2))
    assert limited["search_limited"]
    assert limited["part_stats"][0]["window_limit_reached"]


def test_drum_empty_constant_and_bad_config():
    empty = MidiSong(PPQ, [Part(0, 1, 0, 0, "empty", False, [])], [(0, 500000)], [(0, 4, 4)], [])
    assert not extract_aligned(empty)["phrases"]
    constant = [Note(i * PPQ, i * PPQ + 200, 60, 80) for i in range(40)]
    empty.parts[0].notes = constant
    assert not extract_aligned(empty)["phrases"]
    empty.parts[0].is_drum = True
    assert not extract_aligned(empty)["phrases"]
    for values in (
        {"min_notes": 33, "max_notes": 32},
        {"max_edit_fraction": 0.2},
        {"max_windows": 0},
        {"max_seed_pairs": 0},
        {"min_seed_support": 0},
        {"timing_tolerance": float("nan")},
    ):
        with pytest.raises(ValueError):
            AlignedConfig(**values)
    with pytest.raises(TypeError):
        extract_aligned(song_with(), object())
