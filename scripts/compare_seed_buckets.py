#!/usr/bin/env python3
"""Measure aligned indexed seed posting bucket sensitivity.

This experiment changes only ``AlignedConfig.max_bucket``. Synthetic scoring is
restricted to the existing development split. Real MIDI has no accuracy label
and is used only for paired output, telemetry and runtime comparisons.
"""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict, replace
from hashlib import sha256
import json
from pathlib import Path
import statistics
import time
from typing import Callable

from samuged.aligned import AlignedConfig
from samuged.aligned_indexed import extract_indexed
from samuged.evaluate import aggregate_results, generate_cases, score_case
from samuged.experiment import (
    canonical_json,
    complete_experiment,
    prepare_experiment,
    receipt_links,
    sha256_json,
    verify_completed_experiment,
)
from samuged.midi import load_midi


STUDY_VERSION = "seed-bucket-sensitivity-v1"
BUCKET_CAPS = (192, 768)
SYNTHETIC_CASES = 500
REAL_LIMITED_CASES = 23
REAL_CONTROL_CASES = 23
RUNTIME_LIMIT_SECONDS = 3600.0
PILOT_LIMITED_CASES = 6
PILOT_CONTROL_CASES = 6
PILOT_SYNTHETIC_CASES = 20
FALLBACK_LIMITED_CASES = 12
FALLBACK_CONTROL_CASES = 12
RESULT_ARTIFACTS = ("aggregate.json", "raw_results.json")
REQUIRED_FILES = (
    "scripts/compare_seed_buckets.py",
    "samuged/aligned.py",
    "samuged/aligned_indexed.py",
    "samuged/evaluate.py",
    "samuged/experiment.py",
    "samuged/metadata_recovery.py",
    "samuged/midi.py",
    "samuged/phrases.py",
    "pyproject.toml",
    "requirements-research.lock",
)
LIMIT_FLAGS = (
    "note_limit_reached",
    "window_limit_reached",
    "comparison_limit_reached",
    "group_limit_reached",
)


def _file_sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: dict) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        + "\n"
    )


def _hash_rank(source_path: str) -> str:
    return sha256(source_path.encode("utf-8")).hexdigest()


def _part_sum(record: dict, key: str) -> int:
    return sum(int(part.get(key, 0)) for part in record.get("part_stats", []))


def _other_limit_count(record: dict) -> int:
    return sum(bool(part.get(key)) for part in record.get("part_stats", []) for key in LIMIT_FLAGS)


def select_real_cohort(
    manifest: Path,
    *,
    limited_count: int = REAL_LIMITED_CASES,
    control_count: int = REAL_CONTROL_CASES,
) -> tuple[list[dict], dict]:
    """Select all seed limited pilot rows and hash ordered unlimited controls."""
    rows = [json.loads(line) for line in manifest.read_text().split("\n") if line.strip()]
    if len({row.get("source_path") for row in rows}) != len(rows):
        raise ValueError("pilot manifest contains duplicate source paths")
    usable = [row for row in rows if row.get("status") == "ok"]
    limited = [row for row in usable if row.get("search_limited") is True]
    if len(limited) != limited_count:
        raise ValueError(f"expected {limited_count} search limited pilot sources")
    invalid_limited = [
        row["source_path"]
        for row in limited
        if _part_sum(row, "saturated_seed_buckets") < 1 or _other_limit_count(row)
    ]
    if invalid_limited:
        raise ValueError("pilot search limits are not seed saturation only")
    unlimited = [row for row in usable if row.get("search_limited") is False]
    controls = sorted(unlimited, key=lambda row: (_hash_rank(row["source_path"]), row["source_path"]))[
        :control_count
    ]
    if len(controls) != control_count:
        raise ValueError(f"expected {control_count} unlimited pilot controls")

    def receipt(row: dict, group: str) -> dict:
        return {
            "case_id": f"real-{group}-{_hash_rank(row['source_path'])[:16]}",
            "cohort": f"fixed_real_{group}",
            "source_path": row["source_path"],
            "source_sha256": row["source_sha256"],
            "source_bytes": row["source_bytes"],
            "metadata_repairs": row.get("metadata_repairs", []),
            "pilot_seed_saturation": _part_sum(row, "saturated_seed_buckets"),
            "pilot_seed_postings_dropped": _part_sum(
                row, "saturated_seed_postings_dropped"
            ),
            "pilot_other_limit_count": _other_limit_count(row),
            "control_rank_sha256": _hash_rank(row["source_path"]),
        }

    cohort = [receipt(row, "limited") for row in sorted(limited, key=lambda row: row["source_path"])]
    cohort.extend(receipt(row, "control") for row in controls)
    cause = {
        "pilot_rows": len(rows),
        "pilot_search_limited_rows": len(limited),
        "limited_rows_with_seed_saturation": sum(
            _part_sum(row, "saturated_seed_buckets") > 0 for row in limited
        ),
        "limited_rows_with_other_limit_flags": sum(_other_limit_count(row) > 0 for row in limited),
        "limited_saturated_seed_buckets": sum(
            _part_sum(row, "saturated_seed_buckets") for row in limited
        ),
        "limited_seed_postings_dropped": sum(
            _part_sum(row, "saturated_seed_postings_dropped") for row in limited
        ),
        "comparison_limit_parts": sum(
            bool(part.get("comparison_limit_reached"))
            for row in limited
            for part in row.get("part_stats", [])
        ),
        "control_rule": "first 23 unlimited rows by SHA256(source_path), then source_path",
    }
    return cohort, cause


