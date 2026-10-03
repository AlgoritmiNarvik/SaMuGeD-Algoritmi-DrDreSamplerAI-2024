from types import SimpleNamespace

import pytest

from samuged.midi import MidiSong, Note, Part
from scripts.evaluate_selection_external import (
    METHODS,
    _validate_theme_representation,
    assert_single_part_selection_equivalence,
    validate_method_coverage,
)


def _theme_case(name="canonical_melody"):
    song = MidiSong(
        480,
        [Part(0, 0, 0, 0, name, False, [Note(0, 240, 60, 90)])],
        [(0, 500_000)],
        [(0, 4, 4)],
        [],
    )
    # Labels deliberately remain outside the detector input object.
    return SimpleNamespace(song_id="065", song=song, labels={"0": {0}})


def test_theme_detector_representation_strips_annotation_identity():
    case = _theme_case()
    _validate_theme_representation(case)
    assert not hasattr(case.song, "labels")
    assert case.labels == {"0": {0}}

    with pytest.raises(ValueError, match="retains annotation or instrument identity"):
        _validate_theme_representation(_theme_case("Annotator_0_theme"))


def test_selected_method_coverage_requires_every_case_method_once():
    case_ids = ["a", "b"]
    rows = [
        {"case_id": case_id, "method": method}
        for case_id in case_ids
        for method in METHODS
    ]
    validate_method_coverage(rows, case_ids)

    with pytest.raises(ValueError, match="coverage"):
        validate_method_coverage(rows[:-1], case_ids)
    with pytest.raises(ValueError, match="coverage"):
        validate_method_coverage(rows + [rows[0]], case_ids)


def test_single_part_closed_and_melody_payloads_must_match_exactly():
    phrase = {
        "family_id": "a" * 64,
        "part_index": 0,
        "start_tick": 0,
        "end_tick": 960,
        "occurrences": [
            {"start_tick": 0, "end_tick": 960},
            {"start_tick": 1920, "end_tick": 2880},
        ],
    }
    outputs = {
        "aligned_closed": {"phrases": [phrase]},
        "aligned_melody": {"phrases": [dict(phrase)]},
    }
    assert_single_part_selection_equivalence("065", outputs)

    outputs["aligned_melody"]["phrases"][0]["end_tick"] = 961
    with pytest.raises(ValueError, match="single-Part"):
        assert_single_part_selection_equivalence("065", outputs)
