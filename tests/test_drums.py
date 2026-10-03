from dataclasses import asdict, replace
import random

import pytest

from samuged.drums import DrumConfig, drum_part, extract_drums
from samuged.midi import MidiSong, Note, Part, export_phrase, load_midi


BASE_PATTERN = (
    (0.0, 36),
    (0.0, 42),
    (0.5, 42),
    (1.0, 38),
    (1.0, 42),
    (1.5, 42),
    (2.0, 36),
    (2.0, 42),
    (2.5, 42),
    (3.0, 38),
    (3.0, 42),
    (3.5, 42),
)


def _notes_for_bars(
    bars: int,
    *,
    ppq: int = 480,
    bar_beats: float = 4.0,
    pattern=BASE_PATTERN,
    jitter_bar: int | None = None,
    delete: tuple[int, int] | None = None,
    change: tuple[int, tuple[int, ...]] | None = None,
) -> list[Note]:
    notes = []
    for bar in range(bars):
        changed = set(change[1]) if change is not None and change[0] == bar else set()
        for hit_index, (onset, pitch) in enumerate(pattern):
            if delete == (bar, hit_index):
                continue
            if hit_index in changed:
                pitch += 1
            offset = 0.04 if jitter_bar == bar else 0.0
            start = round((bar * bar_beats + onset + offset) * ppq)
            notes.append(Note(start, start + max(1, round(0.08 * ppq)), pitch, 90))
    return notes


def _song(
    notes: list[Note],
    *,
    ppq: int = 480,
    meters: list[tuple[int, int, int]] | None = None,
    program: int = 0,
) -> MidiSong:
    part = Part(7, 3, 9, program, "kit", True, notes)
    return MidiSong(
        ppq,
        [part],
        [(0, 500_000)],
        meters or [(0, 4, 4)],
        [],
    )


def test_combines_drums_preserves_simultaneous_hits_and_merges_duplicates() -> None:
    notes = _notes_for_bars(2)
    duplicate = [Note(n.start, n.end + 2, n.pitch, 100) for n in notes]
    song = MidiSong(
        480,
        [
            Part(5, 4, 9, 0, "main", True, list(reversed(notes))),
            Part(2, 1, 9, 8, "duplicate", True, duplicate),
            Part(9, 7, 0, 12, "pitched", False, [Note(0, 100, 60, 70)]),
        ],
        [(0, 500_000)],
        [(0, 4, 4)],
        [],
    )

    combined = drum_part(song)
    result = extract_drums(song, DrumConfig(bar_counts=(1,), mode="exact"))
    phrase = result["phrases"][0]

    assert (combined.index, combined.track, combined.channel, combined.is_drum) == (
        0,
        0,
        9,
        True,
    )
    assert len(combined.notes) == len(notes)
    assert combined.notes[0:2] == [
        Note(0, notes[0].end + 2, 36, 100),
        Note(0, notes[1].end + 2, 42, 100),
    ]
    assert "source_part_indices=[2,5]" in combined.name
    assert phrase["part_index"] == -1
    assert phrase["source_part_indices"] == [2, 5]
    assert phrase["kit_programs"] == [0, 8]
    assert phrase["onsets_beats"][:2] == [0.0, 0.0]
    assert phrase["pitches"][:2] == [36, 42]
    assert result["stats"]["duplicate_hits_removed"] == len(notes)


def test_exact_repeats_use_drum_ids_without_transposition() -> None:
    song = _song(_notes_for_bars(3))
    result = extract_drums(song, DrumConfig(bar_counts=(1,), mode="exact"))
    phrase = result["phrases"][0]

    assert phrase["occurrence_count"] == 3
    assert [item["start_tick"] for item in phrase["occurrences"]] == [0, 1920, 3840]
    assert {item["transpose_semitones"] for item in phrase["occurrences"]} == {0}
    assert phrase["note_count"] == len(BASE_PATTERN)

    shifted = []
    for bar in range(2):
        for onset, pitch in BASE_PATTERN:
            start = round((bar * 4 + onset) * 480)
            shifted.append(Note(start, start + 30, pitch + bar, 90))
    assert not extract_drums(
        _song(shifted), DrumConfig(bar_counts=(1,), mode="tolerant")
    )["phrases"]


def test_tolerant_mode_accepts_one_missing_hit_but_rejects_instrument_changes() -> None:
    varied = _song(
        _notes_for_bars(2, jitter_bar=1, delete=(1, 2))
    )
    tolerant = extract_drums(
        varied, DrumConfig(bar_counts=(1,), mode="tolerant")
    )
    assert tolerant["phrases"]
    assert tolerant["phrases"][0]["occurrences"][1]["similarity"] < 1
    assert not extract_drums(
        varied, DrumConfig(bar_counts=(1,), mode="exact")
    )["phrases"]

    mismatched = _song(
        _notes_for_bars(2, change=(1, (0, 3)))
    )
    assert not extract_drums(
        mismatched, DrumConfig(bar_counts=(1,), mode="tolerant")
    )["phrases"]