def development_cases(count: int = SYNTHETIC_CASES) -> list:
    cases = [case for case in generate_cases(count * 2) if case.split == "development"]
    if len(cases) != count or any(case.split != "development" for case in cases):
        raise ValueError("development cohort construction differs from the frozen design")
    return cases


def configs() -> dict[int, AlignedConfig]:
    baseline = AlignedConfig()
    return {cap: replace(baseline, max_bucket=cap) for cap in BUCKET_CAPS}


def _identity(phrase: dict) -> dict:
    return {
        "family_id": phrase["family_id"],
        "part_index": phrase["part_index"],
        "start_tick": phrase["start_tick"],
        "end_tick": phrase["end_tick"],
        "note_count": phrase["note_count"],
        "occurrences": [
            {
                "start_tick": row["start_tick"],
                "end_tick": row["end_tick"],
                "note_index": row["note_index"],
                "note_count": row["note_count"],
            }
            for row in phrase["occurrences"]
        ],
    }


def _phrase_rows(phrases: list[dict]) -> list[dict]:
    return [
        {
            **_identity(phrase),
            "recurrence_score": phrase["recurrence_score"],
            "occurrence_count": phrase["occurrence_count"],
            "semantic_sha256": sha256_json(_identity(phrase)),
        }
        for phrase in phrases
    ]


def compare_outputs(low: dict, high: dict) -> dict:
    low_rows = _phrase_rows(low["phrases"])
    high_rows = _phrase_rows(high["phrases"])
    low_hashes = [row["semantic_sha256"] for row in low_rows]
    high_hashes = [row["semantic_sha256"] for row in high_rows]
    low_rank = {value: rank for rank, value in enumerate(low_hashes, 1)}
    high_rank = {value: rank for rank, value in enumerate(high_hashes, 1)}
    shared = sorted(set(low_rank) & set(high_rank))
    return {
        "exact_phrase_output_equal": canonical_json(low["phrases"]) == canonical_json(high["phrases"]),
        "semantic_sequence_equal": low_hashes == high_hashes,
        "semantic_set_equal": set(low_hashes) == set(high_hashes),
        "top1_equal": low_hashes[:1] == high_hashes[:1],
        "shared_rank_changes": [
            {"semantic_sha256": value, "baseline_rank": low_rank[value], "wide_rank": high_rank[value]}
            for value in shared
            if low_rank[value] != high_rank[value]
        ],
        "baseline_only": [row for row in low_rows if row["semantic_sha256"] not in high_rank],
        "wide_only": [row for row in high_rows if row["semantic_sha256"] not in low_rank],
    }


def telemetry(result: dict) -> dict:
    parts = result["part_stats"]
    sums = (
        "windows_considered",
        "windows",
        "comparisons",
        "proposed_pairs",
        "dp_calls",
        "groups",
        "repeat_groups",
        "seed_index_keys",
        "seed_index_postings",
        "posting_entries_visited",
        "saturated_seed_buckets",
        "saturated_seed_postings_dropped",
        "candidates_truncated",
    )
    key_types: Counter[str] = Counter()
    for part in parts:
        key_types.update(part.get("saturated_seed_key_types", {}))
    return {
        "parts": len(parts),
        "candidate_count": result["candidate_count"],
        "raw_repeat_group_count": result["raw_repeat_group_count"],
        "search_limited": result["search_limited"],
        "curation_truncated": result["curation_truncated"],
        **{key: sum(int(part.get(key, 0)) for part in parts) for key in sums},
        "max_seed_bucket_size": max((int(part.get("max_seed_bucket_size", 0)) for part in parts), default=0),
        "saturated_seed_key_types": dict(sorted(key_types.items())),
        "limit_part_counts": {
            key: sum(bool(part.get(key)) for part in parts) for key in LIMIT_FLAGS
        },
    }


