import json
from unittest.mock import patch

import pytest

from samuged.drum_stress import (
    CONDITIONS,
    aggregate_results,
    frozen_design,
    generate_cohort,
    run_stress,
    score_case,
)
from samuged.drums import DrumConfig, drum_part, extract_drums
from samuged.experiment import verify_completed_experiment


@pytest.fixture(scope="module")
def cohort():
    return generate_cohort(40)


def test_cohort_is_frozen_varied_and_split_disjoint(cohort) -> None:
    cases, audit = cohort

    assert len(cases) == 40 * len(CONDITIONS)
    assert audit["exact_unique_arrangements"] == len(cases)
    assert audit["beat_unique_arrangements"] == len(cases)
    assert audit["cross_split_exact_overlap"] == 0
    assert audit["cross_split_beat_overlap"] == 0
    assert audit["rejected_duplicate_attempts"] >= 0
    assert set(audit["rejected_duplicate_attempts_by_reason"]) == {
        "phrase_design",
        "exact_arrangement",
        "beat_arrangement",
    }
    assert set(audit["distinct_phrase_designs_per_condition"]) == set(CONDITIONS)
    assert set(audit["distinct_phrase_designs_per_condition"].values()) == {40}
    assert sum(
        count
        for split in audit["rejected_duplicates"].values()
        for condition in split.values()
        for count in condition.values()
    ) >= 0

    development_exact = {
        case.exact_arrangement_sha256
        for case in cases
        if case.split == "development"
    }
    test_exact = {
        case.exact_arrangement_sha256 for case in cases if case.split == "test"
    }
    development_beat = {
        case.beat_arrangement_sha256
        for case in cases
        if case.split == "development"
    }
    test_beat = {
        case.beat_arrangement_sha256 for case in cases if case.split == "test"
    }
    assert development_exact.isdisjoint(test_exact)
    assert development_beat.isdisjoint(test_beat)
    assert frozen_design(40)["minimum_distinct_phrase_designs_per_condition"] == 20


def test_cases_are_long_and_truth_is_generator_geometry(cohort) -> None:
    cases, _audit = cohort

    assert all(case.occurrence_count in {3, 4, 5} for case in cases)
    assert all(
        len(case.truth_intervals) == case.occurrence_count
        for case in cases
        if case.positive
    )
    assert all(not case.truth_intervals for case in cases if not case.positive)
    assert min(sum(len(part.notes) for part in case.song.parts) for case in cases) >= 200
    for case in cases:
        for start, end in case.truth_intervals:
            expected = case.target_bar_count * case.song.meters[0][1] * case.song.ticks_per_beat
            assert end - start == expected


def test_interventions_straddle_frozen_tolerances(cohort) -> None:
    cases, _audit = cohort
    selected = {
        condition: next(case for case in cases if case.condition == condition)
        for condition in (
            "timing_inside_tolerance",
            "timing_outside_tolerance",
            "missing_at_tolerance",
            "missing_beyond_tolerance",
            "extra_at_tolerance",
            "extra_beyond_tolerance",
        )
    }

    assert selected["timing_inside_tolerance"].intervention["timing_edit_bound_beats"] < 1 / 12
    assert selected["timing_outside_tolerance"].intervention["timing_edit_bound_beats"] > 1 / 12
    assert selected["missing_at_tolerance"].intervention["edit_fraction_max"] <= 0.10
    assert selected["missing_beyond_tolerance"].intervention["edit_fraction_min"] > 0.10
    assert selected["extra_at_tolerance"].intervention["edit_fraction_max"] <= 0.10
    assert selected["extra_beyond_tolerance"].intervention["edit_fraction_min"] > 0.10


def test_multitrack_merge_and_pickup_are_explicit_diagnostics(cohort) -> None:
    cases, _audit = cohort
    multitrack = next(case for case in cases if case.condition == "multitrack_merged")
    pickup = next(case for case in cases if case.condition == "pickup_bar_origin_mismatch")

    assert len(multitrack.song.parts) == 3
    assert len(drum_part(multitrack.song).notes) < sum(
        len(part.notes) for part in multitrack.song.parts
    )
    assert pickup.diagnostic_expected_failure
    bar_ticks = pickup.song.meters[0][1] * pickup.song.ticks_per_beat
    assert all(start % bar_ticks for start, _end in pickup.truth_intervals)
    assert pickup.intervention["pickup_offset_beats"] == pickup.song.meters[0][1] / 4


