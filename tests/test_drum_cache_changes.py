import pytest

from samuged.drum_oracle import enumerate_windows
from samuged.drums import DrumConfig, extract_drums
from samuged.midi import MidiSong, Note, Part
from scripts.audit_drum_cache_changes import (
    _semantic_difference,
    _validate_phrase,
)


def _synthetic_song() -> MidiSong:
    notes = []
    pattern = ((0, 36), (0, 42), (12, 42), (24, 36),
               (24, 42), (36, 42), (48, 36), (60, 42))
    for bar in range(4):
        for offset, pitch in pattern:
            start = bar * 96 + offset
            notes.append(Note(start, start + 6, pitch, 100))
    return MidiSong(
        24,
        [Part(0, 0, 9, 0, "drums", True, notes)],
        [],
        [(0, 4, 4)],
        [],
        [],
    )


def _phrase_fixture() -> tuple[dict, dict, int]:
    song = _synthetic_song()
    result = extract_drums(song, DrumConfig(mode="exact", max_comparisons=10_000))
    assert result["phrases"]
    phrase = result["phrases"][0]
    windows = {window.identity: window for window in enumerate_windows(song)}
    metadata = ([0], [0], [0])
    return phrase, {"windows": windows, "metadata": metadata}, song.ticks_per_beat


def test_changed_phrase_edges_match_source_oracle_and_canonical_arrays():
    phrase, context, ppq = _phrase_fixture()
    result = _validate_phrase(
        phrase, context["windows"], ppq, context["metadata"]
    )
    assert result["direct_edge_count"] == phrase["occurrence_count"] - 1
    assert all(edge["oracle_reason"] == "admissible" for edge in result["direct_edges"])


def test_changed_phrase_rejects_occurrence_outside_grid():
    phrase, context, ppq = _phrase_fixture()
    tampered = {**phrase, "occurrences": [dict(item) for item in phrase["occurrences"]]}
    tampered["occurrences"][1]["start_tick"] += 1
    with pytest.raises(ValueError, match="not oracle windows"):
        _validate_phrase(tampered, context["windows"], ppq, context["metadata"])


def test_changed_phrase_rejects_canonical_note_array_tampering():
    phrase, context, ppq = _phrase_fixture()
    tampered = {**phrase, "pitches": list(phrase["pitches"])}
    tampered["pitches"][0] += 1
    with pytest.raises(ValueError, match="canonical pitches mismatch"):
        _validate_phrase(tampered, context["windows"], ppq, context["metadata"])


def test_semantic_difference_reports_replacements_support_and_score_delta():
    baseline = [
        {"family_id": "keep", "start_tick": 0, "end_tick": 96,
         "bar_count": 1, "note_count": 8, "occurrence_count": 3,
         "occurrences": [{"start_tick": 0, "end_tick": 96},
                         {"start_tick": 96, "end_tick": 192},
                         {"start_tick": 192, "end_tick": 288}],
         "recurrence_score": 0.6},
        {"family_id": "gone", "start_tick": 10, "end_tick": 106,
         "bar_count": 1, "note_count": 8, "occurrence_count": 2,
         "occurrences": [{"start_tick": 10, "end_tick": 106},
                         {"start_tick": 202, "end_tick": 298}],
         "recurrence_score": 0.5},
    ]
    candidate = [
        {**baseline[0], "occurrence_count": 4,
         "occurrences": baseline[0]["occurrences"] + [{"start_tick": 288, "end_tick": 384}],
         "recurrence_score": 0.7},
        {"family_id": "new", "start_tick": 20, "end_tick": 116,
         "bar_count": 1, "note_count": 8, "occurrence_count": 2,
         "occurrences": [{"start_tick": 20, "end_tick": 116},
                         {"start_tick": 212, "end_tick": 308}],
         "recurrence_score": 0.4},
    ]
    difference = _semantic_difference(baseline, candidate)
    assert difference["baseline_disappeared"][0]["family_id"] == "gone"
    assert difference["candidate_new"][0]["family_id"] == "new"
    keep = next(item for item in difference["occurrence_support"] if item["family_id"] == "keep")
    assert keep["gained_occurrences"] == [[288, 384]]
    assert keep["score_delta"] == pytest.approx(0.1)
    assert difference["rank_replacements"]
