"""Reconstruct the small external theme diagnostic before citing its scores."""
from __future__ import annotations

import argparse
import importlib.util
from itertools import product
import json
import math
from pathlib import Path
import random
import sys

from . import evaluate_themes as evaluation
from .experiment import sha256_bytes, sha256_json, verify_completed_experiment


_REPLAY_SOURCE_FILES = frozenset(
    {
        "pyproject.toml",
        "requirements-research.lock",
        "samuged/aligned.py",
        "samuged/aligned_indexed.py",
        "samuged/midi.py",
        "samuged/phrases.py",
    }
)
_SNAPSHOT_FILES = _REPLAY_SOURCE_FILES | {"samuged/experiment.py", "samuged/evaluate_themes.py"}
_IMPORT_CLOSURE_FILES = frozenset({"samuged/__init__.py", "samuged/metadata_recovery.py"})


def _same(actual, expected, label: str) -> None:
    if actual != expected:
        raise ValueError(f"theme {label} mismatch")


def _expected_design(input_receipts: dict) -> dict:
    return {
        "schema_version": evaluation.EVALUATION_VERSION,
        "official_source": evaluation.OFFICIAL_SOURCE,
        "cohort": list(evaluation.SONG_IDS),
        "domain": "exact beat-normalized note identities from annotator-0 track union",
        "canonical_adapter": (
            "union annotator 0 tracks 1 and 2; one piano part, channel 0, "
            "program 0, canonical_melody name; annotator track identity removed"
        ),
        "annotation_views": "track 2 positives scored separately for each annotator",
        "primary_prediction": "all source notes in every verified occurrence of top-ranked family",
        "sensitivity_prediction": "union of all source notes in verified occurrences of top three families",
        "metric": "exact note classification precision, recall and F1",
        "inter_annotator_agreement": "pairwise raw note-label agreement and Cohen kappa",
        "bootstrap": {
            "unit": "song with all three annotators retained",
            "song_count": len(evaluation.SONG_IDS),
            "samples": evaluation.BOOTSTRAP_SAMPLES,
            "seed": evaluation.BOOTSTRAP_SEED,
            "interval": "percentile 95%",
        },
        "claim_boundary": (
            "local note-domain diagnostic; not the authors' beat-domain F1, not "
            "occurrence-family F1, corpus accuracy or musical memorability"
        ),
        "published_baseline_boundary": (
            "input note-universe coverage only because all 30 published prediction "
            "MIDIs differ from the canonical annotation universe"
        ),
        "input_receipts": input_receipts,
    }


def _agreement(left: set[int], right: set[int], universe_size: int) -> dict:
    both_positive = len(left & right)
    both_negative = universe_size - len(left | right)
    observed = (both_positive + both_negative) / universe_size
    left_rate = len(left) / universe_size
    right_rate = len(right) / universe_size
    expected = left_rate * right_rate + (1 - left_rate) * (1 - right_rate)
    kappa = None if math.isclose(expected, 1.0) else (observed - expected) / (1 - expected)
    return {"raw_agreement": observed, "cohen_kappa": kappa}


def _percentile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(probability * (len(ordered) - 1))))
    return ordered[index]


def _bootstrap(per_song: dict[str, dict[str, float]]) -> dict:
    songs = sorted(per_song)
    metrics = ("precision", "recall", "f1")
    source = random.Random(evaluation.BOOTSTRAP_SEED)
    draws = {metric: [] for metric in metrics}
    for _ in range(evaluation.BOOTSTRAP_SAMPLES):
        selected = [source.choice(songs) for _ in songs]
        for metric in metrics:
            draws[metric].append(
                sum(per_song[song][metric] for song in selected) / len(selected)
            )
    return {
        metric: {
            "estimate": sum(per_song[song][metric] for song in songs) / len(songs),
            "ci95_low": _percentile(draws[metric], 0.025),
            "ci95_high": _percentile(draws[metric], 0.975),
        }
        for metric in metrics
    }


def _method_views(rows: list[dict]) -> dict:
    groups = {}
    for method in evaluation.METHODS:
        for view in evaluation.VIEWS:
            selected = [
                row for row in rows
                if row["method"] == method and row["view"] == view
            ]
            per_song = {
                song_id: {
                    metric: sum(
                        row["metrics"][metric]
                        for row in selected
                        if row["song_id"] == song_id
                    ) / len(evaluation.ANNOTATORS)
                    for metric in ("precision", "recall", "f1")
                }
                for song_id in evaluation.SONG_IDS
            }
            groups[f"{method}/{view}"] = {
                "song_count": len(evaluation.SONG_IDS),
                "annotation_views": len(selected),
                "per_song_mean_over_annotators": per_song,
                "macro_over_songs": {
                    metric: sum(per_song[song][metric] for song in evaluation.SONG_IDS)
                    / len(evaluation.SONG_IDS)
                    for metric in ("precision", "recall", "f1")
                },
                "macro_by_annotator": {
                    str(annotator): {
                        metric: sum(
                            row["metrics"][metric]
                            for row in selected
                            if row["annotator"] == annotator
                        ) / len(evaluation.SONG_IDS)
                        for metric in ("precision", "recall", "f1")
                    }
                    for annotator in evaluation.ANNOTATORS
                },
                "cluster_bootstrap_by_song": _bootstrap(per_song),
            }
    return groups


