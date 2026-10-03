from dataclasses import replace

import pytest

from samuged.closed_patterns import select_closed_candidates
from samuged.midi import MidiSong, Note, Part
from samuged.part_ranking import (
    PRESET_CONFIGS,
    PartPriorConfig,
    part_structure_features,
    preset_by_name,
    select_part_ranked_closed_candidates,
    song_part_scores,
)
from scripts.evaluate_part_ranking import _blind_song, fit_preset, summarize_split


def notes(pitches, *, step=240, duration=180, start=0):
    return [
        Note(start + index * step, start + index * step + duration, pitch, 90)
        for index, pitch in enumerate(pitches)
    ]


def part(index, source_notes, *, name="unknown", channel=0, program=0, track=1):
    return Part(index, track, channel, program, name, False, source_notes)


def song(*parts):
    return MidiSong(480, list(parts), [(0, 500_000)], [(0, 4, 4)], [])


def candidate(family, part_index, score, start):
    return {
        "family_id": family,
        "part_index": part_index,
        "note_count": 8,
        "start_tick": start,
        "end_tick": start + 960,
        "recurrence_score": score,
        "score_components": {"boundary": 0.5},
        "occurrence_count": 2,
        "occurrences": [
            {"start_tick": start, "end_tick": start + 960},
            {"start_tick": start + 1920, "end_tick": start + 2880},
        ],
    }


def test_features_ignore_track_role_metadata():
    source = notes([60, 62, 64, 65, 67, 69, 71, 72])
    left = part(4, source, name="MELODY", channel=0, program=1, track=3)
    right = part(4, source, name="PIANO", channel=11, program=99, track=81)
    assert part_structure_features(left, 480) == part_structure_features(right, 480)
    config = preset_by_name("balanced")
    assert song_part_scores(song(left), config) == song_part_scores(song(right), config)


def test_blind_song_removes_role_bearing_metadata_but_preserves_notes():
    source = part(4, notes([60, 62, 64]), name="MELODY", channel=7, program=42, track=9)
    blinded = _blind_song(song(source))
    assert blinded.parts[0].name == ""
    assert blinded.parts[0].channel == blinded.parts[0].program == blinded.parts[0].track == 0
    assert blinded.parts[0].index == 4
    assert blinded.parts[0].notes is source.notes


def test_low_monophonic_line_beats_high_chord_accompaniment():
    low = part(0, notes([43, 45, 47, 48, 50, 52, 50, 48]))
    chords = []
    for index in range(8):
        for pitch in (72, 76, 79):
            chords.append(Note(index * 240, index * 240 + 420, pitch, 80))
    high = part(1, chords)
    scores, _ = song_part_scores(song(low, high), preset_by_name("structure"))
    assert scores[0] > scores[1]


def test_dense_melody_beats_sparse_bridge_without_register_cue():
    melody = part(0, notes([64, 65, 67, 69, 67, 65, 64, 62], step=240))
    bridge = part(1, notes([64, 67, 65, 69], step=1920))
    scores, _ = song_part_scores(song(melody, bridge), preset_by_name("structure"))
    assert scores[0] > scores[1]


def test_polyphonic_representation_is_penalized():
    mono = part(0, notes([60, 62, 64, 65, 67, 69]))
    poly = part(
        1,
        [note for index in range(6) for note in (
            Note(index * 240, index * 240 + 360, 60 + index, 90),
            Note(index * 240, index * 240 + 360, 48 + index, 75),
        )],
    )
    scores, features = song_part_scores(song(mono, poly), preset_by_name("monophony"))
    assert features[0]["onset_monophony"] > features[1]["onset_monophony"]
    assert scores[0] > scores[1]


def test_voice_independence_matches_brute_force_overlap_counts():
    source = [
        Note(0, 240, 60, 90),
        Note(0, 480, 64, 80),
        Note(20, 300, 67, 70),  # merged with the tick-zero onset group
        Note(240, 480, 62, 90),  # starts exactly when the first note ends
        Note(480, 720, 65, 90),
    ]
    features = part_structure_features(part(0, source), 480)
    group_starts = (0, 240, 480)
    active = [sum(note.start <= tick < note.end for note in source) for tick in group_starts]
    brute = 1 / (1 + sum(max(0, count - 1) for count in active) / len(active))
    assert features["voice_independence"] == pytest.approx(brute, abs=1e-8)


