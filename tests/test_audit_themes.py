from hashlib import sha256
import json
from pathlib import Path
import shutil

import pytest

from samuged.audit_themes import verify


REPOSITORY = Path(__file__).resolve().parents[1]
EXPERIMENT = REPOSITORY / "research_local/theme_evaluation_v01"
INPUT_ROOT = REPOSITORY / "research_local/external/theme_transformer"
INPUT_AUDIT = REPOSITORY / "research_local/theme_annotation_input_audit.json"


def _require_fixture() -> None:
    required = (
        EXPERIMENT / "completion_receipt.json",
        EXPERIMENT / "raw_results.json",
        EXPERIMENT / "aggregate.json",
        INPUT_ROOT / "download_receipts.json",
        INPUT_AUDIT,
    )
    if not all(path.is_file() for path in required):
        pytest.skip("local frozen theme evaluation fixture is unavailable")


def _copy_experiment(tmp_path: Path) -> Path:
    _require_fixture()
    target = tmp_path / "theme"
    shutil.copytree(EXPERIMENT, target)
    return target


def _rewrite_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n")


def _reseal(experiment: Path, artifact: str) -> None:
    path = experiment / artifact
    data = path.read_bytes()
    completion_path = experiment / "completion_receipt.json"
    completion = json.loads(completion_path.read_text())
    completion["artifacts"][artifact] = {
        "bytes": len(data),
        "sha256": sha256(data).hexdigest(),
    }
    _rewrite_json(completion_path, completion)


def test_actual_frozen_theme_evaluation_passes_full_replay() -> None:
    _require_fixture()

    result = verify(EXPERIMENT, INPUT_ROOT, INPUT_AUDIT)

    assert result["passed"] is True
    assert result["detector_replayed"] is True
    assert result["song_count"] == 6
    assert result["detector_runs"] == 24
    assert result["classification_rows"] == 144


def test_unsealed_result_mutation_fails_completion_integrity(tmp_path: Path) -> None:
    experiment = _copy_experiment(tmp_path)
    aggregate_path = experiment / "aggregate.json"
    aggregate = json.loads(aggregate_path.read_text())
    aggregate["song_count"] = 7
    _rewrite_json(aggregate_path, aggregate)

    with pytest.raises(ValueError, match="completed result changed"):
        verify(experiment, INPUT_ROOT, INPUT_AUDIT, replay=False)


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        (
            lambda value: value["metadata_checks"].update(all_meters_equal=False),
            "metadata checks mismatch",
        ),
        (
            lambda value: value["published_baseline_input_coverage"][0].update(
                canonical_note_coverage=1.0
            ),
            "published baseline input coverage mismatch",
        ),
        (
            lambda value: value["detector_summary"]["reference_exact"].update(
                curation_truncated_songs=0
            ),
            "detector summary mismatch",
        ),
        (
            lambda value: value.update(total_runtime_seconds=0.0),
            "total runtime mismatch",
        ),
        (
            lambda value: value["official_source_comparison"].update(
                all_official_melody_unions_exact_match_canonical=True
            ),
            "official source comparison mismatch",
        ),
        (
            lambda value: value["method_views"]["aligned_indexed/top1"]
            ["cluster_bootstrap_by_song"]["f1"].update(ci95_high=1.0),
            "aggregate metrics mismatch",
        ),
    ),
)
def test_resealed_aggregate_claim_corruption_is_rejected(
    tmp_path: Path, mutation, message: str
) -> None:
    experiment = _copy_experiment(tmp_path)
    aggregate_path = experiment / "aggregate.json"
    aggregate = json.loads(aggregate_path.read_text())
    mutation(aggregate)
    _rewrite_json(aggregate_path, aggregate)
    _reseal(experiment, "aggregate.json")

    with pytest.raises(ValueError, match=message):
        verify(experiment, INPUT_ROOT, INPUT_AUDIT, replay=False)


def test_resealed_row_arithmetic_corruption_is_rejected(tmp_path: Path) -> None:
    experiment = _copy_experiment(tmp_path)
    raw_path = experiment / "raw_results.json"
    raw = json.loads(raw_path.read_text())
    raw["note_classification"][0]["metrics"]["true_positive"] += 1
    _rewrite_json(raw_path, raw)
    _reseal(experiment, "raw_results.json")

    with pytest.raises(ValueError, match="classification rows mismatch"):
        verify(experiment, INPUT_ROOT, INPUT_AUDIT, replay=False)


def test_resealed_invalid_runtime_and_phrase_count_are_rejected(tmp_path: Path) -> None:
    experiment = _copy_experiment(tmp_path)
    raw_path = experiment / "raw_results.json"
    raw = json.loads(raw_path.read_text())
    raw["detector_runs"][0]["runtime_seconds"] = -1
    _rewrite_json(raw_path, raw)
    _reseal(experiment, "raw_results.json")
    with pytest.raises(ValueError, match="not finite and nonnegative"):
        verify(experiment, INPUT_ROOT, INPUT_AUDIT, replay=False)

    raw["detector_runs"][0]["runtime_seconds"] = 0
    raw["detector_runs"][0]["phrase_count"] = 2
    _rewrite_json(raw_path, raw)
    _reseal(experiment, "raw_results.json")
    with pytest.raises(ValueError, match="frozen phrase count mismatch"):
        verify(experiment, INPUT_ROOT, INPUT_AUDIT, replay=False)


def test_resealed_prediction_view_corruption_is_rejected(tmp_path: Path) -> None:
    experiment = _copy_experiment(tmp_path)
    raw_path = experiment / "raw_results.json"
    raw = json.loads(raw_path.read_text())
    run = raw["detector_runs"][0]
    extra = next(
        index
        for index in range(raw["cases"][0]["canonical_note_count"])
        if index not in run["predicted_source_note_indices"]["top3"]
    )
    run["predicted_source_note_indices"]["top1"].append(extra)
    run["predicted_source_note_indices"]["top1"].sort()
    _rewrite_json(raw_path, raw)
    _reseal(experiment, "raw_results.json")

    with pytest.raises(ValueError, match="top-one prediction is not contained"):
        verify(experiment, INPUT_ROOT, INPUT_AUDIT, replay=False)
