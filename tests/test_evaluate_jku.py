import json
from pathlib import Path

import pytest

from samuged.evaluate_jku import (
    ALGORITHMS,
    EXPECTED_PIECES,
    PUBLISHED_METRIC_COLUMNS,
    _expected_pieces,
    _algorithm_specs,
    _result_telemetry,
    load_piece,
    metrics,
    prediction_points,
    run,
)
from samuged.experiment import verify_completed_experiment


def test_algorithm_selection_keeps_reference_default_modes_and_top_k():
    reference, _ = _algorithm_specs("reference", 3)
    aligned, _ = _algorithm_specs("aligned", 3)
    indexed, _ = _algorithm_specs("aligned_indexed", 3)

    assert ALGORITHMS == ("reference", "aligned", "aligned_indexed")
    assert tuple(reference) == ("exact", "transposed", "approximate")
    assert set(aligned) == {"aligned"}
    assert set(indexed) == {"aligned_indexed"}
    assert all(config["top_k"] == 3 for configs in (reference, aligned, indexed)
               for config in configs.values())
    with pytest.raises(ValueError, match="algorithm must be one of"):
        _algorithm_specs("unknown", 3)


def test_telemetry_aggregates_parts_without_inventing_missing_counters():
    found = {"part_stats": [
        {"note_limit_reached": True, "comparisons": 4, "dp_calls": 2},
        {"note_limit_reached": False, "comparison_limit_reached": True,
         "comparisons": 7, "exact_signature_hits": 3},
    ]}

    telemetry = _result_telemetry(found)

    assert telemetry["limit_parts"]["note_limit_reached"] == 1
    assert telemetry["limit_parts"]["comparison_limit_reached"] == 1
    assert telemetry["limit_parts"]["window_limit_reached"] == 0
    assert telemetry["profile_counters"]["comparisons"] == 11
    assert telemetry["profile_counters"]["dp_calls"] == 2
    assert telemetry["profile_counters"]["exact_signature_hits"] == 3


def test_empty_prediction_has_scalar_zero_metrics():
    reference = [[[(0, 60), (1, 62)], [(4, 60), (5, 62)]]]
    scores = metrics(reference, [])
    assert scores["F_est"] == scores["F_occ.75"] == scores["FFTP_est"] == 0
    assert all(isinstance(value, float) for value in scores.values())
    perfect = metrics(reference, reference)
    assert perfect["F_est"] == perfect["F_occ.75"] == perfect["F_3"] == 1


def test_occurrence_thresholds_are_explicit_and_distinct():
    reference = [[[(0, pitch) for pitch in range(5)]]]
    estimated = [[[(0, pitch) for pitch in range(3)]]]

    scores = metrics(reference, estimated)

    assert scores["F_occ.5"] == pytest.approx(0.6)
    assert scores["F_occ.75"] == 0
    assert set(PUBLISHED_METRIC_COLUMNS) == {
        "P_est", "R_est", "F_est", "P_occ.75", "R_occ.75", "F_occ.75",
        "P_3", "R_3", "F_3", "FFTP_est", "FFP", "P_occ.5", "R_occ.5",
        "F_occ.5", "P", "R", "F",
    }


def test_csv_pickup_alignment_and_exact_source_mapping(tmp_path):
    variant = tmp_path/"monophonic"
    (variant/"csv").mkdir(parents=True)
    (variant/"kern").mkdir()
    occurrences = variant/"repeatedPatterns"/"schoenberg"/"A"/"occurrences"/"csv"
    occurrences.mkdir(parents=True)
    (variant/"kern"/"score.krn").write_text("**kern\n*M3/4\n")
    (variant/"csv"/"score.csv").write_text("-1,60,60,0.5,0\n0.66666,64,64,0.5,0\n5,60,60,0.5,0\n6.66666,64,64,0.5,0\n")
    (occurrences/"occ1.csv").write_text("-1,60\n0.66666,64\n")
    (occurrences/"occ2.csv").write_text("5,60\n6.66666,64\n")
    song, truth, meta = load_piece(variant)
    assert meta["offset_beats"] == 3
    assert song.parts[0].notes[0].start == 1920
    phrase = {"part_index": 0, "prototype_note_index": 0, "note_count": 2,
              "occurrences": [{"note_index": 0}, {"note_index": 2}]}
    predicted = prediction_points(song, [phrase], meta["offset_beats"], meta["_point_lookup"])
    assert predicted == truth
    assert metrics(truth, predicted)["F_est"] == 1
    (occurrences/"occ2.csv").write_text("500,60\n")
    with pytest.raises(ValueError, match="absent from score"):
        load_piece(variant)


