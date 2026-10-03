#!/usr/bin/env python3
"""Compare two bounded aligned-index seed rescue variants.

The variants are implemented by a process-local seed-key substitution which is
restored after every extraction.  Core modules and detector defaults are never
modified.  Synthetic metrics measure planted recurrence only.  Real MIDI rows
are unlabelled output and workload diagnostics.
"""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from contextlib import contextmanager
from dataclasses import asdict
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import statistics
import sys
import time
from typing import Any, Iterator

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from samuged import aligned, evaluate
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


VERSION = "samuged-seed-rescue-union-comparison-v2"
METHODS = ("baseline", "terminal_onset", "terminal_onset_union_short")
DEV_CASES = 500
FRESH_CASES = 500
FRESH_SEED_BASE = 40_000_000
REAL_CASES = 128
MAX_WORKERS = 2
SHORT_MAX_NOTES = 8
SOURCE_IDS = (
    "505a593b4bb78fb0913f503e",
    "7f008f441e679da594f68111",
    "9f60267f5b12ba99c1d0c9a9",
)
LIMIT_FLAGS = (
    "note_limit_reached",
    "window_limit_reached",
    "comparison_limit_reached",
    "group_limit_reached",
)
REQUIRED_FILES = (
    "scripts/compare_seed_rescue.py",
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


def _file_receipt(path: Path) -> dict[str, Any]:
    data = path.read_bytes()
    return {"path": str(path.resolve()), "sha256": sha256(data).hexdigest(), "bytes": len(data)}


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _read_jsonl_lf(path: Path) -> list[dict[str, Any]]:
    """Read JSONL using LF only, preserving Unicode line-separator characters."""
    text = path.read_bytes().decode("utf-8")
    rows = []
    for line_number, line in enumerate(text.split("\n"), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"JSONL row {line_number} is not an object: {path}")
        rows.append(value)
    return rows


def _terminal_composite_keys(candidate, cfg: AlignedConfig) -> tuple[tuple, ...]:
    """Frozen composite seed scheme with terminal onset replacing note end span."""
    terminal_onset = candidate.onsets[-1]
    keys: set[tuple] = set()
    offsets = aligned._offsets(len(candidate.pitches), cfg.seed_notes, cfg.max_seed_offsets)
    for seed_phase in (0.0, 0.5):
        anchors = []
        for offset in offsets:
            pitches = candidate.pitches[offset : offset + cfg.seed_notes]
            intervals = tuple(
                pitches[index + 1] - pitches[index]
                for index in range(len(pitches) - 1)
            )
            rhythm = tuple(
                aligned._bucket(
                    candidate.onsets[offset + index] - candidate.onsets[offset],
                    cfg.seed_beat_bucket,
                    seed_phase,
                )
                for index in range(1, cfg.seed_notes)
            )
            anchors.append((offset, intervals, rhythm, candidate.onsets[offset]))
        pairs = [
            (left, right)
            for left_index, left in enumerate(anchors)
            for right in anchors[left_index + 1 :]
            if right[0] - left[0] >= cfg.seed_notes
        ]
        pairs.sort(key=lambda pair: (-(pair[1][0] - pair[0][0]), pair[0][0], pair[1][0]))
        pairs = pairs[: cfg.max_seed_pairs]
        if len(candidate.notes) <= 7 or not pairs:
            for _, intervals, rhythm, _ in anchors:
                for span_phase in (0.0, 0.5):
                    keys.add(
                        (
                            "single_terminal",
                            intervals,
                            rhythm,
                            aligned._bucket(terminal_onset, cfg.span_beat_bucket, span_phase),
                        )
                    )
            if not pairs:
                continue
        for left, right in pairs:
            anchor_distance = right[3] - left[3]
            for distance_phase in (0.0, 0.5):
                for span_phase in (0.0, 0.5):
                    keys.add(
                        (
                            "pair_terminal",
                            left[1],
                            left[2],
                            right[1],
                            right[2],
                            aligned._bucket(
                                anchor_distance, cfg.span_beat_bucket, distance_phase
                            ),
                            aligned._bucket(
                                terminal_onset, cfg.span_beat_bucket, span_phase
                            ),
                        )
                    )
    return tuple(sorted(keys))


def seed_keys_for_method(candidate, cfg: AlignedConfig, method: str) -> tuple[tuple, ...]:
    """Return the exact frozen candidate keys for one study method."""
    if method == "baseline":
        return _ORIGINAL_SEED_KEYS(candidate, cfg)
    if method == "terminal_onset":
        return _terminal_composite_keys(candidate, cfg)
    if method != "terminal_onset_union_short":
        raise ValueError(f"unknown method: {method}")
    keys = set(_terminal_composite_keys(candidate, cfg))
    if len(candidate.notes) <= SHORT_MAX_NOTES:
        for offset in aligned._offsets(
            len(candidate.pitches), cfg.seed_notes, cfg.max_seed_offsets
        ):
            pitches = candidate.pitches[offset : offset + cfg.seed_notes]
            intervals = tuple(
                pitches[index + 1] - pitches[index]
                for index in range(len(pitches) - 1)
            )
            # Offset is part of the rescue key and each offset emits one such
            # key. Admission still uses one mixed Counter across composite,
            # phase and rescue keys; only the final verifier accepts a pair.
            keys.add(("short_distinct", offset, intervals))
    return tuple(sorted(keys))


_ORIGINAL_SEED_KEYS = aligned._seed_keys


@contextmanager
def _seed_method(method: str) -> Iterator[None]:
    """Install one process-local key function and always restore core state."""
    if aligned._seed_keys is not _ORIGINAL_SEED_KEYS:
        raise RuntimeError("aligned seed key function was already modified")
    if method == "baseline":
        yield
        return

    def replacement(candidate, cfg):
        return seed_keys_for_method(candidate, cfg, method)

    aligned._seed_keys = replacement
    try:
        yield
    finally:
        aligned._seed_keys = _ORIGINAL_SEED_KEYS
    if aligned._seed_keys is not _ORIGINAL_SEED_KEYS:
        raise RuntimeError("aligned seed key function was not restored")


def run_method(song, cfg: AlignedConfig, method: str) -> tuple[dict, float]:
    started = time.monotonic()
    with _seed_method(method):
        result = extract_indexed(song, cfg)
    return result, time.monotonic() - started


def _telemetry(result: dict) -> dict[str, Any]:
    parts = result["part_stats"]
    sums = (
        "windows_considered", "windows", "comparisons", "proposed_pairs",
        "dp_calls", "groups", "repeat_groups", "seed_key_calls",
        "seed_index_keys", "seed_index_postings", "posting_entries_visited",
        "seed_support_rejections", "overlap_rejections", "length_rejections",
        "terminal_timing_rejections", "timing_feasibility_rejections",
        "pitch_feasibility_rejections", "anchor_alignment_hits",
        "anchor_alignment_rejections", "saturated_seed_buckets",
        "saturated_seed_postings_dropped", "candidates_truncated",
    )
    key_types: Counter[str] = Counter()
    for part in parts:
        key_types.update(part.get("saturated_seed_key_types", {}))
    return {
        "candidate_count": result["candidate_count"],
        "raw_repeat_group_count": result["raw_repeat_group_count"],
        "search_limited": result["search_limited"],
        "curation_truncated": result["curation_truncated"],
        **{key: sum(int(part.get(key, 0)) for part in parts) for key in sums},
        "max_seed_bucket_size": max(
            (int(part.get("max_seed_bucket_size", 0)) for part in parts), default=0
        ),
        "saturated_seed_key_types": dict(sorted(key_types.items())),
        "limit_part_counts": {
            key: sum(bool(part.get(key)) for part in parts) for key in LIMIT_FLAGS
        },
    }


def _target_recovered(phrases: list[dict], intervals: list[list[int]]) -> dict[str, Any]:
    expected = {tuple(interval) for interval in intervals}
    ranks = []
    for rank, phrase in enumerate(phrases, 1):
        observed = {
            (occurrence["start_tick"], occurrence["end_tick"])
            for occurrence in phrase["occurrences"]
        }
        if expected <= observed:
            ranks.append(rank)
    return {"recovered": bool(ranks), "ranks": ranks}


def _comparison(baseline: dict, variant: dict) -> dict[str, Any]:
    baseline_ids = [row["family_id"] for row in baseline["phrases"]]
    variant_ids = [row["family_id"] for row in variant["phrases"]]
    return {
        "full_result_equal": canonical_json(baseline) == canonical_json(variant),
        "phrase_payload_equal": baseline["phrases"] == variant["phrases"],
        "family_sequence_equal": baseline_ids == variant_ids,
        "top1_equal": baseline_ids[:1] == variant_ids[:1],
        "baseline_only_family_ids": sorted(set(baseline_ids) - set(variant_ids)),
        "variant_only_family_ids": sorted(set(variant_ids) - set(baseline_ids)),
    }


def _run_variants(song, case=None, target_intervals=None, order=METHODS) -> dict[str, Any]:
    cfg = AlignedConfig()
    results: dict[str, dict] = {}
    variants = {}
    for method in order:
        result, elapsed = run_method(song, cfg, method)
        results[method] = result
        row = {
            "runtime_seconds": round(elapsed, 8),
            "result_sha256": sha256_json(result),
            "telemetry": _telemetry(result),
            "result": result,
        }
        if case is not None:
            row["score"] = score_case(case, result["phrases"], elapsed)
        if target_intervals is not None:
            row["target"] = _target_recovered(result["phrases"], target_intervals)
        variants[method] = row
    return {
        "execution_order": list(order),
        "variants": variants,
        "comparisons": {
            method: _comparison(results["baseline"], results[method])
            for method in METHODS[1:]
        },
    }


def _method_order(index: int) -> tuple[str, ...]:
    shift = index % len(METHODS)
    return METHODS[shift:] + METHODS[:shift]


def _worker(task: dict[str, Any]) -> dict[str, Any]:
    kind = task["task_kind"]
    if kind == "synthetic":
        case = task["case"]
        result = _run_variants(case.song, case=case, order=tuple(task["order"]))
        return {
            "sequence": task["sequence"],
            "case_id": case.case_id,
            "cohort": task["cohort"],
            "kind": case.kind,
            "positive": case.positive,
            **result,
        }
    source = Path(task["source_path"])
    source_receipt = _file_receipt(source)
    if (
        source_receipt["sha256"] != task["source_sha256"]
        or source_receipt["bytes"] != task["source_bytes"]
    ):
        raise ValueError(f"source changed before worker parse: {source}")
    song = load_midi(source, recover_invalid_keys=bool(task.get("metadata_repairs")))
    if song.metadata_repairs != task.get("metadata_repairs", []):
        raise ValueError(f"metadata repair receipt changed: {source}")
    result = _run_variants(
        song,
        target_intervals=task.get("target_intervals"),
        order=tuple(task["order"]),
    )
    return {
        "sequence": task["sequence"],
        "case_id": task["case_id"],
        "cohort": task["cohort"],
        "source_path": task["source_relative"],
        "source_sha256": task["source_sha256"],
        **result,
    }


def development_cases() -> list:
    cases = [case for case in generate_cases(DEV_CASES * 2) if case.split == "development"]
    if len(cases) != DEV_CASES:
        raise ValueError("existing development cohort construction changed")
    return cases


def fresh_cases() -> list:
    return [
        evaluate._build_case(
            evaluate.CASE_KINDS[index % len(evaluate.CASE_KINDS)],
            "fresh_seed_rescue",
            index,
            FRESH_SEED_BASE + index,
        )
        for index in range(FRESH_CASES)
    ]


def _real_cohort(manifest: Path, source_root: Path) -> tuple[list[dict], dict[str, Any]]:
    rows = _read_jsonl_lf(manifest)
    if len(rows) != REAL_CASES or len({row["source_path"] for row in rows}) != REAL_CASES:
        raise ValueError("fixed real pilot must contain 128 distinct sources")
    cohort = []
    for row in rows:
        if row.get("status") != "ok":
            raise ValueError("fixed real pilot contains a non-ok source")
        path = (source_root / row["source_path"]).resolve(strict=True)
        receipt = _file_receipt(path)
        if receipt["sha256"] != row["source_sha256"]:
            raise ValueError(f"real source changed: {row['source_path']}")
        cohort.append({
            "case_id": f"real:{row['source_id']}",
            "cohort": "fixed_real_128",
            "source_path": row["source_path"],
            "source_sha256": row["source_sha256"],
            "source_bytes": receipt["bytes"],
            "metadata_repairs": row.get("metadata_repairs", []),
        })
    return cohort, _file_receipt(manifest)


def _regression_cohort(
    audit_root: Path, reference_root: Path, source_root: Path
) -> tuple[list[dict], list[dict[str, Any]]]:
    verify_completed_experiment(audit_root)
    raw_path = audit_root / "raw_results.json"
    raw = json.loads(raw_path.read_text())
    by_id = {row["source_id"]: row for row in raw["rows"]}
    if set(by_id) != set(SOURCE_IDS):
        raise ValueError("no-match audit cohort changed")
    inputs = [
        _file_receipt(audit_root / "experiment_receipt.json"),
        _file_receipt(audit_root / "completion_receipt.json"),
        _file_receipt(raw_path),
    ]
    cohort = []
    for source_id in SOURCE_IDS:
        row = by_id[source_id]
        source_path = (source_root / row["source_path"]).resolve(strict=True)
        source_receipt = _file_receipt(source_path)
        record_path = reference_root / "records" / f"{source_id}.json"
        record_receipt = _file_receipt(record_path)
        if source_receipt["sha256"] != row["source_sha256"]:
            raise ValueError(f"regression source changed: {source_id}")
        inputs.extend((source_receipt, record_receipt))
        cohort.append({
            "case_id": f"regression:{source_id}",
            "cohort": "known_development_regressions",
            "source_id": source_id,
            "source_path": row["source_path"],
            "source_sha256": row["source_sha256"],
            "source_bytes": source_receipt["bytes"],
            "metadata_repairs": [],
            "target_intervals": [
                [occurrence["start_tick"], occurrence["end_tick"]]
                for occurrence in row["reference_phrase"]["occurrences"]
            ],
            "reference_record_sha256": record_receipt["sha256"],
        })
    return cohort, inputs


def _task_rows(
    dev: list, fresh: list, real: list[dict], regressions: list[dict], source_root: Path
) -> list[dict[str, Any]]:
    tasks = []
    sequence = 0
    for cohort, cases in (("existing_development_500", dev), ("fresh_seed_500", fresh)):
        for case in cases:
            tasks.append({
                "task_kind": "synthetic", "sequence": sequence, "cohort": cohort,
                "case": case, "order": _method_order(sequence),
            })
            sequence += 1
    for row in regressions + real:
        tasks.append({
            "task_kind": "midi", "sequence": sequence, "cohort": row["cohort"],
            "case_id": row["case_id"], "source_relative": row["source_path"],
            "source_path": str((source_root / row["source_path"]).resolve()),
            "source_sha256": row["source_sha256"],
            "source_bytes": row["source_bytes"],
            "metadata_repairs": row.get("metadata_repairs", []),
            "target_intervals": row.get("target_intervals"),
            "order": _method_order(sequence),
        })
        sequence += 1
    return tasks


def _sum_telemetry(rows: list[dict], method: str) -> dict[str, Any]:
    values = [row["variants"][method]["telemetry"] for row in rows]
    sum_keys = tuple(
        key for key in values[0]
        if key not in {
            "search_limited", "curation_truncated", "max_seed_bucket_size",
            "saturated_seed_key_types", "limit_part_counts",
        }
    ) if values else ()
    key_types: Counter[str] = Counter()
    for value in values:
        key_types.update(value["saturated_seed_key_types"])
    return {
        **{key: sum(value[key] for value in values) for key in sum_keys},
        "search_limited_cases": sum(value["search_limited"] for value in values),
        "curation_truncated_cases": sum(value["curation_truncated"] for value in values),
        "max_seed_bucket_size": max((value["max_seed_bucket_size"] for value in values), default=0),
        "saturated_seed_key_types": dict(sorted(key_types.items())),
        "limit_part_counts": {
            flag: sum(value["limit_part_counts"][flag] for value in values)
            for flag in LIMIT_FLAGS
        },
    }


def _paired_deltas(rows: list[dict], method: str) -> dict[str, Any]:
    comparisons = [row["comparisons"][method] for row in rows]
    baseline_runtime = [row["variants"]["baseline"]["runtime_seconds"] for row in rows]
    variant_runtime = [row["variants"][method]["runtime_seconds"] for row in rows]
    return {
        "full_result_changes": sum(not row["full_result_equal"] for row in comparisons),
        "phrase_payload_changes": sum(not row["phrase_payload_equal"] for row in comparisons),
        "family_sequence_changes": sum(not row["family_sequence_equal"] for row in comparisons),
        "top1_changes": sum(not row["top1_equal"] for row in comparisons),
        "baseline_only_selected_families": sum(len(row["baseline_only_family_ids"]) for row in comparisons),
        "variant_only_selected_families": sum(len(row["variant_only_family_ids"]) for row in comparisons),
        "runtime_total_seconds": {
            "baseline": round(sum(baseline_runtime), 8),
            "variant": round(sum(variant_runtime), 8),
        },
        "runtime_paired_ratio_median": round(
            statistics.median(
                variant / baseline
                for baseline, variant in zip(baseline_runtime, variant_runtime)
                if baseline > 0
            ),
            8,
        ) if rows else None,
    }


def _synthetic_summary(rows: list[dict]) -> dict[str, Any]:
    methods = {}
    for method in METHODS:
        scores = [row["variants"][method]["score"] for row in rows]
        methods[method] = {
            "metrics": aggregate_results(scores),
            "telemetry": _sum_telemetry(rows, method),
            "runtime_seconds": round(
                sum(row["variants"][method]["runtime_seconds"] for row in rows), 8
            ),
        }
    deltas = {}
    for method in METHODS[1:]:
        changes = Counter()
        by_kind: dict[str, Counter] = {}
        for row in rows:
            baseline = row["variants"]["baseline"]["score"]
            variant = row["variants"][method]["score"]
            if baseline["recovered"] and not variant["recovered"]:
                label = "lost_recovery"
            elif not baseline["recovered"] and variant["recovered"]:
                label = "gained_recovery"
            elif baseline["recovery_rank"] != variant["recovery_rank"]:
                label = "rank_changed"
            elif baseline["false_positive_case"] != variant["false_positive_case"]:
                label = "negative_case_changed"
            else:
                label = "unchanged"
            changes[label] += 1
            by_kind.setdefault(row["kind"], Counter())[label] += 1
        deltas[method] = {
            **_paired_deltas(rows, method),
            "outcome_changes": dict(sorted(changes.items())),
            "outcome_changes_by_kind": {
                kind: dict(sorted(counts.items())) for kind, counts in sorted(by_kind.items())
            },
        }
    return {"cases": len(rows), "methods": methods, "deltas_from_baseline": deltas}


def _unlabelled_summary(rows: list[dict]) -> dict[str, Any]:
    return {
        "cases": len(rows),
        "methods": {
            method: {
                "telemetry": _sum_telemetry(rows, method),
                "runtime_seconds": round(
                    sum(row["variants"][method]["runtime_seconds"] for row in rows), 8
                ),
            }
            for method in METHODS
        },
        "deltas_from_baseline": {
            method: _paired_deltas(rows, method) for method in METHODS[1:]
        },
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    if not 1 <= args.workers <= MAX_WORKERS:
        raise ValueError(f"workers must be between 1 and {MAX_WORKERS}")
    source_root = args.source_root.resolve(strict=True)
    manifest = args.real_manifest.resolve(strict=True)
    audit_root = args.regression_audit.resolve(strict=True)
    reference_root = args.reference.resolve(strict=True)
    output = args.output.resolve()

    dev = development_cases()
    fresh = fresh_cases()
    real, manifest_receipt = _real_cohort(manifest, source_root)
    regressions, regression_inputs = _regression_cohort(
        audit_root, reference_root, source_root
    )
    default_config = asdict(AlignedConfig())
    design = {
        "version": VERSION,
        "purpose": "bounded candidate seed rescue diagnostics without production changes",
        "methods": {
            "baseline": "unchanged aligned_indexed exact-first candidate generation",
            "terminal_onset": "composite seed full span replaced by terminal onset",
            "terminal_onset_union_short": (
                "terminal-onset composite keys at every length, unioned for six-to-eight-note "
                "windows with one pitch-interval key per encoded offset"
            ),
        },
        "union_admission": (
            "unchanged min_seed_support=3 uses one mixed vote counter; support may combine "
            "phase/composite and short distinct-offset keys; the unchanged verifier accepts"
        ),
        "cohorts": {
            "known_development_regressions": 3,
            "existing_development_500": DEV_CASES,
            "fixed_real_128": REAL_CASES,
            "fresh_seed_500": FRESH_CASES,
        },
        "existing_development_namespace": evaluate._DEV_SEED_BASE,
        "fresh_seed_namespace": FRESH_SEED_BASE,
        "fresh_policy": "frozen and executed without tuning after any result inspection",
        "workers": args.workers,
        "fixed_core_behaviour": [
            "exact cache", "all resource limits", "fixed prototype verifier",
            "nonoverlap", "ranking", "curation",
        ],
        "result_artifacts": ["aggregate.json", "input_manifest.json", "raw_results.json"],
        "claim_boundary": (
            "planted recurrence metrics and unlabelled real output sensitivity; "
            "not musical quality, memorability or a default promotion"
        ),
    }
    config = {
        "aligned_config": default_config,
        "methods": list(METHODS),
        "short_max_notes": SHORT_MAX_NOTES,
        "input_receipts": {
            "real_manifest": manifest_receipt,
            "regression_inputs": regression_inputs,
        },
    }
    cases = [
        *[case.metadata() | {"cohort": "existing_development_500"} for case in dev],
        *[case.metadata() | {"cohort": "fresh_seed_500"} for case in fresh],
        *regressions,
        *real,
    ]
    receipt = prepare_experiment(
        output, design=design, config=config, cases=cases, required_files=REQUIRED_FILES
    )
    links = receipt_links(receipt)
    _write_json(output / "input_manifest.json", {
        **links,
        "version": VERSION,
        "real_manifest": manifest_receipt,
        "regression_inputs": regression_inputs,
        "case_count": len(cases),
        "case_cohort_sha256": receipt["case_cohort_sha256"],
    })

    tasks = _task_rows(dev, fresh, real, regressions, source_root)
    rows = []
    started = time.monotonic()
    # map preserves task order while allowing at most two worker processes.
    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        for completed, row in enumerate(executor.map(_worker, tasks), 1):
            rows.append(row)
            if completed % 25 == 0 or completed == len(tasks):
                print(json.dumps({
                    "completed": completed,
                    "total": len(tasks),
                    "elapsed_seconds": round(time.monotonic() - started, 3),
                }), flush=True)
    rows.sort(key=lambda row: row["sequence"])

    # Recheck every external input after all detector work.
    for item in [manifest_receipt, *regression_inputs]:
        current = _file_receipt(Path(item["path"]))
        if (current["sha256"], current["bytes"]) != (item["sha256"], item["bytes"]):
            raise RuntimeError(f"input changed during experiment: {item['path']}")
    for row in regressions + real:
        current = _file_receipt(source_root / row["source_path"])
        if current["sha256"] != row["source_sha256"]:
            raise RuntimeError(f"source changed during experiment: {row['source_path']}")

    groups = {
        name: [row for row in rows if row["cohort"] == name]
        for name in (
            "known_development_regressions", "existing_development_500",
            "fixed_real_128", "fresh_seed_500",
        )
    }
    regression_summary = _unlabelled_summary(groups["known_development_regressions"])
    regression_summary["target_recovery"] = {
        method: {
            "recovered": sum(row["variants"][method]["target"]["recovered"] for row in groups["known_development_regressions"]),
            "case_ids": [
                row["case_id"] for row in groups["known_development_regressions"]
                if row["variants"][method]["target"]["recovered"]
            ],
        }
        for method in METHODS
    }
    aggregate = {
        **links,
        "version": VERSION,
        "groups": {
            "known_development_regressions": regression_summary,
            "existing_development_500": _synthetic_summary(groups["existing_development_500"]),
            "fixed_real_128": _unlabelled_summary(groups["fixed_real_128"]),
            "fresh_seed_500": _synthetic_summary(groups["fresh_seed_500"]),
        },
        "wall_seconds": round(time.monotonic() - started, 8),
        "decision": "report_only_no_default_promotion",
        "claim_boundary": design["claim_boundary"],
    }
    _write_json(output / "raw_results.json", {**links, "version": VERSION, "rows": rows})
    _write_json(output / "aggregate.json", aggregate)
    complete_experiment(output)
    return aggregate


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=ROOT / "datasets/Lakh MIDI Clean")
    parser.add_argument("--real-manifest", type=Path, default=ROOT / "research_local/pilot_indexed_v01/sources.jsonl")
    parser.add_argument("--regression-audit", type=Path, default=ROOT / "research_local/no_match_regressions_v01")
    parser.add_argument("--reference", type=Path, default=ROOT / "research_local/lakh_phrases_v03")
    parser.add_argument("--output", type=Path, default=ROOT / "research_local/seed_rescue_union_v02")
    parser.add_argument("--workers", type=int, default=2)
    return parser.parse_args(argv)


if __name__ == "__main__":
    result = run(parse_args())
    print(json.dumps({
        "version": result["version"],
        "receipt_sha256": result["receipt_sha256"],
        "wall_seconds": result["wall_seconds"],
    }, sort_keys=True))