def _runtime(value, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"theme {label} is not numeric")
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"theme {label} is not finite and nonnegative")
    return float(value)


def verify(output: Path, input_root: Path, input_audit: Path, *, replay: bool = True) -> dict:
    """Check input labels, every result row and optionally all detector outputs.

    Receipt hashes alone cannot prove that a metric was calculated correctly.
    This check reconstructs labels from the frozen MIDI inputs, independently
    counts the classification outcomes and requires the exact study cohort.
    Replay additionally checks every saved phrase output hash with unchanged
    executable detector files. It does not provide new human quality labels.
    """
    completion = verify_completed_experiment(output)
    _same(set(completion["artifacts"]), {"raw_results.json", "aggregate.json"}, "result artifacts")
    receipt = json.loads((output / "experiment_receipt.json").read_text())
    raw = json.loads((output / "raw_results.json").read_text())
    aggregate = json.loads((output / "aggregate.json").read_text())
    # Use the recorded adapter for input reconstruction and detector dispatch.
    # Its relative core imports are checked against their saved hashes below.
    frozen_path = output / "source_snapshot/samuged/evaluate_themes.py"
    module_name = "samuged._theme_audit_frozen_adapter"
    specification = importlib.util.spec_from_file_location(module_name, frozen_path)
    evaluation = importlib.util.module_from_spec(specification)
    sys.modules[module_name] = evaluation
    specification.loader.exec_module(evaluation)
    for value in (receipt["design"], raw, aggregate):
        _same(value.get("schema_version"), evaluation.EVALUATION_VERSION, "schema version")
    cases, input_receipts = evaluation.load_cases(input_root, input_audit)
    case_metadata = [case.receipt_metadata() for case in cases]
    expected_design = _expected_design(input_receipts)
    _same(receipt["design"], expected_design, "frozen design")
    _same(receipt["case_cohort"], case_metadata, "frozen cohort")
    _same(raw["cases"], case_metadata, "raw cohort")
    _same(receipt["design"]["input_receipts"], input_receipts, "design input receipts")
    _same(raw["input_receipts"], input_receipts, "raw input receipts")
    _same(receipt["config"], json.loads(json.dumps({"detectors": evaluation._configs(), "top_k": 3})),
          "detector configuration")
    _same(aggregate["song_count"], len(cases), "song count")
    _same(aggregate["annotation_views"], len(cases) * len(evaluation.ANNOTATORS), "annotation count")

    snapshot = json.loads((output / "source_snapshot.json").read_text())
    saved_hashes = {row["path"]: row["sha256"] for row in snapshot["files"]}
    closure_complete = _IMPORT_CLOSURE_FILES.issubset(saved_hashes)
    expected_files = _SNAPSHOT_FILES | (_IMPORT_CLOSURE_FILES if closure_complete else frozenset())
    _same(set(saved_hashes), expected_files, "source snapshot file set")
    if replay:
        repository = Path(__file__).resolve().parents[1]
        replay_files = _REPLAY_SOURCE_FILES | (_IMPORT_CLOSURE_FILES if closure_complete else frozenset())
        for relative in sorted(replay_files):
            _same(sha256_bytes((repository / relative).read_bytes()), saved_hashes[relative],
                  f"replay executable {relative}")

    runs = raw["detector_runs"]
    expected_run_keys = list(product(evaluation.SONG_IDS, evaluation.METHODS))
    _same([(row["song_id"], row["method"]) for row in runs], expected_run_keys, "detector run coverage")
    expected_rows = []
    for run in runs:
        case = next(case for case in cases if case.song_id == run["song_id"])
        universe_size = len(case.song.parts[0].notes)
        config = receipt["config"]["detectors"][run["method"]]
        _runtime(run.get("runtime_seconds"), "detector runtime")
        if type(run.get("phrase_count")) is not int or not 0 <= run["phrase_count"] <= 3:
            raise ValueError("theme phrase count is outside frozen top-k bounds")
        _same(run["phrase_count"], 3, "frozen phrase count")
        _same(set(run["predicted_source_note_indices"]), set(evaluation.VIEWS),
              "prediction view keys")
        if replay:
            found = evaluation._detect(run["method"], case.song, config)
            _same(sha256_json(found["phrases"]), run["phrase_output_sha256"], "replayed phrase output")
            _same(len(found["phrases"]), run["phrase_count"], "replayed phrase count")
            _same(evaluation._telemetry(found), run["telemetry"], "replayed telemetry")
        for view in evaluation.VIEWS:
            indices = run["predicted_source_note_indices"][view]
            if (any(type(index) is not int or not 0 <= index < universe_size for index in indices)
                    or indices != sorted(set(indices))):
                raise ValueError("theme prediction indices are not unique source coordinates")
            predicted = set(indices)
            if replay:
                _same(predicted, evaluation.prediction_indices(
                    case.song, found["phrases"], top_n=1 if view == "top1" else 3,
                    onset_merge_beats=config["onset_merge_beats"],
                    require_source_verified=run["method"] == "aligned_indexed",
                ), "replayed source indices")
            for annotator in evaluation.ANNOTATORS:
                truth = case.labels[str(annotator)]
                # Count labels directly, independently of the runner's metric helper.
                tp = sum(index in truth for index in predicted)
                fp, fn = len(predicted) - tp, len(truth) - tp
                precision = tp / len(predicted) if predicted else float(not truth)
                recall = tp / len(truth) if truth else float(not predicted)
                f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
                expected_rows.append({
                    "song_id": case.song_id, "method": run["method"], "view": view,
                    "annotator": annotator, "truth_positive_notes": len(truth),
                    "predicted_positive_notes": len(predicted),
                    "metrics": {"true_positive": tp, "false_positive": fp, "false_negative": fn,
                                "precision": precision, "recall": recall, "f1": f1},
                })
        if not set(run["predicted_source_note_indices"]["top1"]).issubset(
            run["predicted_source_note_indices"]["top3"]
        ):
            raise ValueError("theme top-one prediction is not contained in top-three")
    _same(raw["note_classification"], expected_rows, "classification rows")
    _same(aggregate["method_views"], _method_views(expected_rows), "aggregate metrics")
    agreement = [{"song_id": case.song_id, "annotator_pair": [left, right],
                  **_agreement(case.labels[str(left)], case.labels[str(right)],
                               len(case.song.parts[0].notes))}
                 for case in cases for left, right in ((0, 1), (0, 2), (1, 2))]
    _same(raw["inter_annotator_agreement"], agreement, "raw annotator agreement")
    _same(aggregate["inter_annotator_agreement"], agreement, "aggregate annotator agreement")
    for key in ("search_limited", "curation_truncated"):
        _same(aggregate[f"{key}_runs"], sum(row["telemetry"][key] for row in runs), key)
    _same(
        aggregate["metadata_checks"],
        {
            "all_note_universes_equal": True,
            "all_meters_equal": all(case.metadata["meters_equal"] for case in cases),
            "songs_with_annotator_tempo_disagreement": [
                case.song_id for case in cases if not case.metadata["tempos_equal"]
            ],
        },
        "metadata checks",
    )
    coverage = [
        {"song_id": case.song_id, **row}
        for case in cases
        for row in case.baseline_input_coverage
    ]
    _same(len(coverage), 30, "published baseline coverage count")
    _same(aggregate["published_baseline_input_coverage"], coverage,
          "published baseline input coverage")
    _same(aggregate["official_source"], evaluation.OFFICIAL_SOURCE, "official source")
    _same(aggregate["official_source_comparison"],
          input_receipts["official_source_comparison"], "official source comparison")
    _same(aggregate["claim_boundary"], expected_design["claim_boundary"], "claim boundary")
    _same(aggregate["published_baseline_boundary"],
          expected_design["published_baseline_boundary"], "published baseline boundary")
    expected_summary = {
        method: {
            "songs": len([row for row in runs if row["method"] == method]),
            "runtime_seconds": sum(
                row["runtime_seconds"] for row in runs if row["method"] == method
            ),
            "search_limited_songs": sum(
                row["telemetry"]["search_limited"]
                for row in runs if row["method"] == method
            ),
            "curation_truncated_songs": sum(
                row["telemetry"]["curation_truncated"]
                for row in runs if row["method"] == method
            ),
        }
        for method in evaluation.METHODS
    }
    _same(aggregate["detector_summary"], expected_summary, "detector summary")
    _same(aggregate["total_runtime_seconds"],
          sum(row["runtime_seconds"] for row in runs), "total runtime")
    return {
        "schema_version": "samuged-theme-audit-v1", "passed": True,
        "detector_replayed": replay, "song_count": len(cases), "detector_runs": len(runs),
        "frozen_local_import_closure_complete": closure_complete,
        "classification_rows": len(expected_rows),
        "raw_results_sha256": sha256_bytes((output / "raw_results.json").read_bytes()),
        "aggregate_sha256": sha256_bytes((output / "aggregate.json").read_bytes()),
        "completion_receipt_sha256": sha256_bytes((output / "completion_receipt.json").read_bytes()),
        "claim_boundary": "frozen input reconstruction and metric arithmetic, not corpus quality",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment", type=Path, required=True)
    parser.add_argument("--input-root", type=Path, required=True)
    parser.add_argument("--input-audit", type=Path, required=True)
    parser.add_argument("--skip-replay", action="store_true")
    arguments = parser.parse_args()
    print(json.dumps(verify(arguments.experiment, arguments.input_root, arguments.input_audit,
                            replay=not arguments.skip_replay), indent=2))