@pytest.mark.parametrize("staff", ["0.5", "-1"])
def test_score_staff_must_be_a_nonnegative_integer(tmp_path, staff):
    variant = tmp_path/"monophonic"
    (variant/"csv").mkdir(parents=True)
    (variant/"kern").mkdir()
    (variant/"repeatedPatterns").mkdir()
    (variant/"kern"/"score.krn").write_text("**kern\n*M4/4\n")
    (variant/"csv"/"score.csv").write_text(f"0,60,60,1,{staff}\n")

    with pytest.raises(ValueError, match="invalid full score columns"):
        load_piece(variant)


def test_run_refuses_a_populated_output_directory(tmp_path):
    output = tmp_path/"output"
    output.mkdir()
    (output/"existing.json").write_text("{}")

    with pytest.raises(ValueError, match="absent or empty"):
        run(tmp_path/"unused-source", output)


def test_jku_run_rejects_incomplete_five_piece_cohort(tmp_path):
    root = tmp_path / "jku"
    ground_truth = root / "groundTruth"
    for piece in EXPECTED_PIECES[:-1]:
        (ground_truth / piece).mkdir(parents=True)

    with pytest.raises(ValueError, match="exactly the five expected works"):
        run(root, tmp_path / "output")


def test_jku_run_writes_top_level_links_and_completion_receipt(tmp_path, monkeypatch):
    root = tmp_path / "jku"
    ground_truth = root / "groundTruth"
    for piece in EXPECTED_PIECES:
        (ground_truth / piece).mkdir(parents=True)

    prior_path = (
        Path(__file__).resolve().parents[1]
        / "research_local/jku_reference_v02/published_examples.json"
    )
    if not prior_path.is_file():
        pytest.skip("frozen JKU published examples are unavailable")
    prior = json.loads(prior_path.read_text())
    monkeypatch.setattr(
        "samuged.evaluate_jku._algorithm_specs",
        lambda _algorithm, _top_k: (
            {"toy": {}},
            lambda _mode, _song: {
                "phrases": [],
                "search_limited": False,
                "curation_truncated": False,
                "part_stats": [],
            },
        ),
    )
    monkeypatch.setattr(
        "samuged.evaluate_jku.verify_published_examples",
        lambda _root: {
            "passed": True,
            "examples": prior["examples"],
            "reference_patterns": 0,
            "verified_metric_names": [],
            "metric_provenance": {},
            "mir_eval_version": "0.8.2",
        },
    )
    monkeypatch.setattr(
        "samuged.evaluate_jku.load_piece",
        lambda _path: (
            __import__("samuged.midi", fromlist=["MidiSong"]).MidiSong(
                480, [], [], [], []
            ),
            [],
            {
                "_point_lookup": {},
                "offset_beats": 0.0,
                "ground_truth_points_verified_in_score": True,
                "score_path": "fixture.csv",
                "score_sha256": "0" * 64,
            },
        ),
    )

    result = run(root, tmp_path / "output")
    raw = json.loads((tmp_path / "output/raw_results.json").read_text())
    aggregate = json.loads((tmp_path / "output/aggregate.json").read_text())

    for key in ("receipt_sha256", "config_sha256", "source_snapshot_sha256",
                "snapshot_sha256", "case_cohort_sha256"):
        assert raw[key] == aggregate[key] == result[key]
    completion = verify_completed_experiment(tmp_path / "output")
    assert completion["status"] == "completed"
    snapshot = json.loads((tmp_path / "output/source_snapshot.json").read_text())
    snapshot_paths = {entry["path"] for entry in snapshot["files"]}
    assert {
        "samuged/__init__.py",
        "samuged/metadata_recovery.py",
    } <= snapshot_paths
