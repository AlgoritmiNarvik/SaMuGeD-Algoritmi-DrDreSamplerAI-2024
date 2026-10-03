from copy import deepcopy

import pytest

from samuged.closed_patterns import (
    has_exact_occurrence_evidence,
    prefer_closed_exact_extension,
    select_closed_candidates,
    select_original_candidates,
)


def _candidate(
    family_id: str,
    note_count: int,
    intervals: list[tuple[int, int]],
    *,
    score: float,
    boundary: float,
) -> dict:
    occurrences = []
    for note_index, (start, end) in enumerate(intervals):
        occurrences.append(
            {
                "start_tick": start,
                "end_tick": end,
                "note_index": note_index * note_count,
                "note_count": note_count,
                "transpose_semitones": 0,
                "similarity": 1.0,
                "edit_count": 0,
                "inserted_note_indices": [],
                "deleted_prototype_note_indices": [],
                "substituted_note_pairs": [],
                "matched_note_pairs": [[index, index] for index in range(note_count)],
                "max_timing_error_beats": 0.0,
                "max_duration_error_beats": 0.0,
                "source_verified": True,
            }
        )
    return {
        "family_id": family_id,
        "part_index": 0,
        "start_tick": intervals[0][0],
        "note_count": note_count,
        "occurrence_count": len(occurrences),
        "recurrence_score": score,
        "score_components": {
            "match_quality": 1.0,
            "support": 0.6,
            "note_length": note_count / 16,
            "boundary": boundary,
        },
        "matcher_flags": {
            "source_verified": True,
            "monotone_alignment": True,
            "fixed_transposition": True,
            "tempo_warp": False,
            "terminal_gaps_allowed": False,
            "similarity_only_acceptance": False,
        },
        "occurrences": occurrences,
    }


def test_closed_selector_replaces_shorter_exact_three_occurrence_family():
    shorter = _candidate(
        "short",
        6,
        [(200, 800), (1200, 1800), (2200, 2800)],
        score=0.82,
        boundary=0.67,
    )
    complete = _candidate(
        "complete",
        8,
        [(0, 800), (1000, 1800), (2000, 2800)],
        score=0.81,
        boundary=0.33,
    )

    assert select_original_candidates([complete, shorter], 3) == [shorter]
    assert select_closed_candidates([complete, shorter], 3) == [complete]
    assert prefer_closed_exact_extension(complete, shorter)


@pytest.mark.parametrize(
    ("mutation", "value"),
    [
        ("edit_count", 1),
        ("inserted_note_indices", [2]),
        ("deleted_prototype_note_indices", [2]),
        ("substituted_note_pairs", [[2, 2]]),
        ("max_timing_error_beats", 0.01),
        ("max_duration_error_beats", 0.01),
        ("similarity", 0.99),
    ],
)
def test_exact_evidence_rejects_any_residual(mutation, value):
    candidate = _candidate(
        "candidate",
        8,
        [(0, 800), (1000, 1800), (2000, 2800)],
        score=0.81,
        boundary=0.33,
    )
    candidate["occurrences"][1][mutation] = value

    assert not has_exact_occurrence_evidence(candidate)


def test_closed_extension_requires_three_equal_support_occurrences():
    shorter = _candidate(
        "short",
        6,
        [(200, 800), (1200, 1800)],
        score=0.82,
        boundary=0.67,
    )
    complete = _candidate(
        "complete",
        8,
        [(0, 800), (1000, 1800)],
        score=0.81,
        boundary=0.33,
    )

    assert not prefer_closed_exact_extension(complete, shorter)
    assert select_closed_candidates([complete, shorter], 3) == [shorter]


def test_closed_extension_rejects_score_drop_beyond_margin():
    shorter = _candidate(
        "short",
        6,
        [(200, 800), (1200, 1800), (2200, 2800)],
        score=0.83,
        boundary=0.67,
    )
    complete = _candidate(
        "complete",
        8,
        [(0, 800), (1000, 1800), (2000, 2800)],
        score=0.80,
        boundary=0.33,
    )

    assert not prefer_closed_exact_extension(complete, shorter)
    assert select_closed_candidates([complete, shorter], 3) == [shorter]


def test_closed_extension_rejects_noncontained_or_reused_occurrences():
    shorter = _candidate(
        "short",
        6,
        [(200, 800), (300, 700), (2200, 2800)],
        score=0.82,
        boundary=0.67,
    )
    complete = _candidate(
        "complete",
        8,
        [(0, 800), (1000, 1800), (2000, 2800)],
        score=0.81,
        boundary=0.33,
    )

    assert not prefer_closed_exact_extension(complete, shorter)


def test_exact_evidence_requires_full_diagonal_matching_pairs():
    candidate = _candidate(
        "candidate",
        8,
        [(0, 800), (1000, 1800), (2000, 2800)],
        score=0.81,
        boundary=0.33,
    )
    malformed = deepcopy(candidate)
    malformed["occurrences"][0]["matched_note_pairs"][-1] = [6, 7]

    assert has_exact_occurrence_evidence(candidate)
    assert not has_exact_occurrence_evidence(malformed)


def test_selector_validates_top_k():
    with pytest.raises(ValueError, match="positive integer"):
        select_closed_candidates([], 0)