def test_scoring_separates_target_nested_and_negative_outputs(cohort) -> None:
    cases, _audit = cohort
    case = next(
        case
        for case in cases
        if case.condition == "varied_exact" and case.target_bar_count == 4
    )
    nested = {
        "family_id": "nested",
        "bar_count": 1,
        "occurrences": [
            {"start_tick": start, "end_tick": start + (end - start) // 4}
            for start, end in case.truth_intervals
        ],
    }
    target = {
        "family_id": "target",
        "bar_count": 4,
        "occurrences": [
            {"start_tick": start, "end_tick": end}
            for start, end in case.truth_intervals
        ],
    }
    row = score_case(case, [nested, target], {}, 0.01)

    assert row["target_recovered"]
    assert row["target_rank"] == 2
    assert row["nested_legitimate_families"] == 1
    assert row["non_target_returned_occurrences"] == case.occurrence_count

    negative = next(case for case in cases if not case.positive)
    negative_row = score_case(negative, [nested], {}, 0.01)
    aggregate = aggregate_results([negative_row])
    assert aggregate["negative_cases_with_output"] == 1
    assert aggregate["negative_case_denominator"] == 1
    assert aggregate["negative_case_output_wilson_95"][0] > 0
    assert aggregate["exact_identity_control_cases"] == 0
    assert aggregate["tolerant_supported_control_cases"] == 0


def test_selected_controls_exercise_detector_without_tuning(cohort) -> None:
    cases, _audit = cohort
    selected = {
        condition: next(
            case
            for case in cases
            if case.condition == condition and case.target_bar_count == 1
        )
        for condition in (
            "varied_exact",
            "timing_inside_tolerance",
            "pickup_bar_origin_mismatch",
        )
    }

    exact_result = extract_drums(selected["varied_exact"].song, DrumConfig(mode="exact"))
    exact_row = score_case(
        selected["varied_exact"],
        exact_result["phrases"],
        exact_result["stats"],
        0.01,
    )
    inside_result = extract_drums(
        selected["timing_inside_tolerance"].song, DrumConfig(mode="tolerant")
    )
    inside_row = score_case(
        selected["timing_inside_tolerance"],
        inside_result["phrases"],
        inside_result["stats"],
        0.01,
    )
    pickup_result = extract_drums(
        selected["pickup_bar_origin_mismatch"].song, DrumConfig(mode="tolerant")
    )
    pickup_row = score_case(
        selected["pickup_bar_origin_mismatch"],
        pickup_result["phrases"],
        pickup_result["stats"],
        0.01,
    )

    assert exact_row["target_recovered"]
    assert inside_row["target_recovered"]
    assert not pickup_row["target_recovered"]


def test_run_writes_design_before_result_shaped_artifacts(tmp_path, cohort) -> None:
    cases, audit = cohort
    subset = cases[: len(CONDITIONS)]
    with patch(
        "samuged.drum_stress.generate_cohort",
        return_value=(subset, audit),
    ):
        aggregate = run_stress(tmp_path / "stress", cases_per_condition=40)

    design = json.loads((tmp_path / "stress/design.json").read_text())
    raw = json.loads((tmp_path / "stress/raw_results.json").read_text())
    saved = json.loads((tmp_path / "stress/aggregate.json").read_text())

    assert aggregate == saved
    assert "methods" not in design
    assert "target_recovered" not in json.dumps(design)
    assert design["design_sha256"] == raw["design_sha256"] == saved["design_sha256"]
    assert len(raw["cases"]) == len(CONDITIONS)
    receipt = json.loads((tmp_path / "stress/experiment_receipt.json").read_text())
    assert receipt["status"] == "started"
    snapshot = json.loads((tmp_path / "stress/source_snapshot.json").read_text())
    snapshot_paths = {entry["path"] for entry in snapshot["files"]}
    assert {
        "samuged/__init__.py",
        "samuged/metadata_recovery.py",
    } <= snapshot_paths
    assert design["receipt_sha256"] == raw["receipt_sha256"] == saved["receipt_sha256"]
    frozen_cohort_hash = receipt["case_cohort_sha256"]
    assert design["case_cohort_sha256"] == frozen_cohort_hash
    assert frozen_cohort_hash == saved["cohort_sha256"]
    completion = verify_completed_experiment(tmp_path / "stress")
    assert completion["status"] == "completed"
    assert set(completion["artifacts"]) == {"aggregate.json", "raw_results.json"}


def test_run_refuses_to_overwrite_existing_output(tmp_path, cohort) -> None:
    output = tmp_path / "stress"
    output.mkdir()
    (output / "existing.json").write_text("{}")
    with patch("samuged.drum_stress.generate_cohort", return_value=cohort):
        with pytest.raises(FileExistsError, match="must be empty"):
            run_stress(output, cases_per_condition=40)
