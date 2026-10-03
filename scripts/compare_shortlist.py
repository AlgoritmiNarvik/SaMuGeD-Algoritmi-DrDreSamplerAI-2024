"""Frozen development sensitivity study for the per-part melodic shortlist cap.

This experiment compares caps of 80 and 400 without changing any other
detector setting. Synthetic scores use development cases only. The fixed real
MIDI cohort is unlabelled and is used only for paired output and telemetry
comparisons.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, replace
import json
from pathlib import Path
import statistics
import time
from typing import Callable

from samuged.aligned import AlignedConfig
from samuged.aligned_indexed import extract_indexed
from samuged.dataset import atomic_json, file_digest
from samuged.evaluate import aggregate_results, generate_cases, score_case
from samuged.experiment import (
    complete_experiment,
    prepare_experiment,
    receipt_links,
    sha256_json,
)
from samuged.midi import load_midi
from samuged.phrases import Config, extract


STUDY_VERSION = "shortlist-sensitivity-v1"
CAPS = (80, 400)
ALGORITHMS = ("reference_approximate", "aligned_indexed")
OVERLAP_THRESHOLD = 0.7
REQUIRED_FILES = (
    "scripts/compare_shortlist.py",
    "samuged/aligned.py",
    "samuged/aligned_indexed.py",
    "samuged/dataset.py",
    "samuged/evaluate.py",
    "samuged/experiment.py",
    "samuged/metadata_recovery.py",
    "samuged/midi.py",
    "samuged/phrases.py",
    "pyproject.toml",
    "requirements-research.lock",
)


def _overlap_fraction(left: dict, right: dict) -> float:
    """Fraction of left occurrences covered by a right occurrence.

    Coverage uses overlap divided by the shorter interval. It is a structural
    nesting diagnostic, not a judgement that either family is incorrect.
    """
    occurrences = left.get("occurrences", [])
    if not occurrences or left.get("part_index") != right.get("part_index"):
        return 0.0
    covered = 0
    for first in occurrences:
        first_length = max(1, first["end_tick"] - first["start_tick"])
        for second in right.get("occurrences", []):
            second_length = max(1, second["end_tick"] - second["start_tick"])
            overlap = max(
                0,
                min(first["end_tick"], second["end_tick"])
                - max(first["start_tick"], second["start_tick"]),
            )
            if overlap / min(first_length, second_length) >= OVERLAP_THRESHOLD:
                covered += 1
                break
    return covered / len(occurrences)


def diversity_summary(phrases: list[dict]) -> dict:
    """Describe selected-family variety without assigning musical quality."""
    pair_coverages = []
    overlapping_pairs = 0
    for index, left in enumerate(phrases):
        for right in phrases[index + 1 :]:
            if left.get("part_index") != right.get("part_index"):
                continue
            coverage = max(_overlap_fraction(left, right), _overlap_fraction(right, left))
            pair_coverages.append(coverage)
            overlapping_pairs += coverage >= OVERLAP_THRESHOLD
    return {
        "selected_family_count": len(phrases),
        "unique_family_id_count": len({row["family_id"] for row in phrases}),
        "unique_part_count": len({row.get("part_index") for row in phrases}),
        "unique_note_count_count": len({row.get("note_count") for row in phrases}),
        "same_part_family_pairs": len(pair_coverages),
        "overlapping_family_pairs": overlapping_pairs,
        "mean_pair_overlap_coverage": (
            round(statistics.mean(pair_coverages), 8) if pair_coverages else 0.0
        ),
        "maximum_pair_overlap_coverage": round(max(pair_coverages, default=0.0), 8),
    }


def _telemetry(result: dict) -> dict:
    parts = result["part_stats"]
    limit_names = (
        "candidate_limit_reached",
        "comparison_limit_reached",
        "group_limit_reached",
        "note_limit_reached",
        "window_limit_reached",
    )
    return {
        "candidate_count": result["candidate_count"],
        "raw_repeat_group_count": result["raw_repeat_group_count"],
        "curation_truncated": result["curation_truncated"],
        "search_limited": result["search_limited"],
        "parts": len(parts),
        "parts_at_candidate_cap": sum(bool(row.get("candidate_limit_reached")) for row in parts),
        "candidates_truncated": sum(row.get("candidates_truncated", 0) for row in parts),
        "comparisons": sum(row.get("comparisons", 0) for row in parts),
        "windows_considered": sum(row.get("windows_considered", 0) for row in parts),
        "saturated_seed_buckets": sum(row.get("saturated_seed_buckets", 0) for row in parts),
        "limit_part_counts": {
            name: sum(bool(row.get(name)) for row in parts) for name in limit_names
        },
    }


def compare_outputs(low: dict, high: dict) -> dict:
    """Return paired output changes at the user-visible selected-family level."""
    low_phrases, high_phrases = low["phrases"], high["phrases"]
    low_ids = [row["family_id"] for row in low_phrases]
    high_ids = [row["family_id"] for row in high_phrases]
    return {
        "phrases_equal": low_phrases == high_phrases,
        "family_id_sequence_equal": low_ids == high_ids,
        "top1_equal": (low_ids[:1] == high_ids[:1]),
        "low_only_family_ids": sorted(set(low_ids) - set(high_ids)),
        "high_only_family_ids": sorted(set(high_ids) - set(low_ids)),
        "selected_family_count_delta": len(high_phrases) - len(low_phrases),
        "diversity_changed": diversity_summary(low_phrases) != diversity_summary(high_phrases),
    }


def _variant(result: dict, elapsed: float, score: dict | None) -> dict:
    phrases = result["phrases"]
    row = {
        "runtime_seconds": round(elapsed, 8),
        "phrases_sha256": sha256_json(phrases),
        "family_ids": [phrase["family_id"] for phrase in phrases],
        "diversity": diversity_summary(phrases),
        "telemetry": _telemetry(result),
    }
    if score is not None:
        row["score"] = score
    return row


def _rank_summary(scores: list[dict]) -> dict:
    ranks = [row["recovery_rank"] for row in scores if row["recovery_rank"] is not None]
    return {
        "recovery_rank_counts": {
            str(rank): sum(value == rank for value in ranks) for rank in range(1, 4)
        },
        "unrecovered_positive_cases": sum(
            row["positive"] and row["recovery_rank"] is None for row in scores
        ),
        "mean_recovery_rank_when_recovered": (
            round(statistics.mean(ranks), 8) if ranks else None
        ),
    }


def _paired_runtime(rows: list[dict]) -> dict:
    low = [row["variants"]["80"]["runtime_seconds"] for row in rows]
    high = [row["variants"]["400"]["runtime_seconds"] for row in rows]
    differences = [right - left for left, right in zip(low, high)]
    ratios = [right / left for left, right in zip(low, high) if left > 0]
    return {
        "cap80_total_seconds": round(sum(low), 8),
        "cap400_total_seconds": round(sum(high), 8),
        "paired_difference_mean_seconds": round(statistics.mean(differences), 8),
        "paired_difference_median_seconds": round(statistics.median(differences), 8),
        "paired_ratio_median": round(statistics.median(ratios), 8) if ratios else None,
    }


def _aggregate_group(rows: list[dict], labelled: bool) -> dict:
    result = {
        "cases": len(rows),
        "identical_phrase_outputs": sum(row["comparison"]["phrases_equal"] for row in rows),
        "changed_phrase_outputs": sum(not row["comparison"]["phrases_equal"] for row in rows),
        "changed_family_id_sequences": sum(
            not row["comparison"]["family_id_sequence_equal"] for row in rows
        ),
        "changed_top1": sum(not row["comparison"]["top1_equal"] for row in rows),
        "changed_diversity": sum(row["comparison"]["diversity_changed"] for row in rows),
        "runtime": _paired_runtime(rows),
        "variants": {},
    }
    for cap in CAPS:
        label = str(cap)
        variants = [row["variants"][label] for row in rows]
        diversity = [row["diversity"] for row in variants]
        telemetry = [row["telemetry"] for row in variants]
        cap_result = {
            "selected_family_count_total": sum(row["selected_family_count"] for row in diversity),
            "selected_family_count_mean": round(
                statistics.mean(row["selected_family_count"] for row in diversity), 8
            ) if diversity else 0.0,
            "overlapping_family_pairs_total": sum(
                row["overlapping_family_pairs"] for row in diversity
            ),
            "mean_pair_overlap_coverage_across_cases": round(
                statistics.mean(row["mean_pair_overlap_coverage"] for row in diversity), 8
            ) if diversity else 0.0,
            "curation_truncated_cases": sum(row["curation_truncated"] for row in telemetry),
            "search_limited_cases": sum(row["search_limited"] for row in telemetry),
            "parts_at_candidate_cap": sum(row["parts_at_candidate_cap"] for row in telemetry),
            "candidates_truncated": sum(row["candidates_truncated"] for row in telemetry),
            "comparisons": sum(row["comparisons"] for row in telemetry),
            "windows_considered": sum(row["windows_considered"] for row in telemetry),
            "saturated_seed_buckets": sum(row["saturated_seed_buckets"] for row in telemetry),
            "limit_part_counts": {
                name: sum(row["limit_part_counts"][name] for row in telemetry)
                for name in telemetry[0]["limit_part_counts"]
            } if telemetry else {},
        }
        if labelled:
            scores = [row["score"] for row in variants]
            cap_result["development_score"] = aggregate_results(scores)
            cap_result["ranking"] = _rank_summary(scores)
        result["variants"][label] = cap_result
    return result


def _configs() -> dict[str, dict[int, Config | AlignedConfig]]:
    return {
        "reference_approximate": {
            cap: replace(Config(), max_candidates=cap) for cap in CAPS
        },
        "aligned_indexed": {
            cap: replace(AlignedConfig(), max_candidates=cap) for cap in CAPS
        },
    }


def _run_pair(
    algorithm: str,
    song,
    configs: dict[int, Config | AlignedConfig],
    order: tuple[int, int],
    case=None,
    detectors: dict[str, Callable] | None = None,
) -> tuple[dict, dict]:
    functions = detectors or {
        "reference_approximate": extract,
        "aligned_indexed": extract_indexed,
    }
    results, variants = {}, {}
    for cap in order:
        started = time.monotonic()
        result = functions[algorithm](song, configs[cap])
        elapsed = time.monotonic() - started
        score = score_case(case, result["phrases"], elapsed) if case is not None else None
        results[cap] = result
        variants[str(cap)] = _variant(result, elapsed, score)
    comparison = compare_outputs(results[80], results[400])
    if not comparison["phrases_equal"]:
        comparison["changed_phrases"] = {
            str(cap): results[cap]["phrases"] for cap in CAPS
        }
    return variants, comparison


def run(
    source: Path,
    manifest: Path,
    output: Path,
    *,
    case_count: int = 1000,
    expected_real_sources: int = 128,
    detectors: dict[str, Callable] | None = None,
) -> dict:
    cases = [case for case in generate_cases(case_count) if case.split == "development"]
    if case_count == 1000 and len(cases) != 500:
        raise ValueError("frozen development cohort must contain exactly 500 cases")
    source_rows = [json.loads(line) for line in manifest.read_text(encoding="utf-8").splitlines() if line]
    if len(source_rows) != expected_real_sources:
        raise ValueError(f"expected {expected_real_sources} fixed real sources")
    if len({row["source_path"] for row in source_rows}) != len(source_rows):
        raise ValueError("real source manifest contains duplicate paths")
    if any(row.get("status") != "ok" for row in source_rows):
        raise ValueError("real source manifest must contain only successful sources")

    real_cohort = []
    for row in source_rows:
        path = source / row["source_path"]
        if not path.is_file() or file_digest(path) != row["source_sha256"]:
            raise ValueError(f"pilot source changed: {row['source_path']}")
        real_cohort.append({
            "case_id": f"real:{row['source_path']}",
            "kind": "fixed_real_source",
            "source_path": row["source_path"],
            "source_sha256": row["source_sha256"],
            "metadata_repairs": row.get("metadata_repairs", []),
        })

    configs = _configs()
    design = {
        "version": STUDY_VERSION,
        "purpose": "development sensitivity of the per-part melodic candidate shortlist cap",
        "synthetic_generator_count": case_count,
        "synthetic_split": "development",
        "synthetic_cases": len(cases),
        "real_source_manifest": str(manifest),
        "real_source_manifest_sha256": file_digest(manifest),
        "real_sources": len(real_cohort),
        "algorithms": list(ALGORITHMS),
        "shortlist_caps": list(CAPS),
        "top_k": 3,
        "paired_order": "alternating by case index and algorithm to reduce fixed first-run bias",
        "real_labels": False,
        "test_split_used": False,
        "external_human_labels_used": False,
        "decision_policy": "report sensitivity only; do not select or tune a production default",
        "claim_boundary": (
            "synthetic development recovery and unlabelled real output sensitivity; "
            "not musical quality, memorability or held-out accuracy"
        ),
    }
    frozen_config = {
        algorithm: {str(cap): asdict(configs[algorithm][cap]) for cap in CAPS}
        for algorithm in ALGORITHMS
    }
    receipt = prepare_experiment(
        output,
        design=design,
        config=frozen_config,
        cases=[*cases, *real_cohort],
        required_files=REQUIRED_FILES,
    )
    links = receipt_links(receipt)
    rows = []
    total = len(cases) + len(real_cohort)
    processed = 0

    for index, case in enumerate(cases):
        for algorithm_index, algorithm in enumerate(ALGORITHMS):
            low_first = (index + algorithm_index) % 2 == 0
            order = CAPS if low_first else tuple(reversed(CAPS))
            variants, comparison = _run_pair(
                algorithm, case.song, configs[algorithm], order, case, detectors
            )
            rows.append({
                "case_id": case.case_id,
                "cohort": "development",
                "algorithm": algorithm,
                "execution_order": list(order),
                "variants": variants,
                "comparison": comparison,
            })
        processed += 1
        if processed % 25 == 0:
            print(json.dumps({"items_processed": processed, "total": total}), flush=True)

    for source_index, cohort_row in enumerate(real_cohort):
        manifest_row = source_rows[source_index]
        path = source / cohort_row["source_path"]
        song = load_midi(path, recover_invalid_keys=bool(cohort_row["metadata_repairs"]))
        if song.metadata_repairs != cohort_row["metadata_repairs"]:
            raise ValueError(f"metadata repair receipt changed: {cohort_row['source_path']}")
        for algorithm_index, algorithm in enumerate(ALGORITHMS):
            global_index = len(cases) + source_index
            low_first = (global_index + algorithm_index) % 2 == 0
            order = CAPS if low_first else tuple(reversed(CAPS))
            variants, comparison = _run_pair(
                algorithm, song, configs[algorithm], order, detectors=detectors
            )
            rows.append({
                "case_id": cohort_row["case_id"],
                "cohort": "fixed_real",
                "algorithm": algorithm,
                "execution_order": list(order),
                "source_sha256": cohort_row["source_sha256"],
                "variants": variants,
                "comparison": comparison,
            })
        processed += 1
        if processed % 16 == 0 or processed == total:
            print(json.dumps({"items_processed": processed, "total": total}), flush=True)

    raw = {**links, "study_version": STUDY_VERSION, "rows": rows}
    atomic_json(output / "raw_results.json", raw)
    groups = {}
    for algorithm in ALGORITHMS:
        groups[algorithm] = {
            "development": _aggregate_group(
                [row for row in rows if row["algorithm"] == algorithm and row["cohort"] == "development"],
                labelled=True,
            ),
            "fixed_real": _aggregate_group(
                [row for row in rows if row["algorithm"] == algorithm and row["cohort"] == "fixed_real"],
                labelled=False,
            ),
        }
    aggregate = {
        **links,
        "study_version": STUDY_VERSION,
        "groups": groups,
        "interpretation_rule": (
            "the cap is output-material only when selected phrase outputs differ; "
            "candidate-limit telemetry alone records shortlist saturation"
        ),
    }
    atomic_json(output / "aggregate.json", aggregate)
    complete_experiment(output)
    return aggregate


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.source, args.manifest, args.output), indent=2))


if __name__ == "__main__":
    main()
