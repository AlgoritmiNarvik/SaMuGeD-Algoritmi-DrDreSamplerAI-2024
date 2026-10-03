"""Independently audit the completed certified drum control experiment.

The audit reads the saved MIDI files and result rows, loads the executable
modules from the experiment's source snapshot and re-runs the oracle and both
detector modes. It does not modify the completed experiment directory.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass
from fractions import Fraction
import hashlib
import importlib
import json
from pathlib import Path, PurePosixPath
import sys
import time
from typing import Any, Iterator


VERSION = "certified-drum-audit-v1"
EXPECTED_SPLITS = ("development", "test")
EXPECTED_KINDS = ("certified_negative", "planted_positive")
EXPECTED_METERS = {(4, 4), (3, 4), (6, 8), (7, 8)}
EXPECTED_PPQS = {96, 480, 960}
MIN_BARS = 16
MAX_BARS = 32
BAR_COUNTS = (1, 2, 4)
MIN_HITS = 8
MIN_PITCHES = 2
TIMING_TOLERANCE_BEATS = Fraction(1, 12)
HIT_ERROR_FRACTION = Fraction(1, 10)

STUDY_VERSION = "certified-drum-controls-v1"
STUDY_NAMESPACE = "samuged-certified-drums-v1"
EXPECTED_BARS = [16, 32]
EXPECTED_METER_LIST = [[4, 4], [3, 4], [6, 8], [7, 8]]
EXPECTED_PPQ_LIST = [96, 480, 960]
EXPECTED_PAIR_LIMIT = "exact bucket-pair count per generated song"
EXPECTED_CLAIM_BOUNDARY = (
    "algorithm-independent symbolic controls only; no human specificity, "
    "musical quality or real corpus accuracy claim"
)
EXPECTED_POSITIVE_COVERAGE = (
    "fraction of labelled target oracle edges reproduced as direct prototype "
    "to occurrence detector edges"
)


def _bytes_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_bytes(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _json_sha256(value: object) -> str:
    return _bytes_sha256(_json_bytes(value))


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _safe_relative(path: str) -> PurePosixPath:
    value = PurePosixPath(path)
    if value.is_absolute() or ".." in value.parts or "\\" in path:
        raise ValueError(f"unsafe relative path: {path}")
    return value


def _study_file(study: Path, relative: str) -> Path:
    path = _safe_relative(relative)
    resolved = (study / path).resolve(strict=True)
    if not resolved.is_file() or not resolved.is_relative_to(study.resolve()):
        raise ValueError(f"study artifact escapes study directory: {relative}")
    return resolved


def _source_file(snapshot_root: Path, relative: str) -> Path:
    path = _safe_relative(relative)
    resolved = (snapshot_root / path).resolve(strict=True)
    if not resolved.is_file() or not resolved.is_relative_to(snapshot_root.resolve()):
        raise ValueError(f"source snapshot path escapes snapshot: {relative}")
    return resolved


@dataclass(frozen=True)
class SnapshotApi:
    experiment: Any
    oracle: Any
    drums: Any
    midi: Any


@contextmanager
def _snapshot_api(snapshot_root: Path) -> Iterator[SnapshotApi]:
    """Load the study's frozen package under the real package name temporarily."""
    saved_path = list(sys.path)
    saved_modules = {
        name: module
        for name, module in sys.modules.items()
        if name == "samuged" or name.startswith("samuged.")
    }
    for name in list(saved_modules):
        del sys.modules[name]
    sys.path.insert(0, str(snapshot_root))
    importlib.invalidate_caches()
    try:
        yield SnapshotApi(
            experiment=importlib.import_module("samuged.experiment"),
            oracle=importlib.import_module("samuged.drum_oracle"),
            drums=importlib.import_module("samuged.drums"),
            midi=importlib.import_module("samuged.midi"),
        )
    finally:
        for name in list(sys.modules):
            if name == "samuged" or name.startswith("samuged."):
                del sys.modules[name]
        sys.path[:] = saved_path
        sys.modules.update(saved_modules)


def _verify_source_snapshot(study: Path, receipt: dict[str, Any]) -> dict[str, Any]:
    metadata = _read_json(study / "source_snapshot.json")
    files = metadata.get("files")
    if not isinstance(files, list) or not isinstance(metadata.get("snapshot_version"), str):
        raise ValueError("invalid source snapshot metadata")
    expected_snapshot = _json_sha256(
        {"version": metadata["snapshot_version"], "files": files}
    )
    if expected_snapshot != metadata.get("snapshot_sha256"):
        raise ValueError("source snapshot metadata hash mismatch")
    snapshot_root = study / "source_snapshot"
    verified_files = []
    seen = set()
    for entry in files:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            raise ValueError("invalid source snapshot entry")
        relative = entry["path"]
        if relative in seen:
            raise ValueError(f"duplicate source snapshot path: {relative}")
        seen.add(relative)
        path = _source_file(snapshot_root, relative)
        data = path.read_bytes()
        if entry.get("bytes") != len(data) or entry.get("sha256") != _bytes_sha256(data):
            raise ValueError(f"source snapshot file mismatch: {relative}")
        verified_files.append(relative)
    receipt_snapshot = receipt.get("source_snapshot", {})
    if receipt_snapshot.get("snapshot_sha256") != metadata["snapshot_sha256"]:
        raise ValueError("receipt and source snapshot hashes differ")
    return {
        "snapshot_sha256": metadata["snapshot_sha256"],
        "file_count": len(verified_files),
        "files": verified_files,
        "root": snapshot_root,
    }


