from __future__ import annotations

from pathlib import Path

import pytest

import scripts.evaluate_certified_drums as controls
from samuged.experiment import verify_completed_experiment


def test_frozen_design_covers_requested_geometry() -> None:
    design = controls.frozen_design()

    assert design["version"] == controls.VERSION
    assert design["meters"] == [[4, 4], [3, 4], [6, 8], [7, 8]]
    assert design["ticks_per_beat"] == [96, 480, 960]
    assert design["bars"] == [16, 32]
    assert design["negative_acceptance"]["oracle_pair_count"] == 0
    assert design["negative_acceptance"]["pair_budget_reached"] is False
    assert design["negative_acceptance"]["exhaustive_pair_enumeration"] is True
    assert design["result_artifacts"][:4] == [
        "design.json", "labels.json", "raw_results.json", "aggregate.json"
    ]


def test_small_cohort_has_certified_controls_and_unique_negatives() -> None:
    cases, audit = controls.generate_certified_cohort(
        negative_cases_per_split=2,
        positive_cases_per_split=1,
        max_attempts=100,
    )

    negatives = [case for case in cases if case.kind == "certified_negative"]
    positives = [case for case in cases if case.kind == "planted_positive"]
    assert len(negatives) == 4
    assert len(positives) == 2
    assert all(case.oracle["oracle_pair_count"] == 0 for case in negatives)
    assert all(not case.oracle["pair_budget_reached"] for case in negatives)
    assert all(case.oracle["exhaustive_pair_enumeration"] for case in negatives)
    assert all(set(case.target_pair_keys) <= case.oracle["pairs"] for case in positives)
    assert len({case.exact_arrangement_sha256 for case in negatives}) == len(negatives)
    assert len({case.beat_arrangement_sha256 for case in negatives}) == len(negatives)
    assert audit["negative_oracle_pair_count_total"] == 0
    assert audit["positive_target_pairs_oracle_confirmed"] == len(positives)


def test_oracle_rejects_a_repeated_control_bar() -> None:
    bars = [[(slot, 36 + (slot % 4), 90) for slot in range(12)] for _ in range(16)]
    song = controls._song_from_bars(bars, ppq=480, numerator=3, denominator=4)

    certificate = controls._oracle_certificate(song)

    assert certificate["oracle_pair_count"] > 0
    assert certificate["pair_budget_reached"] is False


def test_run_writes_receipt_labels_before_detector_and_binds_midis(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "certified"
    original = controls.extract_drums
    calls: list[str] = []

    def wrapped(song, config):
        assert (output / "experiment_receipt.json").is_file()
        assert (output / "labels.json").is_file()
        calls.append(config.mode)
        return original(song, config)

    monkeypatch.setattr(controls, "extract_drums", wrapped)
    result = controls.run(
        output,
        negative_cases_per_split=2,
        positive_cases_per_split=1,
        max_attempts=100,
    )

    assert calls == ["exact", "exact", "exact", "exact", "exact", "exact",
                     "tolerant", "tolerant", "tolerant", "tolerant", "tolerant", "tolerant"]
    assert result["case_count"] == 6
    assert (output / "completion_receipt.json").is_file()
    completed = verify_completed_experiment(output)
    assert completed["status"] == "completed"
    required = set(completed["required_artifacts"])
    assert "labels.json" in required
    assert "design.json" in required
    assert len([name for name in required if name.endswith(".mid")]) == 6
    assert result["methods"]["exact"]["overall"]["negative_cases"] == 4


def test_run_rejects_nonempty_output_before_generation(tmp_path: Path) -> None:
    output = tmp_path / "existing"
    output.mkdir()
    (output / "sentinel").write_text("keep")

    with pytest.raises(FileExistsError):
        controls.run(
            output,
            negative_cases_per_split=1,
            positive_cases_per_split=1,
            max_attempts=20,
        )

    assert (output / "sentinel").read_text() == "keep"