def _meter_pattern(bar_start: float, bar_beats: float, ppq: int) -> list[Note]:
    notes = []
    for index in range(10):
        onset = bar_start + index * (bar_beats / 10)
        pitch = 36 if index % 3 == 0 else 42
        start = round(onset * ppq)
        notes.append(Note(start, start + 20, pitch, 80 + index))
    return notes


def test_non_four_four_windows_reset_at_meter_changes_without_crossing() -> None:
    ppq = 480
    change_tick = 6 * ppq
    notes = []
    for start in (0.0, 3.0):
        notes.extend(_meter_pattern(start, 3.0, ppq))
    for start in (6.0, 11.0):
        notes.extend(_meter_pattern(start, 5.0, ppq))
    song = _song(
        notes,
        ppq=ppq,
        meters=[(0, 6, 8), (change_tick, 5, 4)],
    )

    phrases = extract_drums(
        song, DrumConfig(bar_counts=(1,), mode="exact", top_k=3)
    )["phrases"]

    assert {phrase["duration_beats"] for phrase in phrases} == {3.0, 5.0}
    assert all(
        not (item["start_tick"] < change_tick < item["end_tick"])
        for phrase in phrases
        for item in phrase["occurrences"]
    )
    assert {(phrase["meter_numerator"], phrase["meter_denominator"]) for phrase in phrases} == {
        (6, 8),
        (5, 4),
    }


def test_empty_and_drum_only_inputs_do_not_force_output() -> None:
    empty = MidiSong(480, [], [(0, 500_000)], [(0, 4, 4)], [])
    assert drum_part(empty).notes == []
    assert extract_drums(empty)["phrases"] == []

    one_bar = _song(_notes_for_bars(1))
    assert extract_drums(
        one_bar, DrumConfig(bar_counts=(1,), mode="exact")
    )["phrases"] == []

    drum_only = _song(_notes_for_bars(2))
    assert extract_drums(
        drum_only, DrumConfig(bar_counts=(1,), mode="exact")
    )["phrases"]


def test_aggregate_part_and_phrase_bounds_are_exporter_compatible(tmp_path) -> None:
    song = _song(_notes_for_bars(2))
    phrase = extract_drums(
        song, DrumConfig(bar_counts=(1,), mode="exact")
    )["phrases"][0]
    ensemble = drum_part(song)
    notes = [
        note
        for note in ensemble.notes
        if phrase["start_tick"] <= note.start < phrase["end_tick"]
    ]
    path = tmp_path / "drum-pattern.mid"

    export_phrase(
        song,
        ensemble,
        notes,
        phrase["start_tick"],
        phrase["end_tick"],
        path,
    )
    exported = load_midi(path)

    assert exported.parts[0].channel == 9
    assert len(exported.parts[0].notes) == phrase["note_count"]
    assert [note.start for note in exported.parts[0].notes[:2]] == [0, 0]


def test_results_are_deterministic_under_part_and_note_order() -> None:
    first = _notes_for_bars(4)
    second = [Note(n.start, n.end, n.pitch, n.velocity) for n in first]
    song = MidiSong(
        480,
        [
            Part(10, 2, 9, 0, "a", True, first),
            Part(3, 5, 9, 0, "b", True, second),
        ],
        [(0, 500_000)],
        [(0, 4, 4)],
        [],
    )
    before = asdict(song)
    cfg = DrumConfig(bar_counts=(1, 2), mode="tolerant")
    left = extract_drums(song, cfg)
    assert asdict(song) == before

    random.Random(42).shuffle(song.parts)
    for part in song.parts:
        random.Random(part.index).shuffle(part.notes)
    right = extract_drums(song, cfg)
    assert left == right