def _variant(result: dict, elapsed: float, case=None) -> dict:
    row = {
        "runtime_seconds": round(elapsed, 8),
        "phrases_sha256": sha256_json(result["phrases"]),
        "phrases": _phrase_rows(result["phrases"]),
        "telemetry": telemetry(result),
    }
    if case is not None:
        row["development_score"] = score_case(case, result["phrases"], elapsed)
    return row


def run_pair(
    song,
    case_configs: dict[int, AlignedConfig],
    order: tuple[int, int],
    *,
    case=None,
    detector: Callable = extract_indexed,
) -> dict:
    results: dict[int, dict] = {}
    variants = {}
    for cap in order:
        started = time.monotonic()
        result = detector(song, case_configs[cap])
        elapsed = time.monotonic() - started
        results[cap] = result
        variants[str(cap)] = _variant(result, elapsed, case)
    return {
        "execution_order": list(order),
        "variants": variants,
        "comparison": compare_outputs(results[192], results[768]),
    }


def _sum_telemetry(rows: list[dict], cap: int) -> dict:
    telemetry_rows = [row["variants"][str(cap)]["telemetry"] for row in rows]
    sum_keys = (
        "candidate_count",
        "raw_repeat_group_count",
        "windows_considered",
        "windows",
        "comparisons",
        "proposed_pairs",
        "dp_calls",
        "groups",
        "repeat_groups",
        "seed_index_keys",
        "seed_index_postings",
        "posting_entries_visited",
        "saturated_seed_buckets",
        "saturated_seed_postings_dropped",
        "candidates_truncated",
    )
    key_types: Counter[str] = Counter()
    for row in telemetry_rows:
        key_types.update(row["saturated_seed_key_types"])
    return {
        **{key: sum(row[key] for row in telemetry_rows) for key in sum_keys},
        "search_limited_cases": sum(row["search_limited"] for row in telemetry_rows),
        "curation_truncated_cases": sum(row["curation_truncated"] for row in telemetry_rows),
        "max_seed_bucket_size": max((row["max_seed_bucket_size"] for row in telemetry_rows), default=0),
        "saturated_seed_key_types": dict(sorted(key_types.items())),
        "limit_part_counts": {
            key: sum(row["limit_part_counts"][key] for row in telemetry_rows)
            for key in LIMIT_FLAGS
        },
    }


def _aggregate(rows: list[dict], *, labelled: bool) -> dict:
    result = {
        "cases": len(rows),
        "exact_output_changes": sum(not row["comparison"]["exact_phrase_output_equal"] for row in rows),
        "semantic_sequence_changes": sum(not row["comparison"]["semantic_sequence_equal"] for row in rows),
        "semantic_set_changes": sum(not row["comparison"]["semantic_set_equal"] for row in rows),
        "top1_changes": sum(not row["comparison"]["top1_equal"] for row in rows),
        "shared_rank_changes": sum(len(row["comparison"]["shared_rank_changes"]) for row in rows),
        "baseline_only_selected": sum(len(row["comparison"]["baseline_only"]) for row in rows),
        "wide_only_selected": sum(len(row["comparison"]["wide_only"]) for row in rows),
        "variants": {},
    }
    for cap in BUCKET_CAPS:
        elapsed = [row["variants"][str(cap)]["runtime_seconds"] for row in rows]
        variant = {
            "runtime_seconds": {
                "total": round(sum(elapsed), 8),
                "mean": round(statistics.mean(elapsed), 8) if elapsed else 0.0,
                "median": round(statistics.median(elapsed), 8) if elapsed else 0.0,
                "maximum": round(max(elapsed), 8) if elapsed else 0.0,
            },
            "telemetry": _sum_telemetry(rows, cap),
        }
        if labelled:
            scores = [row["variants"][str(cap)]["development_score"] for row in rows]
            variant["development_score"] = aggregate_results(scores)
        result["variants"][str(cap)] = variant
    baseline_total = result["variants"]["192"]["runtime_seconds"]["total"]
    wide_total = result["variants"]["768"]["runtime_seconds"]["total"]
    result["runtime_total_ratio"] = round(wide_total / baseline_total, 8) if baseline_total else None
    if labelled:
        recovery = Counter()
        for row in rows:
            low = row["variants"]["192"]["development_score"]
            high = row["variants"]["768"]["development_score"]
            if low["recovery_rank"] is None and high["recovery_rank"] is not None:
                recovery["newly_recovered"] += 1
            elif low["recovery_rank"] is not None and high["recovery_rank"] is None:
                recovery["lost_recovery"] += 1
            elif low["recovery_rank"] != high["recovery_rank"]:
                recovery["rank_changed"] += 1
            else:
                recovery["unchanged"] += 1
        result["development_recovery_deltas"] = dict(sorted(recovery.items()))
    return result


