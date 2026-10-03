"""Independently audit frozen melodic interval metrics and assignments."""
from __future__ import annotations

import argparse
from collections import Counter
from fractions import Fraction
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Iterable

from samuged.dataset import atomic_json
from samuged.experiment import (
    complete_experiment,
    prepare_experiment,
    receipt_links,
    verify_completed_experiment,
)


VERSION = "melodic-metric-audit-v1"
THRESHOLD = Fraction(4, 5)
STUDY_NAMES = (
    "evaluation_reference_v04",
    "aligned_frozen_v02",
    "closed_patterns_v01_replication",
)
CORE_ARTIFACTS = (
    "experiment_receipt.json",
    "completion_receipt.json",
    "source_snapshot.json",
    "raw_results.json",
    "aggregate.json",
)
REQUIRED_FILES = (
    "scripts/audit_melodic_metrics.py",
    "samuged/dataset.py",
    "samuged/experiment.py",
    "pyproject.toml",
    "requirements-research.lock",
)


def _integer(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{label} must be an integer")
    return value


def valid_interval(value: Any, label: str = "interval") -> tuple[int, int]:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError(f"{label} must contain exactly two ticks")
    start = _integer(value[0], f"{label} start")
    end = _integer(value[1], f"{label} end")
    if start < 0 or end <= start:
        raise ValueError(f"{label} must satisfy 0 <= start < end")
    return start, end


def temporal_iou_fraction(left: Any, right: Any) -> Fraction:
    """Return exact temporal IoU after strict interval validation."""
    left_start, left_end = valid_interval(left, "left interval")
    right_start, right_end = valid_interval(right, "right interval")
    intersection = max(0, min(left_end, right_end) - max(left_start, right_start))
    union = max(left_end, right_end) - min(left_start, right_start)
    return Fraction(intersection, union)


def eligible_edges(
    predicted: Iterable[Any],
    truth: Iterable[Any],
    threshold: Fraction = THRESHOLD,
) -> list[list[tuple[int, Fraction]]]:
    predicted_rows = [valid_interval(row, "predicted interval") for row in predicted]
    truth_rows = [valid_interval(row, "truth interval") for row in truth]
    return [
        [
            (truth_index, score)
            for truth_index, truth_row in enumerate(truth_rows)
            if (score := temporal_iou_fraction(predicted_row, truth_row)) >= threshold
        ]
        for predicted_row in predicted_rows
    ]


def maximum_cardinality_matches(
    predicted: Iterable[Any],
    truth: Iterable[Any],
    threshold: Fraction = THRESHOLD,
) -> list[tuple[int, int, Fraction]]:
    """Find a deterministic maximum-cardinality one-to-one interval matching."""
    predicted_rows = [valid_interval(row, "predicted interval") for row in predicted]
    truth_rows = [valid_interval(row, "truth interval") for row in truth]
    adjacency = eligible_edges(predicted_rows, truth_rows, threshold)
    for neighbours in adjacency:
        neighbours.sort(key=lambda item: (item[1], item[0]), reverse=True)

    prediction_order = sorted(
        range(len(predicted_rows)),
        key=lambda index: (
            max((score for _, score in adjacency[index]), default=Fraction(-1, 1)),
            index,
        ),
        reverse=True,
    )
    truth_to_prediction: dict[int, int] = {}

    def augment(prediction: int, seen_truth: set[int]) -> bool:
        for truth_index, _score in adjacency[prediction]:
            if truth_index in seen_truth:
                continue
            seen_truth.add(truth_index)
            prior = truth_to_prediction.get(truth_index)
            if prior is None or augment(prior, seen_truth):
                truth_to_prediction[truth_index] = prediction
                return True
        return False

    for prediction in prediction_order:
        augment(prediction, set())

    matches = [
        (
            prediction,
            truth_index,
            temporal_iou_fraction(predicted_rows[prediction], truth_rows[truth_index]),
        )
        for truth_index, prediction in truth_to_prediction.items()
    ]
    return sorted(matches, key=lambda item: (item[2], item[0], item[1]), reverse=True)


def _sha_file(path: Path) -> dict[str, Any]:
    payload = path.read_bytes()
    return {"path": path.name, "bytes": len(payload), "sha256": sha256(payload).hexdigest()}


def _study_inventory(path: Path) -> dict[str, Any]:
    completion = verify_completed_experiment(path)
    receipt = json.loads((path / "experiment_receipt.json").read_text(encoding="utf-8"))
    snapshot = json.loads((path / "source_snapshot.json").read_text(encoding="utf-8"))
    artifacts = [_sha_file(path / name) for name in CORE_ARTIFACTS]
    snapshot_files = []
    for entry in snapshot["files"]:
        source = path / "source_snapshot" / entry["path"]
        current = _sha_file(source)
        snapshot_files.append({"path": entry["path"], **{key: current[key] for key in ("bytes", "sha256")}})
    return {
        "study": path.name,
        "path": str(path.resolve()),
        "receipt_sha256": sha256((path / "experiment_receipt.json").read_bytes()).hexdigest(),
        "completion_sha256": sha256((path / "completion_receipt.json").read_bytes()).hexdigest(),
        "case_cohort_sha256": receipt["case_cohort_sha256"],
        "source_snapshot_sha256": receipt["source_snapshot"]["snapshot_sha256"],
        "completion_status": completion["status"],
        "artifacts": artifacts,
        "snapshot_files": snapshot_files,
    }


def _recheck_study(inventory: dict[str, Any]) -> None:
    path = Path(inventory["path"])
    verify_completed_experiment(path)
    for entry in inventory["artifacts"]:
        current = _sha_file(path / entry["path"])
        if current != entry:
            raise ValueError(f"frozen study artifact changed: {path / entry['path']}")
    for entry in inventory["snapshot_files"]:
        current = _sha_file(path / "source_snapshot" / entry["path"])
        expected = {"path": Path(entry["path"]).name, "bytes": entry["bytes"], "sha256": entry["sha256"]}
        if current != expected:
            raise ValueError(f"frozen study snapshot changed: {path / 'source_snapshot' / entry['path']}")


def _truth_cohort(receipt: dict[str, Any]) -> dict[str, dict[str, Any]]:
    cohort = {}
    for row in receipt["case_cohort"]:
        if "truth_intervals" not in row:
            continue
        case_id = row.get("case_id")
        if not isinstance(case_id, str) or case_id in cohort:
            raise ValueError("invalid or duplicate truth cohort case ID")
        truth = [valid_interval(interval, f"{case_id} truth") for interval in row["truth_intervals"]]
        positive = row.get("positive")
        if not isinstance(positive, bool) or positive != bool(truth):
            raise ValueError(f"truth/positive mismatch for {case_id}")
        cohort[case_id] = {**row, "truth_intervals": truth}
    if not cohort:
        raise ValueError("study receipt has no truth-labelled cohort")
    return cohort


def _streams(raw: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    if isinstance(raw.get("cases"), list):
        cases = raw["cases"]
        method_sets = [set(row.get("methods", {})) for row in cases]
        if not method_sets or any(methods != method_sets[0] for methods in method_sets):
            raise ValueError("reference case method coverage differs")
        return {
            method: [row["methods"][method] for row in cases]
            for method in sorted(method_sets[0])
        }
    synthetic = raw.get("synthetic_rows")
    if not isinstance(synthetic, dict) or not synthetic:
        raise ValueError("unsupported melodic evaluation raw result shape")
    if all(isinstance(rows, list) for rows in synthetic.values()):
        return {str(method): rows for method, rows in sorted(synthetic.items())}
    streams = {}
    for algorithm, variants in sorted(synthetic.items()):
        if not isinstance(variants, dict):
            raise ValueError("mixed synthetic result shape")
        for variant, rows in sorted(variants.items()):
            if not isinstance(rows, list):
                raise ValueError("synthetic score stream must be a list")
            streams[f"{algorithm}/{variant}"] = rows
    return streams


def _truth_is_disjoint(truth: list[tuple[int, int]]) -> bool:
    ordered = sorted(truth)
    return all(left[1] <= right[0] for left, right in zip(ordered, ordered[1:]))


def _saved_matches(candidate: dict[str, Any], label: str) -> list[tuple[int, int, float]]:
    saved = candidate.get("truth_matches")
    if not isinstance(saved, list):
        raise ValueError(f"{label} truth_matches must be a list")
    result = []
    for index, row in enumerate(saved):
        if not isinstance(row, list) or len(row) != 3:
            raise ValueError(f"{label} truth match {index} is invalid")
        prediction = _integer(row[0], f"{label} predicted index")
        truth = _integer(row[1], f"{label} truth index")
        if not isinstance(row[2], (int, float)) or isinstance(row[2], bool):
            raise ValueError(f"{label} IoU must be numeric")
        result.append((prediction, truth, float(row[2])))
    return result


def _audit_score_row(
    row: dict[str, Any],
    case: dict[str, Any],
    context: dict[str, str],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    mismatches = []
    stats: Counter[str] = Counter()
    case_id = case["case_id"]

    def compare(field: str, saved: Any, expected: Any, *, candidate_rank: int | None = None) -> None:
        if saved != expected:
            mismatch = {**context, "case_id": case_id, "field": field, "saved": saved, "expected": expected}
            if candidate_rank is not None:
                mismatch["candidate_rank"] = candidate_rank
            mismatches.append(mismatch)

    for field in ("case_id", "split", "kind", "positive"):
        compare(field, row.get(field), case.get(field))
    truth = case["truth_intervals"]
    candidates = row.get("candidates")
    if not isinstance(candidates, list):
        raise ValueError(f"{case_id} candidates must be a list")
    flattened: list[tuple[int, int]] = []
    correct_ranks = []
    for rank, candidate in enumerate(candidates, 1):
        compare("candidate.rank", candidate.get("rank"), rank, candidate_rank=rank)
        intervals = [
            valid_interval(value, f"{case_id} candidate {rank} interval")
            for value in candidate.get("intervals", [])
        ]
        flattened.extend(intervals)
        edges = eligible_edges(intervals, truth)
        stats["predicted_intervals"] += len(intervals)
        stats["eligible_edges"] += sum(len(row_edges) for row_edges in edges)
        stats["predictions_with_multiple_truth_edges"] += sum(len(row_edges) > 1 for row_edges in edges)
        matches = maximum_cardinality_matches(intervals, truth)
        expected_saved = [
            (prediction, truth_index, round(float(iou), 8))
            for prediction, truth_index, iou in matches
        ]
        actual_saved = _saved_matches(candidate, f"{case_id} candidate {rank}")
        compare("candidate.truth_matches", actual_saved, expected_saved, candidate_rank=rank)
        correct = bool(truth) and len(matches) == len(truth)
        compare("candidate.correct_family", candidate.get("correct_family"), correct, candidate_rank=rank)
        if correct:
            correct_ranks.append(rank)
    recovery_rank = correct_ranks[0] if correct_ranks else None
    occurrence_edges = eligible_edges(flattened, truth)
    stats["flattened_predictions_with_multiple_truth_edges"] += sum(
        len(row_edges) > 1 for row_edges in occurrence_edges
    )
    occurrence_matches = maximum_cardinality_matches(flattened, truth)
    candidate_tp = int(recovery_rank is not None)
    expected = {
        "candidate_tp": candidate_tp,
        "candidate_fp": len(candidates) - candidate_tp,
        "candidate_fn": int(case["positive"] and not candidate_tp),
        "occurrence_tp": len(occurrence_matches),
        "occurrence_fp": len(flattened) - len(occurrence_matches),
        "occurrence_fn": len(truth) - len(occurrence_matches),
        "recovered": bool(candidate_tp),
        "recovery_rank": recovery_rank,
        "false_positive_case": not case["positive"] and bool(candidates),
    }
    for field, value in expected.items():
        compare(field, row.get(field), value)
    stats["score_rows"] = 1
    stats["candidates"] = len(candidates)
    stats["candidate_tp"] = candidate_tp
    stats["candidate_fp"] = expected["candidate_fp"]
    stats["candidate_fn"] = expected["candidate_fn"]
    stats["occurrence_tp"] = expected["occurrence_tp"]
    stats["occurrence_fp"] = expected["occurrence_fp"]
    stats["occurrence_fn"] = expected["occurrence_fn"]
    return mismatches, dict(stats)


def run(studies_root: Path, output: Path) -> dict[str, Any]:
    studies = {name: (studies_root / name).resolve() for name in STUDY_NAMES}
    inventories = [_study_inventory(studies[name]) for name in STUDY_NAMES]
    design = {
        "version": VERSION,
        "purpose": "independent arithmetic and assignment audit of frozen melodic evaluations",
        "studies": list(STUDY_NAMES),
        "iou_threshold": {"numerator": THRESHOLD.numerator, "denominator": THRESHOLD.denominator},
        "matching": "maximum-cardinality one-to-one bipartite matching with exact Fraction IoU",
        "claim_boundary": "metric arithmetic audit only; no human musical validation",
    }
    config = {
        "validate_saved_candidate_matches": True,
        "validate_row_metrics": True,
        "require_exact_stream_cohort_coverage": True,
        "require_disjoint_planted_truth": True,
    }
    receipt = prepare_experiment(
        output,
        design=design,
        config=config,
        cases=inventories,
        required_files=REQUIRED_FILES,
    )
    links = receipt_links(receipt)
    all_mismatches = []
    overlap_cases = []
    degree_violations = []
    study_summaries = {}
    total_stats: Counter[str] = Counter()

    for study_name in STUDY_NAMES:
        path = studies[study_name]
        source_receipt = json.loads((path / "experiment_receipt.json").read_text(encoding="utf-8"))
        raw = json.loads((path / "raw_results.json").read_text(encoding="utf-8"))
        cohort = _truth_cohort(source_receipt)
        for case_id, case in cohort.items():
            if not _truth_is_disjoint(case["truth_intervals"]):
                overlap_cases.append({"study": study_name, "case_id": case_id})
        streams = _streams(raw)
        stream_summaries = {}
        for stream_name, rows in streams.items():
            row_ids = [row.get("case_id") for row in rows]
            if len(row_ids) != len(set(row_ids)) or set(row_ids) != set(cohort):
                raise ValueError(f"score stream does not exactly cover cohort: {study_name}/{stream_name}")
            stream_stats: Counter[str] = Counter()
            stream_mismatches = 0
            for row in rows:
                case_id = row["case_id"]
                mismatches, stats = _audit_score_row(
                    row,
                    cohort[case_id],
                    {"study": study_name, "stream": stream_name},
                )
                all_mismatches.extend(mismatches)
                stream_mismatches += len(mismatches)
                stream_stats.update(stats)
                if stats.get("predictions_with_multiple_truth_edges"):
                    degree_violations.append({
                        "study": study_name,
                        "stream": stream_name,
                        "case_id": case_id,
                        "count": stats["predictions_with_multiple_truth_edges"],
                    })
            total_stats.update(stream_stats)
            stream_summaries[stream_name] = {
                **dict(stream_stats),
                "mismatch_count": stream_mismatches,
            }
        study_summaries[study_name] = {
            "truth_cohort_cases": len(cohort),
            "stream_count": len(streams),
            "streams": stream_summaries,
            "receipt_sha256": next(
                row["receipt_sha256"] for row in inventories if row["study"] == study_name
            ),
            "completion_sha256": next(
                row["completion_sha256"] for row in inventories if row["study"] == study_name
            ),
        }

    if overlap_cases:
        all_mismatches.extend(
            {**row, "field": "truth_intervals", "saved": "overlapping", "expected": "disjoint"}
            for row in overlap_cases
        )
    _recheck_studies = {row["study"]: row for row in inventories}
    for study_name in STUDY_NAMES:
        _recheck_study(_recheck_studies[study_name])

    raw_output = {
        **links,
        "version": VERSION,
        "mismatches": all_mismatches,
        "overlapping_truth_cases": overlap_cases,
        "predicted_interval_degree_violations": degree_violations,
    }
    aggregate = {
        **links,
        "version": VERSION,
        "passed": not all_mismatches and not degree_violations,
        "iou_threshold": "4/5",
        "study_count": len(STUDY_NAMES),
        "studies": study_summaries,
        "totals": dict(total_stats),
        "mismatch_count": len(all_mismatches),
        "overlapping_truth_case_count": len(overlap_cases),
        "predicted_interval_degree_violation_count": sum(row["count"] for row in degree_violations),
        "assignment_conclusion": (
            "Every frozen predicted interval had at most one eligible truth edge; the saved greedy "
            "assignment and independent maximum-cardinality assignment therefore have equal cardinality."
            if not degree_violations and not overlap_cases
            else "The frozen edge structure does not justify equivalence of greedy and maximum-cardinality assignment."
        ),
        "claim_boundary": "metric arithmetic and saved-coordinate audit, not musical validity",
    }
    atomic_json(output / "raw_results.json", raw_output)
    atomic_json(output / "aggregate.json", aggregate)
    complete_experiment(output)
    return aggregate


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--studies-root", type=Path, default=Path("research_local"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.studies_root, args.output), indent=2))


if __name__ == "__main__":
    main()
