"""Frozen comparison of the reference and insertion tolerant detectors.

The planted benchmark measures symbolic recurrence against known source
intervals. The real MIDI pilot measures runtime and search limits only. It has
no phrase annotations and therefore provides no accuracy estimate.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
from hashlib import sha256
import importlib.util
import json
import math
from pathlib import Path
import random
import statistics
import sys
import time
from types import ModuleType
from typing import Iterable

from .aligned import AlignedConfig, extract_aligned
from .evaluate import (
    CASE_KINDS,
    IOU_THRESHOLD,
    aggregate_results,
    benchmark_design,
    generate_cases,
    score_case,
)
from .experiment import complete_experiment, prepare_experiment, receipt_links
from .midi import load_midi


COMPARISON_VERSION = "aligned-reference-frozen-v1"
REFERENCE_SOURCE = Path("research_local/lakh_phrases_v02/provenance/samuged/phrases.py")
REAL_MANIFEST = Path("research_local/pilot_both_v03/sources.jsonl")
REAL_ROOT = Path("datasets/Lakh MIDI Clean")
METHODS = ("reference_approximate", "aligned")
LIMIT_KEYS = (
    "note_limit_reached",
    "window_limit_reached",
    "comparison_limit_reached",
    "group_limit_reached",
)
PROFILE_KEYS = (
    "comparisons",
    "proposed_pairs",
    "seed_support_rejections",
    "exact_signature_hits",
    "alignment_cache_hits",
    "dp_calls",
    "overlap_rejections",
    "length_rejections",
    "terminal_timing_rejections",
    "timing_feasibility_rejections",
    "pitch_feasibility_rejections",
    "anchor_alignment_hits",
    "anchor_alignment_fallbacks",
    "anchor_alignment_rejections",
    "saturated_seed_buckets",
)


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_reference_module(source: Path, module_name: str = "samuged._frozen_reference_phrases") -> ModuleType:
    """Load a phrase detector source file under a private samuged module name."""
    source = source.resolve()
    if not source.is_file():
        raise FileNotFoundError(f"reference source is unavailable: {source}")
    spec = importlib.util.spec_from_file_location(module_name, source)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load reference source: {source}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(module_name, None)
        raise
    return module


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = fraction * (len(ordered) - 1)
    low = math.floor(position)
    high = math.ceil(position)
    if low == high:
        return ordered[low]
    weight = position - low
    return ordered[low] * (1 - weight) + ordered[high] * weight


def paired_bootstrap_difference(
    reference_rows: list[dict],
    aligned_rows: list[dict],
    *,
    iterations: int,
    seed: int,
) -> dict:
    """Bootstrap aligned minus reference metrics by paired case resampling."""
    if iterations < 1:
        raise ValueError("bootstrap iterations must be positive")
    reference_by_id = {row["case_id"]: row for row in reference_rows}
    aligned_by_id = {row["case_id"]: row for row in aligned_rows}
    if set(reference_by_id) != set(aligned_by_id):
        raise ValueError("paired rows must contain the same case ids")
    case_ids = sorted(reference_by_id)
    if not case_ids:
        return {}

    def differences(ids: Iterable[str]) -> dict[str, float]:
        ids = list(ids)
        reference = aggregate_results([reference_by_id[case_id] for case_id in ids])
        aligned = aggregate_results([aligned_by_id[case_id] for case_id in ids])
        return {
            "candidate_f1": aligned["candidate"]["f1"] - reference["candidate"]["f1"],
            "occurrence_f1": aligned["occurrence"]["f1"] - reference["occurrence"]["f1"],
            "top1_recovery": aligned["top1_recovery"] - reference["top1_recovery"],
            "false_positive_case_rate": (
                aligned["false_positive_case_rate"] - reference["false_positive_case_rate"]
            ),
        }

    point = differences(case_ids)
    rng = random.Random(seed)
    samples = {key: [] for key in point}
    for _ in range(iterations):
        selected = [case_ids[rng.randrange(len(case_ids))] for _ in case_ids]
        sample = differences(selected)
        for key, value in sample.items():
            samples[key].append(value)
    return {
        key: {
            "aligned_minus_reference": point[key],
            "bootstrap_ci95": [_percentile(values, 0.025), _percentile(values, 0.975)],
        }
        for key, values in samples.items()
    }


def _method_aggregate(rows: list[dict], bootstrap_iterations: int, seed: int) -> dict:
    aggregate = aggregate_results(rows)
    aggregate["search_limited_cases"] = sum(row["search_limited"] for row in rows)
    aggregate["curation_truncated_cases"] = sum(row["curation_truncated"] for row in rows)
    aggregate["limit_parts"] = {
        key: sum(row["limit_parts"].get(key, 0) for row in rows) for key in LIMIT_KEYS
    }
    aggregate["profile_counters"] = {
        key: sum(row["profile_counters"].get(key, 0) for row in rows) for key in PROFILE_KEYS
    }
    aggregate["by_split"] = {}
    for split_index, split in enumerate(("development", "test")):
        selected = [row for row in rows if row["split"] == split]
        split_aggregate = aggregate_results(selected)
        split_aggregate["search_limited_cases"] = sum(row["search_limited"] for row in selected)
        split_aggregate["curation_truncated_cases"] = sum(
            row["curation_truncated"] for row in selected
        )
        aggregate["by_split"][split] = split_aggregate
    aggregate["by_condition"] = {
        kind: aggregate_results([row for row in rows if row["kind"] == kind])
        for kind in CASE_KINDS
    }
    return aggregate


def _detector_row(case, result: dict, elapsed: float) -> dict:
    row = score_case(case, result["phrases"], elapsed)
    part_stats = result["part_stats"]
    row.update(
        {
            "search_limited": result["search_limited"],
            "curation_truncated": result.get("curation_truncated", False),
            "candidate_count_before_reranking": result["candidate_count"],
            "limit_parts": {
                key: sum(int(part.get(key, False)) for part in part_stats) for key in LIMIT_KEYS
            },
            "profile_counters": {
                key: sum(part.get(key, 0) for part in part_stats) for key in PROFILE_KEYS
            },
        }
    )
    return row


def _read_real_cohort(repository: Path, limit: int) -> list[dict]:
    if limit < 1:
        raise ValueError("real limit must be positive")
    manifest = repository / REAL_MANIFEST
    records = [json.loads(line) for line in manifest.read_text(encoding="utf-8").splitlines() if line]
    if len(records) < limit:
        raise ValueError(f"real manifest has {len(records)} rows, fewer than requested {limit}")
    cohort = []
    for index, record in enumerate(records[:limit]):
        relative = record["source_path"]
        source = repository / REAL_ROOT / relative
        actual_hash = _sha256_file(source)
        expected_hash = record.get("source_sha256")
        if expected_hash and actual_hash != expected_hash:
            raise ValueError(f"source hash mismatch for {relative}")
        cohort.append(
            {
                "cohort_type": "real_pilot",
                "cohort_index": index,
                "source_path": relative,
                "source_sha256": actual_hash,
                "source_bytes": source.stat().st_size,
                "manifest_source_id": record.get("source_id"),
            }
        )
    return cohort


def _real_row(source: dict, method: str, result: dict, elapsed: float) -> dict:
    part_stats = result["part_stats"]
    return {
        "cohort_index": source["cohort_index"],
        "source_path": source["source_path"],
        "source_sha256": source["source_sha256"],
        "method": method,
        "status": "ok",
        "elapsed_seconds": round(elapsed, 8),
        "phrase_count": len(result["phrases"]),
        "candidate_count": result["candidate_count"],
        "search_limited": result["search_limited"],
        "curation_truncated": result.get("curation_truncated", False),
        "limit_parts": {
            key: sum(int(part.get(key, False)) for part in part_stats) for key in LIMIT_KEYS
        },
        "profile_counters": {
            key: sum(part.get(key, 0) for part in part_stats) for key in PROFILE_KEYS
        },
    }


def aggregate_real_rows(rows: list[dict]) -> dict:
    by_method = {}
    for method in METHODS:
        selected = [row for row in rows if row["method"] == method and row["status"] == "ok"]
        elapsed = [row["elapsed_seconds"] for row in selected]
        by_method[method] = {
            "successful_files": len(selected),
            "search_limited_files": sum(row["search_limited"] for row in selected),
            "curation_truncated_files": sum(row["curation_truncated"] for row in selected),
            "phrase_count": sum(row["phrase_count"] for row in selected),
            "candidate_count": sum(row["candidate_count"] for row in selected),
            "runtime_seconds": {
                "total": sum(elapsed),
                "mean": statistics.mean(elapsed) if elapsed else 0.0,
                "median": statistics.median(elapsed) if elapsed else 0.0,
                "maximum": max(elapsed, default=0.0),
            },
            "limit_parts": {
                key: sum(row["limit_parts"].get(key, 0) for row in selected)
                for key in LIMIT_KEYS
            },
            "profile_counters": {
                key: sum(row["profile_counters"].get(key, 0) for row in selected)
                for key in PROFILE_KEYS
            },
        }
    paired = []
    rows_by_key = {(row["source_path"], row["method"]): row for row in rows if row["status"] == "ok"}
    for source_path in sorted({row["source_path"] for row in rows}):
        reference = rows_by_key.get((source_path, "reference_approximate"))
        aligned = rows_by_key.get((source_path, "aligned"))
        if reference and aligned:
            paired.append(aligned["elapsed_seconds"] - reference["elapsed_seconds"])
    return {
        "claim_boundary": "runtime, search limits and output counts only; the cohort has no phrase ground truth",
        "methods": by_method,
        "paired_runtime_seconds": {
            "files": len(paired),
            "mean_aligned_minus_reference": statistics.mean(paired) if paired else 0.0,
            "median_aligned_minus_reference": statistics.median(paired) if paired else 0.0,
        },
    }


def _render_report(aggregate: dict) -> str:
    test = aggregate["synthetic"]["methods"]
    reference = test["reference_approximate"]["by_split"]["test"]
    aligned = test["aligned"]["by_split"]["test"]
    real = aggregate["real_pilot"]["methods"]
    lines = [
        "# Frozen reference and aligned comparison",
        "",
        "The synthetic table reports the untouched test split. Development and combined results are retained in `aggregate.json`.",
        "",
        "| Method | Candidate F1 | Occurrence F1 | Top 1 recovery | Negative false positive cases | Mean seconds |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
        f"| reference approximate | {reference['candidate']['f1']:.3f} | {reference['occurrence']['f1']:.3f} | {reference['top1_recovery']:.3f} | {reference['false_positive_case_count']} | {reference['runtime_seconds']['mean']:.4f} |",
        f"| aligned | {aligned['candidate']['f1']:.3f} | {aligned['occurrence']['f1']:.3f} | {aligned['top1_recovery']:.3f} | {aligned['false_positive_case_count']} | {aligned['runtime_seconds']['mean']:.4f} |",
        "",
        "## Test recovery by condition",
        "",
        "| Condition | Reference | Aligned |",
        "| --- | ---: | ---: |",
    ]
    for kind in CASE_KINDS:
        left = reference["by_kind"].get(kind, {})
        right = aligned["by_kind"].get(kind, {})
        lines.append(
            f"| {kind.replace('_', ' ')} | {left.get('recovered_cases', 0)}/{left.get('positive_cases', 0)} | "
            f"{right.get('recovered_cases', 0)}/{right.get('positive_cases', 0)} |"
        )
    lines.extend(
        [
            "",
            "## Fixed real pilot",
            "",
            "| Method | Files | Total seconds | Search limited files | Comparison limited parts |",
            "| --- | ---: | ---: | ---: | ---: |",
        ]
    )
    for method in METHODS:
        row = real[method]
        lines.append(
            f"| {method.replace('_', ' ')} | {row['successful_files']} | {row['runtime_seconds']['total']:.3f} | "
            f"{row['search_limited_files']} | {row['limit_parts']['comparison_limit_reached']} |"
        )
    lines.extend(
        [
            "",
            "The real pilot has no phrase annotations. Its runtime, limit and output counts do not establish precision or recall.",
            "",
            "The aligned candidate index uses a bounded anchor heuristic and can miss recurrences whose edits disrupt every selected anchor. Terminal insertions and deletions are excluded because their source boundaries are underdetermined.",
            "",
            "Neither benchmark measures musical quality, listener response or memorability.",
            "",
        ]
    )
    return "\n".join(lines)


def _json_write(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def run_comparison(
    output: Path,
    *,
    seeds: int = 1000,
    real_limit: int = 128,
    bootstrap_iterations: int = 1000,
) -> dict:
    if seeds != 1000:
        raise ValueError("the frozen comparison requires exactly 1000 generated cases")
    if real_limit != 128:
        raise ValueError("the frozen comparison requires exactly 128 real pilot files")
    if bootstrap_iterations < 1:
        raise ValueError("bootstrap iterations must be positive")

    repository = Path(__file__).resolve().parents[1]
    reference_source = repository / REFERENCE_SOURCE
    reference_module = load_reference_module(reference_source)
    synthetic_cases = generate_cases(seeds)
    real_cohort = _read_real_cohort(repository, real_limit)
    synthetic_reference_config = reference_module.Config(mode="approximate", top_k=10)
    real_reference_config = reference_module.Config(mode="approximate", top_k=3)
    synthetic_aligned_config = AlignedConfig(top_k=10)
    real_aligned_config = AlignedConfig(top_k=3)
    configs = {
        "synthetic": {
            "reference_approximate": asdict(synthetic_reference_config),
            "aligned": asdict(synthetic_aligned_config),
        },
        "real_pilot": {
            "reference_approximate": asdict(real_reference_config),
            "aligned": asdict(real_aligned_config),
        },
        "run": {
            "seeds": seeds,
            "real_limit": real_limit,
            "bootstrap_iterations": bootstrap_iterations,
        },
    }
    design = {
        "version": COMPARISON_VERSION,
        "base_benchmark": benchmark_design(),
        "methods": list(METHODS),
        "synthetic_protocol": "all generated cases, reported separately for development and untouched test splits",
        "real_protocol": "first 128 rows of pilot_both_v03/sources.jsonl; detector order counterbalanced by row parity",
        "paired_bootstrap": "case resampling with replacement; aligned minus reference; percentile 95% intervals",
        "reference_source": REFERENCE_SOURCE.as_posix(),
        "reference_source_sha256": _sha256_file(reference_source),
        "aligned_source_sha256": _sha256_file(repository / "samuged/aligned.py"),
        "claim_boundary": "synthetic planted recurrence metrics and real pilot runtime or limits only; no human memorability claim",
    }
    receipt_cases = [
        {"cohort_type": "synthetic", **case.metadata()} for case in synthetic_cases
    ] + real_cohort
    required_files = (
        "samuged/evaluate_aligned.py",
        "samuged/aligned.py",
        "samuged/evaluate.py",
        "samuged/experiment.py",
        "samuged/__init__.py",
        "samuged/metadata_recovery.py",
        "samuged/midi.py",
        "samuged/phrases.py",
        REFERENCE_SOURCE.as_posix(),
        REAL_MANIFEST.as_posix(),
        "pyproject.toml",
        "requirements-research.lock",
    )
    receipt = prepare_experiment(
        output,
        design=design,
        config=configs,
        cases=receipt_cases,
        required_files=required_files,
    )
    links = receipt_links(receipt)

    snapshot_reference = output.resolve() / "source_snapshot" / REFERENCE_SOURCE
    reference_module = load_reference_module(
        snapshot_reference, "samuged._receipt_reference_phrases"
    )
    synthetic_reference_config = reference_module.Config(**configs["synthetic"]["reference_approximate"])
    real_reference_config = reference_module.Config(**configs["real_pilot"]["reference_approximate"])

    synthetic_rows = {method: [] for method in METHODS}
    for case in synthetic_cases:
        for method, detector, config in (
            ("reference_approximate", reference_module.extract, synthetic_reference_config),
            ("aligned", extract_aligned, synthetic_aligned_config),
        ):
            started = time.monotonic()
            result = detector(case.song, config)
            synthetic_rows[method].append(
                _detector_row(case, result, time.monotonic() - started)
            )

    synthetic_aggregate = {
        "case_count": len(synthetic_cases),
        "split_counts": {
            split: sum(case.split == split for case in synthetic_cases)
            for split in ("development", "test")
        },
        "iou_threshold": IOU_THRESHOLD,
        "methods": {
            method: _method_aggregate(rows, bootstrap_iterations, 6100 + index)
            for index, (method, rows) in enumerate(synthetic_rows.items())
        },
        "paired_bootstrap": {},
        "paired_bootstrap_by_condition": {},
    }
    for split_index, split in enumerate(("combined", "development", "test")):
        reference_rows = synthetic_rows["reference_approximate"]
        aligned_rows = synthetic_rows["aligned"]
        if split != "combined":
            reference_rows = [row for row in reference_rows if row["split"] == split]
            aligned_rows = [row for row in aligned_rows if row["split"] == split]
        synthetic_aggregate["paired_bootstrap"][split] = paired_bootstrap_difference(
            reference_rows,
            aligned_rows,
            iterations=bootstrap_iterations,
            seed=6200 + split_index,
        )
    for kind_index, kind in enumerate(CASE_KINDS):
        synthetic_aggregate["paired_bootstrap_by_condition"][kind] = paired_bootstrap_difference(
            [row for row in synthetic_rows["reference_approximate"] if row["kind"] == kind],
            [row for row in synthetic_rows["aligned"] if row["kind"] == kind],
            iterations=bootstrap_iterations,
            seed=6300 + kind_index,
        )

    real_rows = []
    for source in real_cohort:
        song = load_midi(repository / REAL_ROOT / source["source_path"])
        ordered = (
            (
                ("reference_approximate", reference_module.extract, real_reference_config),
                ("aligned", extract_aligned, real_aligned_config),
            )
            if source["cohort_index"] % 2 == 0
            else (
                ("aligned", extract_aligned, real_aligned_config),
                ("reference_approximate", reference_module.extract, real_reference_config),
            )
        )
        for method, detector, config in ordered:
            started = time.monotonic()
            result = detector(song, config)
            real_rows.append(
                _real_row(source, method, result, time.monotonic() - started)
            )

    aggregate = {
        "comparison_version": COMPARISON_VERSION,
        **links,
        "source_hashes": {
            "reference_phrases": design["reference_source_sha256"],
            "aligned": design["aligned_source_sha256"],
            "evaluator": _sha256_file(repository / "samuged/evaluate_aligned.py"),
        },
        "config": configs,
        "synthetic": synthetic_aggregate,
        "real_pilot": aggregate_real_rows(real_rows),
        "claim_boundary": design["claim_boundary"],
    }
    raw = {
        "comparison_version": COMPARISON_VERSION,
        **links,
        "source_hashes": aggregate["source_hashes"],
        "synthetic_rows": synthetic_rows,
        "real_rows": sorted(real_rows, key=lambda row: (row["cohort_index"], row["method"])),
    }
    _json_write(output / "raw_results.json", raw)
    _json_write(output / "aggregate.json", aggregate)
    (output / "report.md").write_text(_render_report(aggregate), encoding="utf-8")
    complete_experiment(output)
    return aggregate


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seeds", type=int, default=1000)
    parser.add_argument("--real-limit", type=int, default=128)
    parser.add_argument("--bootstrap-iterations", type=int, default=1000)
    args = parser.parse_args(argv)
    result = run_comparison(
        args.output,
        seeds=args.seeds,
        real_limit=args.real_limit,
        bootstrap_iterations=args.bootstrap_iterations,
    )
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