def _validate_sources(source: Path, cohort: list[dict]) -> None:
    for row in cohort:
        path = (source / row["source_path"]).resolve(strict=True)
        if not path.is_relative_to(source.resolve(strict=True)):
            raise ValueError("pilot source path escapes source root")
        if path.stat().st_size != row["source_bytes"] or _file_sha256(path) != row["source_sha256"]:
            raise ValueError(f"pilot source changed: {row['source_path']}")


def _run_real_case(source: Path, row: dict, case_configs, index: int, detector) -> dict:
    path = source / row["source_path"]
    song = load_midi(path, recover_invalid_keys=bool(row["metadata_repairs"]))
    if song.metadata_repairs != row["metadata_repairs"]:
        raise ValueError(f"metadata repairs changed: {row['source_path']}")
    pair = run_pair(
        song,
        case_configs,
        BUCKET_CAPS if index % 2 == 0 else tuple(reversed(BUCKET_CAPS)),
        detector=detector,
    )
    return {**row, **pair}


def _project_runtime(pilot_real: list[dict], pilot_synthetic: list[dict], real_count: int, synthetic_count: int) -> float:
    real_seconds = sum(
        variant["runtime_seconds"]
        for row in pilot_real
        for variant in row["variants"].values()
    )
    synthetic_seconds = sum(
        variant["runtime_seconds"]
        for row in pilot_synthetic
        for variant in row["variants"].values()
    )
    return (
        real_seconds / max(1, len(pilot_real)) * real_count
        + synthetic_seconds / max(1, len(pilot_synthetic)) * synthetic_count
    )