def test_resource_limits_and_seed_saturation_are_visible() -> None:
    song = _song(_notes_for_bars(12))
    limited = extract_drums(
        song,
        DrumConfig(
            bar_counts=(1,),
            mode="exact",
            max_windows=2,
        ),
    )
    assert limited["stats"]["window_limit_reached"]
    assert limited["stats"]["eligible_windows"] == 2
    assert limited["stats"]["search_limited"]

    hit_limited = extract_drums(
        song,
        DrumConfig(bar_counts=(1,), max_hits=5),
    )
    assert hit_limited["stats"]["hit_limit_reached"]
    assert not hit_limited["phrases"]

    changing = []
    for bar in range(8):
        shift = (bar % 4) * 0.18
        pattern = tuple(
            ((onset + shift * (index % 2)) % 4, pitch)
            for index, (onset, pitch) in enumerate(BASE_PATTERN)
        )
        changing.extend(_notes_for_bars(1, pattern=pattern))
        for note in changing[-len(pattern):]:
            note.start += bar * 4 * 480
            note.end += bar * 4 * 480
    saturated = extract_drums(
        _song(changing),
        DrumConfig(
            bar_counts=(1,),
            mode="tolerant",
            max_bucket=1,
            max_comparisons=3,
        ),
    )
    assert saturated["stats"]["saturated_seed_buckets"] > 0
    assert saturated["stats"]["search_limited"]
    assert saturated["stats"]["comparisons"] <= 3


def test_window_attempt_limit_bounds_sparse_pathological_meter() -> None:
    distant = 10**12
    song = _song(
        [
            Note(distant + index, distant + index + 1, 36 + index % 2, 80)
            for index in range(8)
        ],
        meters=[(0, 1, 1 << 30)],
    )

    result = extract_drums(
        song,
        DrumConfig(bar_counts=(1, 2, 4), mode="exact", max_windows=7),
    )

    assert not result["phrases"]
    assert result["stats"]["window_attempts"] == 7
    assert result["stats"]["windows_considered"] <= 7
    assert result["stats"]["window_limit_reached"]
    assert result["stats"]["search_limited"]


def test_oversized_windows_are_skipped_and_reported() -> None:
    result = extract_drums(
        _song(_notes_for_bars(2)),
        DrumConfig(
            bar_counts=(1,),
            mode="exact",
            max_window_hits=10,
        ),
    )

    assert not result["phrases"]
    assert result["stats"]["oversized_windows"] == 2
    assert result["stats"]["search_limited"]


def test_copied_subbars_do_not_outrank_the_one_bar_primitive() -> None:
    result = extract_drums(
        _song(_notes_for_bars(8)),
        DrumConfig(bar_counts=(1, 4), mode="exact", top_k=3),
    )

    phrase = result["phrases"][0]
    assert phrase["bar_count"] == 1
    assert phrase["score_components"]["primitive_bar_period"] == 1.0
    assert phrase["score_components"]["bar_variation"] == 1.0
    assert result["stats"]["raw_candidate_count"] >= 2
    assert result["stats"]["diversity_comparisons"] >= 1
    assert result["stats"]["diversity_pruned"] >= 1
    assert result["stats"]["selected_count"] == len(result["phrases"])

    varied_notes = []
    for bar in range(8):
        variant = bar % 4
        for hit_index, (onset, pitch) in enumerate(BASE_PATTERN):
            if hit_index == 0:
                pitch += variant
            start = round((bar * 4 + onset) * 480)
            varied_notes.append(Note(start, start + 30, pitch, 90))
    varied = extract_drums(
        _song(varied_notes),
        DrumConfig(bar_counts=(1, 4), mode="exact", top_k=3),
    )["phrases"][0]
    assert varied["bar_count"] == 4
    assert varied["score_components"]["primitive_bar_period"] == 4.0
    assert varied["score_components"]["bar_variation"] == 1.0


def test_bad_config_and_mode_fail_before_work() -> None:
    for values in (
        {"mode": "transposed"},
        {"bar_counts": (3,)},
        {"bar_counts": (1, 1)},
        {"timing_tolerance_beats": float("nan")},
        {"hit_error_fraction": 0.11},
        {"top_k": 0},
    ):
        with pytest.raises(ValueError):
            DrumConfig(**values)
    with pytest.raises(ValueError):
        extract_drums(_song(_notes_for_bars(2)), mode="transposed")


def test_merged_drum_gates_do_not_create_crossing_note_offs(tmp_path):
    import mido
    from samuged.midi import load_midi, export_phrase
    song=MidiSong(480,[
        Part(0,1,9,0,'kick long',True,[Note(0,400,36,56)]),
        Part(1,2,9,0,'kick short',True,[Note(100,200,36,109)])
    ],[(0,500000)],[(0,4,4)],[])
    ensemble=drum_part(song)
    assert [(n.start,n.end) for n in ensemble.notes]==[(0,100),(100,200)]
    assert song.parts[0].notes[0].end==400
    output=tmp_path/'gates.mid'
    export_phrase(song,ensemble,ensemble.notes,0,480,output)
    actual=load_midi(output)
    assert [(n.start,n.end,n.velocity) for p in actual.parts for n in p.notes]==[(0,100,56),(100,200,109)]