def test_single_part_zero_prior_matches_closed_selector():
    source_song = song(part(0, notes([60, 62, 64, 65, 67, 69, 71, 72])))
    candidates = [
        candidate("a", 0, 0.9, 0),
        candidate("b", 0, 0.8, 4000),
        candidate("c", 0, 0.7, 8000),
    ]
    selected, evidence = select_part_ranked_closed_candidates(
        candidates, source_song, preset_by_name("none"), top_k=2
    )
    assert selected == select_closed_candidates(candidates, 2)
    assert evidence["candidate_count"] == 3
    assert evidence["reranks_full_shortlist"] is True


def test_zero_prior_matches_closed_selector_across_parts():
    source_song = song(
        part(0, notes([60, 62, 64, 65, 67, 69, 71, 72])),
        part(1, notes([48, 52, 55, 57, 60, 64, 67, 69])),
    )
    candidates = [
        candidate("a", 1, 0.91, 0),
        candidate("b", 0, 0.90, 4000),
        candidate("c", 1, 0.89, 8000),
    ]
    selected, _ = select_part_ranked_closed_candidates(
        candidates, source_song, preset_by_name("none"), top_k=3
    )
    assert selected == select_closed_candidates(candidates, 3)


def test_prior_reranks_full_shortlist_without_mutating_scores():
    melody = part(0, notes([60, 62, 64, 65, 67, 69, 71, 72]))
    chords = []
    for index in range(8):
        for pitch in (48, 52, 55):
            chords.append(Note(index * 240, index * 240 + 420, pitch, 80))
    accompaniment = part(1, chords)
    candidates = [
        candidate("accompaniment", 1, 0.91, 0),
        candidate("melody", 0, 0.89, 5000),
    ]
    config = replace(preset_by_name("structure"), strength=0.20)
    selected, _ = select_part_ranked_closed_candidates(
        candidates, song(melody, accompaniment), config, top_k=1
    )
    assert selected[0]["family_id"] == "melody"
    assert selected[0]["recurrence_score"] == 0.89
    assert candidates[0]["recurrence_score"] == 0.91


def test_invalid_config_and_candidate_are_rejected():
    with pytest.raises(ValueError, match="sum to one"):
        PartPriorConfig("bad", 0.1, 1, 1, 0, 0, 0, 0)
    source_song = song(part(0, notes([60, 62, 64, 65, 67, 69])))
    bad = candidate("bad", 0, float("nan"), 0)
    with pytest.raises(ValueError, match="finite"):
        select_part_ranked_closed_candidates(
            [bad], source_song, preset_by_name("structure"), top_k=1
        )


def test_development_fit_uses_declared_tie_break_order():
    selection = lambda family, index: {
        "family_ids": [family], "part_indices": [index], "phrases": []
    }
    priors = {
        config.name: selection(config.name, 0 if config.name == "monophony_weak" else 1)
        for config in PRESET_CONFIGS
    }
    row = {
        "role_map": {0: "MELODY", 1: "PIANO", 2: "BRIDGE"},
        "baseline": selection("baseline", 1),
        "priors": priors,
    }
    selected, metrics = fit_preset([row])
    assert selected == "monophony_weak"
    assert len(metrics) == 8


def test_split_summary_reports_paired_role_agreement_change():
    base = {
        "split": "heldout",
        "selection_changed": True,
        "top1_part_changed": True,
        "melody_candidate_available": True,
        "search_limited": False,
        "curation_truncated": False,
        "candidate_count": 4,
        "detection_elapsed_seconds": 1.0,
        "baseline": {"selection_elapsed_seconds": 0.01},
        "selected_prior": {"selection_elapsed_seconds": 0.02},
        "baseline_labels": {"top1_melody": False, "top3_melody": True},
        "prior_labels": {"top1_melody": True, "top3_melody": True},
    }
    summary = summarize_split([base], "heldout")
    assert summary["baseline"]["top1_melody_rate"] == 0
    assert summary["part_prior"]["top1_melody_rate"] == 1
    assert summary["paired_top1_difference"]["difference"] == 1