def run(
    source: Path,
    manifest: Path,
    output: Path,
    *,
    synthetic_count: int = SYNTHETIC_CASES,
    limited_count: int = REAL_LIMITED_CASES,
    control_count: int = REAL_CONTROL_CASES,
    detector: Callable = extract_indexed,
) -> dict:
    source = source.resolve(strict=True)
    manifest = manifest.resolve(strict=True)
    output = output.resolve()
    real_cohort, pilot_cause = select_real_cohort(
        manifest, limited_count=limited_count, control_count=control_count
    )
    _validate_sources(source, real_cohort)
    synthetic = development_cases(synthetic_count)
    case_configs = configs()
    differing = [
        key
        for key in asdict(case_configs[192])
        if getattr(case_configs[192], key) != getattr(case_configs[768], key)
    ]
    if differing != ["max_bucket"]:
        raise ValueError("seed bucket variants differ in more than max_bucket")

    pilot_real_ids = [
        row["case_id"]
        for group in ("fixed_real_limited", "fixed_real_control")
        for row in [item for item in real_cohort if item["cohort"] == group][
            : (PILOT_LIMITED_CASES if group.endswith("limited") else PILOT_CONTROL_CASES)
        ]
    ]
    pilot_synthetic_ids = [case.case_id for case in synthetic[: min(PILOT_SYNTHETIC_CASES, len(synthetic))]]
    fallback_real_ids = [
        row["case_id"]
        for group in ("fixed_real_limited", "fixed_real_control")
        for row in [item for item in real_cohort if item["cohort"] == group][
            : (FALLBACK_LIMITED_CASES if group.endswith("limited") else FALLBACK_CONTROL_CASES)
        ]
    ]
    design = {
        "study_version": STUDY_VERSION,
        "question": "sensitivity to the aligned indexed seed posting bucket cap",
        "changed_field": "AlignedConfig.max_bucket",
        "bucket_caps": list(BUCKET_CAPS),
        "fixed_fields": {
            "max_candidates": 80,
            "max_comparisons": 2000,
            "top_k": 3,
            "detector": "samuged.aligned_indexed.extract_indexed",
        },
        "synthetic_scope": "500 existing development cases from generate_cases(1000); no test cases",
        "real_scope": "all 23 seed limited pilot files and 23 SHA256 selected unlimited controls",
        "runtime_guard": {
            "limit_seconds": RUNTIME_LIMIT_SECONDS,
            "pilot_real_case_ids": pilot_real_ids,
            "pilot_synthetic_case_ids": pilot_synthetic_ids,
            "fallback_real_case_ids": fallback_real_ids,
            "rule": "use the fallback real IDs when pilot projected paired detector time exceeds 3600 seconds",
        },
        "result_artifacts": list(RESULT_ARTIFACTS),
        "claim_boundary": "synthetic planted recurrence and unlabelled real output sensitivity, not musical quality or human response",
    }
    frozen_config = {
        str(cap): asdict(config) for cap, config in sorted(case_configs.items())
    }
    frozen_config["input_receipts"] = {
        "pilot_manifest": manifest.as_posix(),
        "pilot_manifest_sha256": _file_sha256(manifest),
        "source_root": source.as_posix(),
    }
    receipt = prepare_experiment(
        output,
        design=design,
        config=frozen_config,
        cases=[*synthetic, *real_cohort],
        required_files=REQUIRED_FILES,
    )
    links = receipt_links(receipt)

    real_by_id = {row["case_id"]: row for row in real_cohort}
    synthetic_by_id = {case.case_id: case for case in synthetic}
    pilot_real = [
        _run_real_case(source, real_by_id[case_id], case_configs, index, detector)
        for index, case_id in enumerate(pilot_real_ids)
    ]
    pilot_synthetic = []
    for index, case_id in enumerate(pilot_synthetic_ids):
        case = synthetic_by_id[case_id]
        pilot_synthetic.append(
            {
                "case_id": case.case_id,
                "cohort": "development",
                **run_pair(
                    case.song,
                    case_configs,
                    BUCKET_CAPS if index % 2 == 0 else tuple(reversed(BUCKET_CAPS)),
                    case=case,
                    detector=detector,
                ),
            }
        )
    projected = _project_runtime(pilot_real, pilot_synthetic, len(real_cohort), len(synthetic))
    if projected > RUNTIME_LIMIT_SECONDS:
        evaluated_real = [real_by_id[case_id] for case_id in fallback_real_ids]
        real_scope = "predeclared_runtime_fallback"
    else:
        evaluated_real = real_cohort
        real_scope = "full_predeclared_cohort"

    rows = []
    for index, case in enumerate(synthetic):
        rows.append(
            {
                "case_id": case.case_id,
                "cohort": "development",
                "kind": case.kind,
                "rng_seed": case.rng_seed,
                **run_pair(
                    case.song,
                    case_configs,
                    BUCKET_CAPS if index % 2 == 0 else tuple(reversed(BUCKET_CAPS)),
                    case=case,
                    detector=detector,
                ),
            }
        )
        if (index + 1) % 100 == 0:
            print(json.dumps({"synthetic_processed": index + 1, "synthetic_total": len(synthetic)}), flush=True)
    for index, row in enumerate(evaluated_real):
        rows.append(_run_real_case(source, row, case_configs, index, detector))
        if (index + 1) % 8 == 0 or index + 1 == len(evaluated_real):
            print(json.dumps({"real_processed": index + 1, "real_total": len(evaluated_real)}), flush=True)

    raw = {
        **links,
        "study_version": STUDY_VERSION,
        "runtime_pilot": {
            "real_rows": pilot_real,
            "synthetic_rows": pilot_synthetic,
            "projected_paired_detector_seconds": round(projected, 8),
            "limit_seconds": RUNTIME_LIMIT_SECONDS,
            "selected_real_scope": real_scope,
        },
        "rows": rows,
    }
    _write_json(output / "raw_results.json", raw)
    groups = {
        name: _aggregate([row for row in rows if row["cohort"] == name], labelled=name == "development")
        for name in ("development", "fixed_real_limited", "fixed_real_control")
    }
    aggregate = {
        **links,
        "study_version": STUDY_VERSION,
        "pilot_cause": pilot_cause,
        "runtime_guard": {
            "projected_paired_detector_seconds": round(projected, 8),
            "limit_seconds": RUNTIME_LIMIT_SECONDS,
            "selected_real_scope": real_scope,
            "evaluated_real_cases": len(evaluated_real),
        },
        "groups": groups,
        "interpretation": (
            "real files have no accuracy labels; selected output changes show cap sensitivity only"
        ),
    }
    _write_json(output / "aggregate.json", aggregate)
    complete_experiment(output)
    verify_completed_experiment(output)
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