def _arrangement_hashes_for_case(song: Any, bars: int) -> tuple[str, str]:
    if not song.parts:
        raise ValueError("saved MIDI has no parts")
    notes = song.parts[0].notes
    exact = [(note.start, note.end, note.pitch, note.velocity) for note in notes]
    beat = [
        (
            round(note.start / song.ticks_per_beat, 8),
            round(note.end / song.ticks_per_beat, 8),
            note.pitch,
        )
        for note in notes
    ]
    return (
        _json_sha256(
            {
                "bars": bars,
                "ppq": song.ticks_per_beat,
                "meters": song.meters,
                "notes": exact,
            }
        ),
        _json_sha256({"bars": bars, "meters": song.meters, "notes": beat}),
    )


def _exhaustive_budget(windows: list[Any]) -> int:
    counts = Counter(
        (window.bar_count, window.numerator, window.denominator)
        for window in windows
    )
    return max(1, sum(count * (count - 1) // 2 for count in counts.values()))


def _oracle_certificate(api: SnapshotApi, song: Any) -> dict[str, Any]:
    windows = api.oracle.enumerate_windows(
        song,
        bar_counts=BAR_COUNTS,
        min_hits=MIN_HITS,
        min_pitches=MIN_PITCHES,
    )
    budget = _exhaustive_budget(windows)
    pairs, stats = api.oracle.enumerate_admissible_pairs(
        windows, song.ticks_per_beat, max_pair_comparisons=budget
    )
    return {
        "eligible_window_count": len(windows),
        "oracle_pair_count": len(pairs),
        "pair_comparisons": stats["pair_comparisons"],
        "pair_budget": stats["pair_budget"],
        "pair_budget_reached": stats["pair_budget_reached"],
        "exhaustive_pair_enumeration": not stats["pair_budget_reached"],
        "pairs": pairs,
    }


def _target_pair_key(
    first: tuple[int, int],
    second: tuple[int, int],
    *,
    bar_count: int,
    numerator: int,
    denominator: int,
) -> tuple[int, ...]:
    left, right = sorted((first, second))
    return (bar_count, numerator, denominator, left[0], left[1], right[0], right[1])


def _derived_target_pairs(case: dict[str, Any]) -> tuple[tuple[int, ...], ...]:
    intervals = [tuple(item) for item in case.get("target_intervals", [])]
    if not intervals:
        return ()
    ppq = case["ticks_per_beat"]
    numerator, denominator = case["meter"]
    bar_ticks = ppq * numerator * 4 // denominator
    lengths = {(end - start) // bar_ticks for start, end in intervals}
    if len(lengths) != 1 or 0 in lengths:
        raise ValueError(f"invalid target interval lengths: {case['case_id']}")
    if any(start % bar_ticks or end % bar_ticks for start, end in intervals):
        raise ValueError(f"target interval is not meter aligned: {case['case_id']}")
    bar_count = lengths.pop()
    return tuple(
        _target_pair_key(
            intervals[left], intervals[right],
            bar_count=bar_count,
            numerator=numerator,
            denominator=denominator,
        )
        for left in range(len(intervals))
        for right in range(left + 1, len(intervals))
    )


def _direct_edges(phrases: list[dict[str, Any]]) -> set[tuple[int, ...]]:
    edges: set[tuple[int, ...]] = set()
    for phrase in phrases:
        geometry = (
            phrase["bar_count"],
            phrase["meter_numerator"],
            phrase["meter_denominator"],
        )
        prototype = (phrase["start_tick"], phrase["end_tick"])
        for occurrence in phrase.get("occurrences", []):
            other = (occurrence["start_tick"], occurrence["end_tick"])
            if other == prototype:
                continue
            first, second = sorted((prototype, other))
            edges.add((*geometry, first[0], first[1], second[0], second[1]))
    return edges


def _family_covers_targets(
    phrases: list[dict[str, Any]], target_intervals: list[list[int]]
) -> bool:
    targets = {tuple(interval) for interval in target_intervals}
    if not targets:
        return False
    for phrase in phrases:
        family = {(phrase["start_tick"], phrase["end_tick"])}
        family.update(
            (occurrence["start_tick"], occurrence["end_tick"])
            for occurrence in phrase.get("occurrences", [])
        )
        if targets <= family:
            return True
    return False


def _json_normalize(value: Any) -> Any:
    if isinstance(value, tuple):
        return [_json_normalize(item) for item in value]
    if isinstance(value, list):
        return [_json_normalize(item) for item in value]
    if isinstance(value, dict):
        return {key: _json_normalize(item) for key, item in value.items()}
    return value


def _compare_replay_stats(
    saved: dict[str, Any], replayed: dict[str, Any]
) -> tuple[bool, list[str]]:
    """Compare scientific stats, allowing MIDI metadata track renumbering."""
    saved_norm = _json_normalize(saved)
    replay_norm = _json_normalize(replayed)
    differences = []
    keys = (set(saved_norm) | set(replay_norm)) - {"source_tracks", "config"}
    for key in sorted(keys):
        if saved_norm.get(key) != replay_norm.get(key):
            differences.append(key)
    if saved_norm.get("config") != replay_norm.get("config"):
        differences.append("config")
    saved_tracks = saved_norm.get("source_tracks")
    replay_tracks = replay_norm.get("source_tracks")
    if not (
        isinstance(saved_tracks, list)
        and isinstance(replay_tracks, list)
        and replay_tracks == [track + 1 for track in saved_tracks]
    ):
        differences.append("source_tracks")
    return not differences, differences


def _require_replay_stats_match(
    saved: dict[str, Any], replayed: dict[str, Any], *, mode: str, case_id: str
) -> tuple[bool, list[str]]:
    stats_match, differences = _compare_replay_stats(saved, replayed)
    if not stats_match:
        raise ValueError(f"replay detector stats mismatch {mode}/{case_id}: {differences}")
    return stats_match, differences


def _wilson(successes: int, total: int) -> list[float] | None:
    if total < 1:
        return None
    z = 1.959963984540054
    p = successes / total
    denominator = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denominator
    margin = z * ((p * (1 - p) + z * z / (4 * total)) / total) ** 0.5 / denominator
    return [max(0.0, centre - margin), min(1.0, centre + margin)]


def _artifact_manifest(study: Path, relative_paths: list[str]) -> list[dict[str, Any]]:
    entries = []
    for relative in sorted(set(relative_paths)):
        data = _study_file(study, relative).read_bytes()
        entries.append({"path": relative, "bytes": len(data), "sha256": _bytes_sha256(data)})
    return entries


def _aggregate_from_raw(rows: list[dict[str, Any]]) -> dict[str, Any]:
    negatives = [row for row in rows if row["kind"] == "certified_negative"]
    positives = [row for row in rows if row["kind"] == "planted_positive"]
    negative_outputs = sum(bool(row["negative_case_with_output"]) for row in negatives)
    target_pairs = sum(row["target_pair_count"] for row in positives)
    covered_pairs = sum(
        row["target_pairs_covered_by_direct_detector_edges"] for row in positives
    )
    return {
        "cases": len(rows),
        "negative_cases": len(negatives),
        "negative_cases_with_output": negative_outputs,
        "negative_output_rate": negative_outputs / len(negatives) if negatives else None,
        "negative_output_wilson_95": _wilson(negative_outputs, len(negatives)),
        "positive_cases": len(positives),
        "positive_target_pairs": target_pairs,
        "positive_target_pairs_covered_by_direct_detector_edges": covered_pairs,
        "positive_oracle_edge_coverage": covered_pairs / target_pairs if target_pairs else None,
        "oracle_pair_budget_reached_cases": sum(
            bool(row["oracle_pair_budget_reached"]) for row in rows
        ),
        "detector_search_limited_cases": sum(
            bool(row["detector_stats"].get("search_limited")) for row in rows
        ),
        "detector_candidate_limit_cases": sum(
            bool(row["detector_stats"].get("candidate_limit_reached")) for row in rows
        ),
    }


def _compare_aggregate(saved: dict[str, Any], actual: dict[str, Any]) -> list[str]:
    fields = (
        "cases", "negative_cases", "negative_cases_with_output",
        "negative_output_rate", "negative_output_wilson_95", "positive_cases",
        "positive_target_pairs", "positive_target_pairs_covered_by_direct_detector_edges",
        "positive_oracle_edge_coverage", "oracle_pair_budget_reached_cases",
        "detector_search_limited_cases", "detector_candidate_limit_cases",
    )
    return [field for field in fields if saved.get(field) != actual.get(field)]


def _expected_study_config() -> dict[str, Any]:
    return {
        "detector_modes": ["exact", "tolerant"],
        "generator": {
            "version": STUDY_VERSION,
            "namespace": STUDY_NAMESPACE,
            "meters": EXPECTED_METER_LIST,
            "ticks_per_beat": EXPECTED_PPQ_LIST,
            "bar_range": EXPECTED_BARS,
            "max_generation_attempts": 10000,
        },
        "oracle": {
            "bar_counts": list(BAR_COUNTS),
            "timing_tolerance_beats": [
                TIMING_TOLERANCE_BEATS.numerator,
                TIMING_TOLERANCE_BEATS.denominator,
            ],
            "hit_error_fraction": [
                HIT_ERROR_FRACTION.numerator,
                HIT_ERROR_FRACTION.denominator,
            ],
            "min_hits": MIN_HITS,
            "min_pitches": MIN_PITCHES,
            "pair_comparison_limit": EXPECTED_PAIR_LIMIT,
            "pair_comparison_cap": None,
        },
    }


def _validate_embedded_design(
    *,
    receipt: dict[str, Any],
    receipt_file_sha256: str,
    design: dict[str, Any],
    labels: dict[str, Any],
    raw: dict[str, Any],
    aggregate: dict[str, Any],
    cases: list[dict[str, Any]],
    counts: Counter[tuple[str, str]],
) -> None:
    """Validate the frozen design body, hashes and executable study semantics.

    ``verify_completed_experiment`` binds result bytes to the start receipt but
    intentionally does not interpret the design body. This independent check
    closes that gap before any detector replay is trusted.
    """
    if not isinstance(receipt.get("design"), dict) or not isinstance(receipt.get("config"), dict):
        raise ValueError("experiment receipt has no frozen design/config")
    receipt_design = receipt["design"]
    receipt_config = receipt["config"]
    if receipt.get("design_sha256") != _json_sha256(receipt_design):
        raise ValueError("frozen receipt design hash mismatch")
    if receipt.get("config_sha256") != _json_sha256(receipt_config):
        raise ValueError("frozen receipt config hash mismatch")
    for name, value, embedded_hash, frozen_hash in (
        ("design", design.get("design"), design.get("design_sha256"), receipt.get("design_sha256")),
        ("config", design.get("config"), design.get("config_sha256"), receipt.get("config_sha256")),
    ):
        if not isinstance(value, dict) or embedded_hash != _json_sha256(value):
            raise ValueError(f"embedded {name} hash mismatch")
        if embedded_hash != frozen_hash or value != receipt[name]:
            raise ValueError(f"embedded {name} differs from frozen receipt")

    source_hash = receipt.get("source_snapshot", {}).get("snapshot_sha256")
    cohort_hash = receipt.get("case_cohort_sha256")
    if not isinstance(source_hash, str) or not isinstance(cohort_hash, str):
        raise ValueError("frozen receipt links are incomplete")
    if receipt_file_sha256 != design.get("receipt_sha256"):
        raise ValueError("embedded design receipt link mismatch")
    for field, expected in (
        ("version", STUDY_VERSION),
        ("config_sha256", receipt.get("config_sha256")),
        ("case_cohort_sha256", cohort_hash),
        ("snapshot_sha256", source_hash),
        ("source_snapshot_sha256", source_hash),
        ("receipt_sha256", receipt_file_sha256),
    ):
        if design.get(field) != expected:
            raise ValueError(f"design provenance link mismatch: {field}")
    for name, result in (("labels", labels), ("raw results", raw), ("aggregate", aggregate)):
        for field, expected in (
            ("version", STUDY_VERSION),
            ("config_sha256", receipt.get("config_sha256")),
            ("case_cohort_sha256", cohort_hash),
            ("snapshot_sha256", source_hash),
            ("source_snapshot_sha256", source_hash),
            ("receipt_sha256", receipt_file_sha256),
        ):
            if result.get(field) != expected:
                raise ValueError(f"{name} provenance link mismatch: {field}")
    for name, result in (("raw results", raw), ("aggregate", aggregate)):
        if result.get("design_sha256") != receipt.get("design_sha256"):
            raise ValueError(f"{name} design hash link mismatch")

    body = design["design"]
    if body.get("version") != STUDY_VERSION:
        raise ValueError("design semantics version mismatch")
    if body.get("namespace") != STUDY_NAMESPACE:
        raise ValueError("design semantics namespace mismatch")
    if body.get("bars") != EXPECTED_BARS:
        raise ValueError("design semantics bar range mismatch")
    if body.get("meters") != EXPECTED_METER_LIST:
        raise ValueError("design semantics meter set mismatch")
    if body.get("ticks_per_beat") != EXPECTED_PPQ_LIST:
        raise ValueError("design semantics PPQ set mismatch")
    if body.get("splits") != list(EXPECTED_SPLITS):
        raise ValueError("design semantics split set mismatch")
    if body.get("claim_boundary") != EXPECTED_CLAIM_BOUNDARY:
        raise ValueError("design claim boundary mismatch")
    expected_counts = {
        "negative_per_split": 120,
        "negative_total": 240,
        "positive_per_split": 60,
        "positive_total": 120,
    }
    actual_counts = {
        "negative_per_split": counts[("development", "certified_negative")],
        "negative_total": sum(counts[(split, "certified_negative")] for split in EXPECTED_SPLITS),
        "positive_per_split": counts[("development", "planted_positive")],
        "positive_total": sum(counts[(split, "planted_positive")] for split in EXPECTED_SPLITS),
    }
    if body.get("case_counts") != expected_counts or actual_counts != expected_counts:
        raise ValueError("design case count semantics mismatch")

    expected_negative = {
        "oracle_pair_count": 0,
        "pair_budget_reached": False,
        "exhaustive_pair_enumeration": True,
        "all_eligible_pairs_compared_under_budget": True,
        "bar_counts": list(BAR_COUNTS),
        "timing_tolerance_beats": [1, 12],
        "hit_error_fraction": [1, 10],
        "min_hits": MIN_HITS,
        "min_pitches": MIN_PITCHES,
        "pair_comparison_limit": EXPECTED_PAIR_LIMIT,
    }
    if body.get("negative_acceptance") != expected_negative:
        raise ValueError("negative acceptance semantics mismatch")
    expected_positive = {
        "known_repeated_bar_regions": True,
        "target_pairs_must_be_oracle_admissible": True,
        "coverage_definition": EXPECTED_POSITIVE_COVERAGE,
    }
    if body.get("positive_acceptance") != expected_positive:
        raise ValueError("positive acceptance semantics mismatch")
    expected_uniqueness = {
        "reject_exact_arrangement_sha256_collision": True,
        "reject_beat_normalized_arrangement_sha256_collision": True,
        "scope": "all accepted controls",
    }
    if body.get("uniqueness") != expected_uniqueness:
        raise ValueError("uniqueness semantics mismatch")
    generation = body.get("generation")
    if generation != {
        "max_attempts": 10000,
        "pattern_generator": "standard-library random.Random seeded by namespace, split, kind, index and attempt",
        "conditional_negative_bias": "negative cases are conditioned on zero admissible pairs under the stated symbolic oracle",
    }:
        raise ValueError("generation semantics mismatch")
    if design.get("config") != _expected_study_config():
        raise ValueError("config semantics mismatch")
    expected_artifacts = [
        "design.json", "labels.json", "raw_results.json", "aggregate.json",
        *[case["midi_path"] for case in cases],
    ]
    if body.get("result_artifacts") != expected_artifacts:
        raise ValueError("design result artifact set mismatch")
    if design.get("case_count") != len(cases):
        raise ValueError("design case count mismatch")
    if design.get("case_cohort_sha256") != cohort_hash:
        raise ValueError("design case cohort link mismatch")


def _validate_generation_audit(
    *,
    design: dict[str, Any],
    labels: dict[str, Any],
    aggregate: dict[str, Any],
    cases: list[dict[str, Any]],
    case_audits: dict[str, dict[str, Any]],
    exact_hashes: set[str],
    beat_hashes: set[str],
) -> None:
    generation = design.get("generation_audit")
    if not isinstance(generation, dict):
        raise ValueError("missing generation audit")
    if labels.get("generation_audit") != generation or aggregate.get("generation_audit") != generation:
        raise ValueError("generation audit differs across frozen results")
    expected_requested = {
        "development_negative": 120,
        "development_positive": 60,
        "negative_cases": 240,
        "positive_cases": 120,
        "test_negative": 120,
        "test_positive": 60,
    }
    if generation.get("requested") != expected_requested:
        raise ValueError("generation requested counts mismatch")
    if generation.get("max_attempts") != 10000:
        raise ValueError("generation max attempt mismatch")
    attempts = generation.get("attempts")
    if not isinstance(attempts, int) or attempts < len(cases) or attempts > generation["max_attempts"]:
        raise ValueError("generation attempt count is inconsistent")
    if cases and attempts < max(case.get("attempt", -1) for case in cases) + 1:
        raise ValueError("generation attempts do not cover accepted cases")
    rejected = generation.get("rejected")
    if not isinstance(rejected, dict) or any(
        not isinstance(value, int) or value < 0 for value in rejected.values()
    ):
        raise ValueError("generation rejection counts are invalid")
    expected = {
        "exact_unique_arrangements": len(exact_hashes),
        "beat_unique_arrangements": len(beat_hashes),
        "negative_oracle_pair_budget_reached": sum(
            bool(case_audits[case["case_id"]]["oracle"]["pair_budget_reached"])
            for case in cases if case["kind"] == "certified_negative"
        ),
        "negative_oracle_pair_count_total": sum(
            case_audits[case["case_id"]]["oracle"]["oracle_pair_count"]
            for case in cases if case["kind"] == "certified_negative"
        ),
        "positive_target_pair_count": sum(
            len(case["target_pair_keys"]) for case in cases if case["kind"] == "planted_positive"
        ),
        "positive_target_pairs_oracle_confirmed": sum(
            bool(case_audits[case["case_id"]]["target_pairs_oracle_confirmed"])
            for case in cases if case["kind"] == "planted_positive"
        ),
    }
    for field, value in expected.items():
        if generation.get(field) != value:
            raise ValueError(f"generation audit mismatch: {field}")


def _validate_and_replay(
    study: Path,
    *,
    api: SnapshotApi,
    receipt: dict[str, Any],
    design: dict[str, Any],
    labels: dict[str, Any],
    raw: dict[str, Any],
    aggregate: dict[str, Any],
) -> dict[str, Any]:
    cases = raw.get("cases")
    if not isinstance(cases, list) or raw.get("case_count") != len(cases):
        raise ValueError("raw case cohort count mismatch")
    receipt_cases = receipt.get("case_cohort")
    if cases != receipt_cases:
        raise ValueError("raw cases differ from frozen receipt cohort")
    labels_by_id = {row.get("case_id"): row for row in labels.get("labels", [])}
    if len(labels_by_id) != len(cases) or set(labels_by_id) != {case["case_id"] for case in cases}:
        raise ValueError("label cohort does not match raw cases")

    counts = Counter((case["split"], case["kind"]) for case in cases)
    expected_counts = {
        (split, kind): (120 if kind == "certified_negative" else 60)
        for split in EXPECTED_SPLITS
        for kind in EXPECTED_KINDS
    }
    if counts != expected_counts:
        raise ValueError(f"unexpected cohort counts: {counts}")
    _validate_embedded_design(
        receipt=receipt,
        receipt_file_sha256=_bytes_sha256((study / "experiment_receipt.json").read_bytes()),
        design=design,
        labels=labels,
        raw=raw,
        aggregate=aggregate,
        cases=cases,
        counts=counts,
    )

    exact_hashes: set[str] = set()
    beat_hashes: set[str] = set()
    oracle_pair_comparisons = 0
    oracle_pair_budgets = 0
    case_audits: dict[str, dict[str, Any]] = {}
    replay_rows: dict[str, dict[str, dict[str, Any]]] = {"exact": {}, "tolerant": {}}
    method_rows = raw.get("methods", {})
    method_rows_by_id: dict[str, dict[str, dict[str, Any]]] = {}
    for mode in ("exact", "tolerant"):
        rows = method_rows.get(mode)
        if not isinstance(rows, list) or len(rows) != len(cases):
            raise ValueError(f"method row count mismatch: {mode}")
        indexed = {row.get("case_id"): row for row in rows}
        if len(indexed) != len(rows) or set(indexed) != {case["case_id"] for case in cases}:
            raise ValueError(f"method row IDs do not match cohort: {mode}")
        method_rows_by_id[mode] = indexed

    for case in cases:
        case_id = case["case_id"]
        if case["split"] not in EXPECTED_SPLITS or case["kind"] not in EXPECTED_KINDS:
            raise ValueError(f"invalid case grouping: {case_id}")
        if not MIN_BARS <= case["bars"] <= MAX_BARS:
            raise ValueError(f"bar range mismatch: {case_id}")
        if tuple(case["meter"]) not in EXPECTED_METERS or case["ticks_per_beat"] not in EXPECTED_PPQS:
            raise ValueError(f"geometry mismatch: {case_id}")
        midi_path = case["midi_path"]
        midi_data = _study_file(study, midi_path).read_bytes()
        if len(midi_data) != case["midi_bytes"] or _bytes_sha256(midi_data) != case["midi_sha256"]:
            raise ValueError(f"MIDI hash mismatch: {case_id}")
        label = labels_by_id[case_id]
        for field in ("split", "kind", "midi_path", "midi_sha256", "target_intervals", "target_pair_keys"):
            if label.get(field) != case.get(field):
                raise ValueError(f"label mismatch for {case_id}: {field}")
        if label.get("oracle_pair_count") != case["oracle"].get("oracle_pair_count"):
            raise ValueError(f"label mismatch for {case_id}: oracle_pair_count")
        if label.get("oracle_pair_budget_reached") != case["oracle"].get("pair_budget_reached"):
            raise ValueError(f"label mismatch for {case_id}: oracle_pair_budget_reached")
        expected_negative_label = (
            case["kind"] == "certified_negative"
            and case["oracle"]["oracle_pair_count"] == 0
            and not case["oracle"]["pair_budget_reached"]
        )
        if label.get("negative_certified") != expected_negative_label:
            raise ValueError(f"negative label mismatch for {case_id}")

        song = api.midi.load_midi(_study_file(study, midi_path))
        if song.ticks_per_beat != case["ticks_per_beat"]:
            raise ValueError(f"parsed PPQ mismatch: {case_id}")
        if not song.parts or not all(part.is_drum for part in song.parts):
            raise ValueError(f"saved MIDI is not drum-only: {case_id}")
        exact_hash, beat_hash = _arrangement_hashes_for_case(song, case["bars"])
        if exact_hash != case["exact_arrangement_sha256"]:
            raise ValueError(f"exact arrangement hash mismatch: {case_id}")
        if beat_hash != case["beat_arrangement_sha256"]:
            raise ValueError(f"beat arrangement hash mismatch: {case_id}")
        if exact_hash in exact_hashes or beat_hash in beat_hashes:
            raise ValueError(f"duplicate arrangement hash: {case_id}")
        exact_hashes.add(exact_hash)
        beat_hashes.add(beat_hash)

        oracle = _oracle_certificate(api, song)
        saved_oracle = case["oracle"]
        for field in (
            "eligible_window_count", "oracle_pair_count", "pair_comparisons",
            "pair_budget", "pair_budget_reached", "exhaustive_pair_enumeration",
        ):
            if oracle[field] != saved_oracle[field]:
                raise ValueError(f"oracle mismatch for {case_id}: {field}")
        if case["kind"] == "certified_negative" and (
            oracle["oracle_pair_count"] != 0 or oracle["pair_budget_reached"]
        ):
            raise ValueError(f"negative is not oracle certified: {case_id}")
        target_keys = tuple(tuple(item) for item in case["target_pair_keys"])
        if case["kind"] == "planted_positive":
            if tuple(_derived_target_pairs(case)) != target_keys:
                raise ValueError(f"positive target labels are inconsistent: {case_id}")
            if not set(target_keys).issubset(oracle["pairs"]):
                raise ValueError(f"positive targets are not oracle confirmed: {case_id}")
        elif target_keys:
            raise ValueError(f"negative has positive target labels: {case_id}")
        expected_positive_label = (
            case["kind"] == "planted_positive"
            and set(target_keys).issubset(oracle["pairs"])
            and not oracle["pair_budget_reached"]
        )
        if label.get("positive_oracle_confirmed") != expected_positive_label:
            raise ValueError(f"positive label mismatch for {case_id}")
        oracle_pair_comparisons += oracle["pair_comparisons"]
        oracle_pair_budgets += oracle["pair_budget"]

        case_audits[case_id] = {
            "case_id": case_id,
            "split": case["split"],
            "kind": case["kind"],
            "midi_sha256": case["midi_sha256"],
            "exact_arrangement_verified": True,
            "beat_arrangement_verified": True,
            "oracle": {field: oracle[field] for field in (
                "eligible_window_count", "oracle_pair_count", "pair_comparisons",
                "pair_budget", "pair_budget_reached", "exhaustive_pair_enumeration",
            )},
            "target_pairs_oracle_confirmed": expected_positive_label,
        }

        for mode in ("exact", "tolerant"):
            row = method_rows_by_id[mode][case_id]
            result = api.drums.extract_drums(
                song, api.drums.DrumConfig(mode=mode, top_k=3)
            )
            phrases = result["phrases"]
            edges = _direct_edges(phrases)
            targets = set(target_keys)
            covered = len(targets & edges)
            stats_match, stat_differences = _require_replay_stats_match(
                row["detector_stats"], result["stats"], mode=mode, case_id=case_id
            )
            expected_fields = {
                "split": case["split"],
                "kind": case["kind"],
                "oracle_pair_count": oracle["oracle_pair_count"],
                "oracle_pair_budget_reached": oracle["pair_budget_reached"],
                "target_pair_count": len(targets),
                "target_pairs_covered_by_direct_detector_edges": covered,
                "detector_phrase_count": len(phrases),
                "negative_case_with_output": case["kind"] == "certified_negative" and bool(phrases),
            }
            for field, expected in expected_fields.items():
                if row.get(field) != expected:
                    raise ValueError(f"replay metric mismatch {mode}/{case_id}: {field}")
            replay_case = {
                "stats_match": stats_match,
                "stats_differences": stat_differences,
                "detector_phrase_count": len(phrases),
                "direct_target_edges_covered": covered,
                "target_pair_count": len(targets),
            }
            if case["kind"] == "planted_positive":
                replay_case["one_family_covers_all_target_windows"] = _family_covers_targets(
                    phrases, case["target_intervals"]
                )
            replay_rows[mode][case_id] = replay_case
            case_audits[case_id].setdefault("replay", {})[mode] = replay_case

    if len(exact_hashes) != len(cases) or len(beat_hashes) != len(cases):
        raise ValueError("cohort arrangement hashes are not unique")
    _validate_generation_audit(
        design=design,
        labels=labels,
        aggregate=aggregate,
        cases=cases,
        case_audits=case_audits,
        exact_hashes=exact_hashes,
        beat_hashes=beat_hashes,
    )

    aggregate_checks: dict[str, dict[str, Any]] = {}
    for mode in ("exact", "tolerant"):
        actual = _aggregate_from_raw(method_rows[mode])
        saved = aggregate["methods"][mode]["overall"]
        differences = _compare_aggregate(saved, actual)
        if differences:
            raise ValueError(f"aggregate mismatch for {mode}: {differences}")
        by_split = {}
        for split in EXPECTED_SPLITS:
            split_rows = [row for row in method_rows[mode] if row["split"] == split]
            split_actual = _aggregate_from_raw(split_rows)
            split_saved = aggregate["methods"][mode]["by_split"][split]
            split_differences = _compare_aggregate(split_saved, split_actual)
            if split_differences:
                raise ValueError(f"split aggregate mismatch {mode}/{split}: {split_differences}")
            by_split[split] = split_actual
        aggregate_checks[mode] = {"overall": actual, "by_split": by_split}

    family_recovery = {}
    for mode in ("exact", "tolerant"):
        family_recovery[mode] = {}
        for split in EXPECTED_SPLITS:
            positive_ids = [
                case["case_id"] for case in cases
                if case["kind"] == "planted_positive" and case["split"] == split
            ]
            covered = sum(
                replay_rows[mode][case_id]["one_family_covers_all_target_windows"]
                for case_id in positive_ids
            )
            family_recovery[mode][split] = {
                "positive_cases": len(positive_ids),
                "families_covering_all_labelled_target_windows": covered,
                "family_recovery_rate": covered / len(positive_ids) if positive_ids else None,
            }

    return {
        "case_count": len(cases),
        "split_kind_counts": {
            f"{split}/{kind}": counts[(split, kind)]
            for split in EXPECTED_SPLITS for kind in EXPECTED_KINDS
        },
        "unique_exact_arrangements": len(exact_hashes),
        "unique_beat_arrangements": len(beat_hashes),
        "oracle": {
            "pair_comparisons_total": oracle_pair_comparisons,
            "pair_budget_total": oracle_pair_budgets,
            "pair_budget_max_per_case": max(
                case_audits[case["case_id"]]["oracle"]["pair_budget"]
                for case in cases
            ),
            "negative_cases_with_admissible_pairs": sum(
                case_audits[case["case_id"]]["oracle"]["oracle_pair_count"] > 0
                for case in cases if case["kind"] == "certified_negative"
            ),
            "negative_admissible_pair_count": sum(
                case_audits[case["case_id"]]["oracle"]["oracle_pair_count"]
                for case in cases if case["kind"] == "certified_negative"
            ),
            "budget_reached_cases": sum(
                case_audits[case["case_id"]]["oracle"]["pair_budget_reached"]
                for case in cases
            ),
        },
        "aggregate_recomputed_from_raw": aggregate_checks,
        "family_recovery_posthoc": family_recovery,
        "cases": [case_audits[case["case_id"]] for case in cases],
    }


def _write_json(path: Path, value: object) -> bytes:
    data = json.dumps(value, indent=2, sort_keys=True, allow_nan=False).encode("utf-8") + b"\n"
    path.write_bytes(data)
    return data


def verify_audit_output(output: Path) -> dict[str, Any]:
    """Verify the small receipt that binds an audit report and its inputs."""
    output = output.resolve(strict=True)
    receipt = _read_json(output / "audit_receipt.json")
    if (
        receipt.get("schema_version") != "samuged-certified-drum-audit-v1"
        or receipt.get("status") != "completed"
    ):
        raise ValueError("invalid certified drum audit receipt")
    artifacts = receipt.get("artifacts")
    if not isinstance(artifacts, dict) or set(artifacts) != {"audit.json", "input_manifest.json"}:
        raise ValueError("audit receipt artifact set mismatch")
    for relative, expected in artifacts.items():
        data = _study_file(output, relative).read_bytes()
        if expected.get("bytes") != len(data) or expected.get("sha256") != _bytes_sha256(data):
            raise ValueError(f"audit artifact changed: {relative}")
    if receipt.get("audit_sha256") != artifacts["audit.json"].get("sha256"):
        raise ValueError("audit receipt report hash link mismatch")
    manifest = _read_json(output / "input_manifest.json")
    manifest_hash = _json_sha256(manifest)
    if manifest_hash != receipt.get("input_manifest_sha256"):
        raise ValueError("audit input manifest hash mismatch")
    audit = _read_json(output / "audit.json")
    if audit.get("input_manifest_sha256") != manifest_hash:
        raise ValueError("audit report input manifest link mismatch")
    if audit.get("study_source_snapshot_sha256") != manifest.get("study_source_snapshot_sha256"):
        raise ValueError("audit report source snapshot link mismatch")
    if audit.get("audit_script_sha256") != manifest.get("audit_script_sha256"):
        raise ValueError("audit report script link mismatch")
    return audit


def audit_study(study: Path, output: Path) -> dict[str, Any]:
    """Audit one completed study into a new output directory."""
    study = study.resolve(strict=True)
    output = output.resolve()
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise FileExistsError(f"audit output must be new or empty: {output}")
    started = time.monotonic()
    receipt = _read_json(study / "experiment_receipt.json")
    snapshot = _verify_source_snapshot(study, receipt)
    snapshot_root = snapshot["root"]
    with _snapshot_api(snapshot_root) as api:
        completion = api.experiment.verify_completed_experiment(study)
        design = _read_json(study / "design.json")
        labels = _read_json(study / "labels.json")
        raw = _read_json(study / "raw_results.json")
        aggregate = _read_json(study / "aggregate.json")
        report = _validate_and_replay(
            study,
            api=api,
            receipt=receipt,
            design=design,
            labels=labels,
            raw=raw,
            aggregate=aggregate,
        )

    required = list(completion["required_artifacts"])
    audit_script_sha256 = _bytes_sha256(Path(__file__).resolve().read_bytes())
    input_entries = _artifact_manifest(
        study,
        ["experiment_receipt.json", "source_snapshot.json", "completion_receipt.json", *required],
    )
    input_manifest = {
        "version": VERSION,
        "study_completion_receipt_sha256": _bytes_sha256(
            (study / "completion_receipt.json").read_bytes()
        ),
        "study_source_snapshot_sha256": snapshot["snapshot_sha256"],
        "audit_script_sha256": audit_script_sha256,
        "artifacts": input_entries,
    }
    input_manifest_hash = _json_sha256(input_manifest)
    report = {
        "version": VERSION,
        "study": str(study),
        "study_completion_receipt_sha256": input_manifest["study_completion_receipt_sha256"],
        "study_source_snapshot_sha256": snapshot["snapshot_sha256"],
        "audit_script_sha256": audit_script_sha256,
        "input_manifest_sha256": input_manifest_hash,
        "source_snapshot_file_count": snapshot["file_count"],
        "runtime_seconds": time.monotonic() - started,
        **report,
        "claim_boundary": (
            "independent integrity, oracle and replay audit; posthoc planted-family "
            "diagnostic, not a human specificity estimate"
        ),
    }
    output.mkdir(parents=True, exist_ok=True)
    input_manifest_bytes = _write_json(output / "input_manifest.json", input_manifest)
    report_bytes = _write_json(output / "audit.json", report)
    completion_audit = {
        "schema_version": "samuged-certified-drum-audit-v1",
        "status": "completed",
        "input_manifest_sha256": _json_sha256(input_manifest),
        "audit_sha256": _bytes_sha256(report_bytes),
        "artifacts": {
            "input_manifest.json": {
                "bytes": len(input_manifest_bytes),
                "sha256": _bytes_sha256(input_manifest_bytes),
            },
            "audit.json": {
                "bytes": len(report_bytes),
                "sha256": _bytes_sha256(report_bytes),
            },
        },
    }
    _write_json(output / "audit_receipt.json", completion_audit)
    return report


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    print(json.dumps(audit_study(args.study, args.output), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
