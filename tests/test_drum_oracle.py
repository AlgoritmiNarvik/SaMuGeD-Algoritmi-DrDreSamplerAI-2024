from fractions import Fraction

from samuged.drum_oracle import (
    OracleWindow,
    _reported_pairs,
    clip_to_first_bars,
    enumerate_admissible_pairs,
    enumerate_windows,
    maximum_pitch_matches,
    verify_pair,
)
from samuged.midi import MidiSong, Note, Part


def _note(start: int, pitch: int) -> Note:
    return Note(start, start + 2, pitch, 90)


def test_maximum_cardinality_avoids_closest_strike_greedy_failure():
    # A closest-first rule consumes right tick 10 for left tick 10 and then
    # cannot match left tick 30. Ordered maximum matching uses 10->0, 30->10.
    left = [_note(10, 36), _note(30, 36)]
    right = [_note(0, 36), _note(10, 36)]

    assert maximum_pitch_matches(
        left,
        right,
        left_start=0,
        right_start=0,
        ppq=100,
        tolerance_beats=Fraction(21, 100),
    ) == 2


def test_simultaneous_equal_pitch_strikes_remain_distinct_vertices():
    left = [_note(0, 36), _note(0, 36), _note(0, 38), _note(10, 42)]
    right = [_note(0, 36), _note(0, 36), _note(0, 38), _note(11, 42)]

    assert maximum_pitch_matches(
        left, right, left_start=0, right_start=0, ppq=120
    ) == 4


def test_meter_change_resets_bar_origin_and_windows_do_not_cross_boundary():
    ppq = 120
    notes = []
    for start, end in ((0, 360), (360, 720), (720, 1200), (1200, 1680)):
        step = (end - start) // 8
        notes.extend(_note(start + index * step, 36 if index % 2 else 42)
                     for index in range(8))
    song = MidiSong(
        ppq,
        [Part(0, 0, 9, 0, "kit", True, notes)],
        [(0, 500_000)],
        [(0, 3, 4), (720, 4, 4)],
        [],
    )

    windows = enumerate_windows(song)

    assert {(window.start, window.end, window.bar_count) for window in windows} >= {
        (0, 360, 1),
        (360, 720, 1),
        (0, 720, 2),
        (720, 1200, 1),
        (1200, 1680, 1),
        (720, 1680, 2),
    }
    assert all(window.end <= 720 or window.start >= 720 for window in windows)


def test_real_clip_preserves_parser_diagnostics_and_clips_note_gates():
    song = MidiSong(
        100,
        [Part(0, 0, 9, 0, "kit", True, [_note(0, 36), Note(390, 450, 42, 90),
                                          _note(401, 38)])],
        [(0, 500_000)],
        [(0, 4, 4)],
        ["source warning"],
        [{"repair": "example"}],
    )

    clipped = clip_to_first_bars(song, 1)

    assert [(note.start, note.end) for note in clipped.parts[0].notes] == [(0, 2), (390, 400)]
    assert clipped.warnings == ["source warning"]
    assert clipped.metadata_repairs == [{"repair": "example"}]


def test_pair_rule_uses_total_unmatched_hits_and_nonoverlap():
    first_notes = tuple(_note(index * 10, 36 if index % 2 else 42) for index in range(10))
    second_notes = tuple(_note(100 + index * 10, 36 if index % 2 else 42) for index in range(9))
    first = OracleWindow(0, 100, 1, 4, 4, first_notes)
    second = OracleWindow(100, 200, 1, 4, 4, second_notes)

    match = verify_pair(first, second, 100)
    assert match.admissible
    assert match.matched_hits == 9
    assert match.total_edits == match.allowed_edits == 1

    overlapping = OracleWindow(50, 150, 1, 4, 4, second_notes)
    assert verify_pair(first, overlapping, 100).reason == "overlap"


def test_exhaustive_pairs_keep_simultaneous_hit_windows():
    notes = tuple(
        [_note(0, 36), _note(0, 38)]
        + [_note(index * 10, 42 if index % 2 else 46) for index in range(1, 7)]
    )
    shifted = tuple(_note(note.start + 100, note.pitch) for note in notes)
    left = OracleWindow(0, 100, 1, 4, 4, notes)
    right = OracleWindow(100, 200, 1, 4, 4, shifted)

    pairs, stats = enumerate_admissible_pairs([left, right], 100)

    assert len(pairs) == 1
    assert stats == {
        "pair_comparisons": 1,
        "pair_budget": 250_000,
        "pair_budget_reached": False,
    }


def test_reported_family_pairs_separate_direct_prototype_edges():
    phrase = {
        "bar_count": 1,
        "meter_numerator": 4,
        "meter_denominator": 4,
        "start_tick": 0,
        "end_tick": 100,
        "occurrences": [
            {"start_tick": 0, "end_tick": 100},
            {"start_tick": 100, "end_tick": 200},
            {"start_tick": 200, "end_tick": 300},
        ],
    }

    family_pairs, verified_edges, instances = _reported_pairs([phrase])

    assert instances == 3
    assert len(family_pairs) == 3
    assert len(verified_edges) == 2
