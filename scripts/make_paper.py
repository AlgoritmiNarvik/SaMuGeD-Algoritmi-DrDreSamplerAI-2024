"""Render a concise paper from measured and audited local artifacts.

The generator fails closed. Dataset claims require an audit bound to the exact
manifests, build configuration and summary. Evaluation claims are recomputed
from adjacent raw results before they are rendered.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
from html import escape
import hashlib
import json
import math
import os
from pathlib import Path
import random
from statistics import mean, median
from typing import Any, Iterator

from reportlab.graphics.shapes import Drawing, Line, Polygon, Rect, String
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from samuged.dataset import digest, file_digest
from samuged.drum_stress import aggregate_results as aggregate_stress
from samuged.evaluate import CASE_KINDS, aggregate_results as aggregate_melody
from samuged.evaluate_aligned import aggregate_real_rows
from samuged.evaluate_drums import aggregate_results as aggregate_drums
from samuged.experiment import receipt_links, verify_start_receipt
try:
    from scripts.package_dataset import _selection_replay_binding
    from scripts.screen_splits import verify_screening
except ModuleNotFoundError as exc:
    if exc.name != "scripts":
        raise
    from package_dataset import _selection_replay_binding
    from screen_splits import verify_screening


INK = colors.HexColor("#172d40")
BLUE = colors.HexColor("#265e83")
MUTED = colors.HexColor("#536272")
PALE = colors.HexColor("#edf3f6")
ALGORITHMS = {
    "reference", "aligned", "aligned_indexed", "aligned_closed",
    "aligned_melody",
}
ALGORITHM_LABELS = {
    "reference": "Reference",
    "aligned": "Aligned",
    "aligned_indexed": "Aligned indexed",
    "aligned_closed": "Closed selection",
    "aligned_melody": "Melody prior",
}
DATASET_FILES = {
    "source_manifest_sha256": "sources.jsonl",
    "phrase_manifest_sha256": "phrases.jsonl",
    "build_config_sha256": "build_config.json",
    "summary_sha256": "summary.json",
}
DATE_POLICY = (
    "explicit --report-date, otherwise SOURCE_DATE_EPOCH in UTC, otherwise the "
    "validated melodic experiment receipt started_at_utc date; fail if none is available"
)


def read(path: Path) -> dict:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read JSON object: {path}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return value


def _sha256_json(value: Any) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _same(actual: Any, expected: Any, context: str) -> None:
    """Require every recomputed field to be present and equal."""
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            raise ValueError(f"{context} has the wrong type")
        for key, value in expected.items():
            if key not in actual:
                raise ValueError(f"{context} is missing {key}")
            _same(actual[key], value, f"{context}.{key}")
        return
    if isinstance(expected, list):
        if not isinstance(actual, list) or len(actual) != len(expected):
            raise ValueError(f"{context} differs from raw results")
        for index, value in enumerate(expected):
            _same(actual[index], value, f"{context}[{index}]")
        return
    if isinstance(expected, float):
        if isinstance(actual, bool) or not isinstance(actual, (int, float)):
            raise ValueError(f"{context} has the wrong type")
        if not math.isclose(float(actual), expected, rel_tol=1e-12, abs_tol=1e-12):
            raise ValueError(f"{context} differs from raw results")
        return
    if actual != expected:
        raise ValueError(f"{context} differs from raw results")


def validate_dataset(dataset: Path) -> dict:
    dataset = Path(dataset).resolve(strict=True)
    audit_sha256 = file_digest(dataset / "audit.json")
    summary = read(dataset / "summary.json")
    audit = read(dataset / "audit.json")
    build = read(dataset / "build_config.json")
    if file_digest(dataset / "audit.json") != audit_sha256:
        raise ValueError("dataset audit changed while being read")
    if (
        audit.get("passed") is not True
        or audit.get("failure_count") != 0
        or audit.get("failures", []) != []
    ):
        raise ValueError("paper requires a passing zero-failure dataset audit")
    run_key = summary.get("run_key")
    if not run_key or audit.get("run_key") != run_key or build.get("run_key") != run_key:
        raise ValueError("audit, summary and build configuration have different run keys")
    actual_hashes = {}
    for field, filename in DATASET_FILES.items():
        digest = file_digest(dataset / filename)
        actual_hashes[field] = digest
        if audit.get(field) != digest:
            raise ValueError(f"audit is not bound to the current {filename}")
    if summary.get("source_manifest_sha256") != actual_hashes["source_manifest_sha256"]:
        raise ValueError("source manifest hash differs from the dataset summary")
    if summary.get("phrase_manifest_sha256") != actual_hashes["phrase_manifest_sha256"]:
        raise ValueError("phrase manifest hash differs from the dataset summary")
    source_files = summary.get("source_files")
    discovered_source_files = summary.get("discovered_source_files")
    full_scope = (
        isinstance(source_files, int) and not isinstance(source_files, bool)
        and isinstance(discovered_source_files, int)
        and not isinstance(discovered_source_files, bool)
        and source_files == discovered_source_files
        and summary.get("cohort_limit") is None
    )
    if full_scope and audit.get("full_source_coverage_required") is not True:
        raise ValueError("full-scope dataset audit lacks required source coverage")
    algorithm = build.get("algorithm") or "reference"
    if algorithm not in ALGORITHMS:
        raise ValueError(f"unsupported extraction algorithm: {algorithm}")
    return {
        "path": dataset, "summary": summary, "audit": audit, "build": build,
        "algorithm": algorithm, "hashes": actual_hashes, "full_scope": full_scope,
        "audit_sha256": audit_sha256,
    }


def _manifest_rows(path: Path, expected_sha256: str) -> Iterator[dict]:
    """Read newline-delimited objects and detect mutation across the scan."""
    if file_digest(path) != expected_sha256:
        raise ValueError(f"manifest changed before recount: {path}")
    try:
        with path.open(encoding="utf-8", newline=None) as stream:
            for line_number, line in enumerate(stream, 1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(
                        f"invalid JSON in {path} line {line_number}: {exc.msg}"
                    ) from exc
                if not isinstance(row, dict):
                    raise ValueError(f"{path} line {line_number} is not an object")
                yield row
    except (OSError, UnicodeError) as exc:
        raise ValueError(f"cannot read manifest: {path}") from exc
    if file_digest(path) != expected_sha256:
        raise ValueError(f"manifest changed during recount: {path}")


def _dataset_counts(dataset_info: dict) -> dict:
    """Recount paper comparison fields from the two bound manifests."""
    identities: dict[str, dict] = {}
    repairs: dict[str, Any] = {}
    status = Counter()
    outcomes = Counter()
    melodic_search_limited = 0
    melodic_shortlist_limited = 0
    drum_limited = 0
    source_count = 0
    for row in _manifest_rows(
        dataset_info["path"] / "sources.jsonl",
        dataset_info["hashes"]["source_manifest_sha256"],
    ):
        source_count += 1
        source_id = row.get("source_id")
        if not isinstance(source_id, str) or not source_id or source_id in identities:
            raise ValueError("source manifest has a missing or duplicate source_id")
        identity = {
            key: row.get(key) for key in ("source_path", "source_sha256", "status")
        }
        if any(not isinstance(identity[key], str) or not identity[key]
               for key in identity):
            raise ValueError(f"source identity is incomplete for {source_id}")
        identities[source_id] = identity
        source_repairs = row.get("metadata_repairs", [])
        if not isinstance(source_repairs, list):
            raise ValueError(f"metadata repairs are malformed for {source_id}")
        repairs[source_id] = source_repairs
        status[identity["status"]] += 1
        outcome = row.get("outcome")
        if isinstance(outcome, str) and outcome:
            outcomes[outcome] += 1
        melodic_search_limited += row.get("search_limited") is True
        melodic_shortlist_limited += row.get("curation_truncated") is True
        drum = row.get("drum_stats")
        drum_limited += isinstance(drum, dict) and drum.get("search_limited") is True
    phrase_counts = Counter()
    phrase_sources = {"melodic": set(), "percussion": set()}
    phrase_ids: set[str] = set()
    for row in _manifest_rows(
        dataset_info["path"] / "phrases.jsonl",
        dataset_info["hashes"]["phrase_manifest_sha256"],
    ):
        phrase_id, source_id, kind = (
            row.get("phrase_id"), row.get("source_id"), row.get("kind")
        )
        if not isinstance(phrase_id, str) or not phrase_id or phrase_id in phrase_ids:
            raise ValueError("phrase manifest has a missing or duplicate phrase_id")
        if source_id not in identities:
            raise ValueError(f"phrase {phrase_id} references an unknown source")
        if kind not in phrase_sources:
            raise ValueError(f"phrase {phrase_id} has an unsupported kind")
        phrase_ids.add(phrase_id)
        phrase_counts[kind] += 1
        phrase_sources[kind].add(source_id)
    counts = {
        "source_files": source_count,
        "source_status": dict(sorted(status.items())),
        "source_outcomes": dict(sorted(outcomes.items())),
        "phrase_counts": {
            kind: phrase_counts[kind] for kind in ("melodic", "percussion")
        },
        "source_files_with_melodic_phrases": len(phrase_sources["melodic"]),
        "source_files_with_percussion_phrases": len(phrase_sources["percussion"]),
        "search_limited_files": melodic_search_limited,
        "curation_truncated_files": melodic_shortlist_limited,
        "drum_search_limited_files": drum_limited,
    }
    summary = dataset_info["summary"]
    for field, value in counts.items():
        if _sha256_json(summary.get(field)) != _sha256_json(value):
            raise ValueError(f"dataset summary {field} differs from manifest recount")
    identity_rows = [
        {"source_id": source_id, **identities[source_id]}
        for source_id in sorted(identities)
    ]
    repair_rows = [
        {"source_id": source_id, "metadata_repairs": repairs[source_id]}
        for source_id in sorted(repairs)
    ]
    return {
        **counts,
        "successful_files": status["ok"],
        "no_match_files": outcomes["no_match"],
        "source_identities": identities,
        "metadata_repairs": repairs,
        "source_identity_sha256": _sha256_json(identity_rows),
        "metadata_repairs_sha256": _sha256_json(repair_rows),
    }


def validate_comparison_datasets(
    primary: dict, comparison_paths: list[Path] | tuple[Path, ...] | None,
) -> list[dict]:
    """Validate at most three full builds over the primary source corpus."""
    paths = list(comparison_paths or [])
    if len(paths) > 3:
        raise ValueError("at most three comparison datasets are supported")
    if not paths:
        return []
    if not primary.get("full_scope") or primary["audit"].get(
        "full_source_coverage_required"
    ) is not True:
        raise ValueError("comparison requires a full-scope primary dataset")
    primary_counts = _dataset_counts(primary)
    primary["manifest_counts"] = primary_counts
    primary_recovery = primary["build"].get("recover_invalid_keys", False)
    if not isinstance(primary_recovery, bool):
        raise ValueError("primary metadata repair policy must be boolean")
    seen_algorithms = {primary["algorithm"]}
    seen_paths = {primary["path"]}
    comparisons = []
    for path in paths:
        info = validate_dataset(path)
        if info["path"] in seen_paths:
            raise ValueError("comparison dataset paths must be distinct")
        seen_paths.add(info["path"])
        if info["algorithm"] in seen_algorithms:
            raise ValueError("primary and comparison algorithms must be distinct")
        seen_algorithms.add(info["algorithm"])
        if not info.get("full_scope") or info["audit"].get(
            "full_source_coverage_required"
        ) is not True:
            raise ValueError("comparison dataset must have a full-scope audit")
        counts = _dataset_counts(info)
        if counts["source_identities"] != primary_counts["source_identities"]:
            raise ValueError("comparison dataset has different source identities")
        recovery = info["build"].get("recover_invalid_keys", False)
        if not isinstance(recovery, bool) or recovery != primary_recovery:
            raise ValueError("comparison dataset has a different metadata repair policy")
        if counts["metadata_repairs"] != primary_counts["metadata_repairs"]:
            raise ValueError("comparison dataset has different metadata repair receipts")
        info["manifest_counts"] = counts
        comparisons.append(info)
    return comparisons


def _recheck_dataset_bindings(dataset_info: dict) -> None:
    if file_digest(dataset_info["path"] / "audit.json") != dataset_info["audit_sha256"]:
        raise ValueError("dataset input changed before paper receipt: audit.json")
    for field, filename in DATASET_FILES.items():
        if file_digest(dataset_info["path"] / filename) != dataset_info["hashes"][field]:
            raise ValueError(f"dataset input changed before paper receipt: {filename}")


def phrase_profile(dataset_info: dict) -> dict:
    """Reconstruct compact corpus descriptions directly from bound phrase rows."""
    values = {kind: {key: [] for key in ("notes", "beats", "occurrences")}
              for kind in ("melodic", "percussion")}
    path = dataset_info["path"] / "phrases.jsonl"
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            target = values[row["kind"]]
            target["notes"].append(row["note_count"])
            target["beats"].append((row["end_tick"] - row["start_tick"]) / row["ticks_per_beat"])
            target["occurrences"].append(row["occurrence_count"])
    if file_digest(path) != dataset_info["hashes"]["phrase_manifest_sha256"]:
        raise ValueError("phrase manifest changed while reconstructing its profile")
    for kind, fields in values.items():
        if len(fields["notes"]) != dataset_info["summary"]["phrase_counts"].get(kind, 0):
            raise ValueError("phrase profile count differs from dataset summary")
    return {kind: {key: median(items) if items else None for key, items in fields.items()}
            for kind, fields in values.items()}


def _validate_receipt(directory: Path, aggregate: dict, raw: dict) -> dict | None:
    receipt_hash = aggregate.get("receipt_sha256")
    if receipt_hash is None:
        return None
    receipt_path = directory / "experiment_receipt.json"
    if file_digest(receipt_path) != receipt_hash:
        raise ValueError(f"experiment receipt hash mismatch: {directory}")
    receipt = verify_start_receipt(directory)
    if receipt.get("status") != "started":
        raise ValueError(f"unexpected experiment receipt status: {directory}")
    for payload in ("config", "design", "case_cohort"):
        field = f"{payload}_sha256"
        if payload in receipt and receipt.get(field) != _sha256_json(receipt[payload]):
            raise ValueError(f"experiment receipt {field} mismatch: {directory}")
    for field in (
        "receipt_sha256", "config_sha256", "design_sha256",
        "case_cohort_sha256", "source_snapshot_sha256", "snapshot_sha256",
    ):
        values = [obj[field] for obj in (aggregate, raw) if field in obj]
        if values and any(value != values[0] for value in values):
            raise ValueError(f"aggregate and raw result {field} mismatch: {directory}")
        if field in receipt and values and receipt[field] != values[0]:
            raise ValueError(f"receipt and result {field} mismatch: {directory}")
    snapshot = receipt.get("source_snapshot", {})
    if snapshot and aggregate.get("snapshot_sha256") != snapshot.get("snapshot_sha256"):
        raise ValueError(f"source snapshot hash mismatch: {directory}")
    for result in (aggregate, raw):
        if any(result.get(key) != value for key, value in receipt_links(receipt).items()):
            raise ValueError(f"result is missing or disagrees with frozen receipt links: {directory}")
    return receipt


def _load_pair(path: Path, *, allow_legacy_design: bool = False) -> tuple[dict, dict, dict | None, dict[str, Path]]:
    path = Path(path).resolve(strict=True)
    directory = path.parent
    aggregate = read(path)
    raw_path = directory / "raw_results.json"
    raw = read(raw_path)
    receipt = _validate_receipt(directory, aggregate, raw)
    if receipt is None and not allow_legacy_design:
        raise ValueError(f"evaluation requires a frozen experiment receipt: {directory}")
    inputs = {"aggregate": path, "raw": raw_path}
    if receipt is not None:
        inputs["experiment_receipt"] = directory / "experiment_receipt.json"
        snapshot = directory / "source_snapshot.json"
        if snapshot.is_file():
            inputs["source_snapshot.json"] = snapshot
        completion = directory / "completion_receipt.json"
        if completion.is_file():
            from samuged.experiment import verify_completed_experiment
            verify_completed_experiment(directory)
            inputs["completion_receipt"] = completion
    return aggregate, raw, receipt, inputs


def validate_themes(path: Path, input_root: Path, input_audit: Path) -> tuple[dict, dict[str, Path]]:
    from samuged.audit_themes import verify
    from samuged.evaluate_themes import SONG_IDS
    directory = Path(path).resolve(strict=True).parent
    verify(directory, input_root, input_audit)
    inputs = {name: directory / name for name in (
        "aggregate.json", "raw_results.json", "experiment_receipt.json",
        "completion_receipt.json", "source_snapshot.json",
    )}
    inputs["input_audit"] = Path(input_audit)
    inputs["download_receipts"] = Path(input_root) / "download_receipts.json"
    inputs.update({f"archive_{song}": Path(input_root) / f"{song}.zip" for song in SONG_IDS})
    return read(directory / "aggregate.json"), inputs


def _selection_theme_groups(rows: list[dict]) -> dict:
    from samuged.evaluate_themes import ANNOTATORS, SONG_IDS
    methods = ("aligned_indexed", "aligned_closed", "aligned_melody")
    groups = {}
    for method in methods:
        for view in ("top1", "top3"):
            selected = [row for row in rows if row.get("method") == method and row.get("view") == view]
            per_song = {}
            for song in SONG_IDS:
                song_rows = [row for row in selected if row.get("song_id") == song]
                if len(song_rows) != len(ANNOTATORS):
                    raise ValueError("selection Theme annotation coverage mismatch")
                per_song[song] = {
                    metric: sum(row["metrics"][metric] for row in song_rows) / len(song_rows)
                    for metric in ("precision", "recall", "f1")
                }
            groups[f"{method}/{view}"] = {
                "song_count": len(per_song),
                "annotation_views": len(selected),
                "per_song_mean_over_annotators": per_song,
                "macro_over_songs": {
                    metric: sum(per_song[song][metric] for song in SONG_IDS) / len(SONG_IDS)
                    for metric in ("precision", "recall", "f1")
                },
            }
    return groups


def _selection_jku_groups(rows: list[dict]) -> dict:
    from samuged.evaluate_jku import EXPECTED_PIECES
    methods = ("aligned_indexed", "aligned_closed", "aligned_melody")
    groups = {}
    for variant in ("monophonic", "polyphonic"):
        for method in methods:
            selected = [
                row for row in rows
                if row.get("variant") == variant and row.get("method") == method
            ]
            if len(selected) != len(EXPECTED_PIECES):
                raise ValueError("selection JKU work coverage mismatch")
            metric_names = tuple(selected[0]["metrics"])
            groups[f"{variant}/{method}"] = {
                "works": len(selected),
                "macro_metrics": {
                    metric: sum(row["metrics"][metric] for row in selected) / len(selected)
                    for metric in metric_names
                },
                "search_limited_works": sum(
                    row["telemetry"]["search_limited"] for row in selected
                ),
                "curation_truncated_works": sum(
                    row["telemetry"]["curation_truncated"] for row in selected
                ),
                "runtime_seconds": sum(row["runtime_seconds"] for row in selected),
            }
    return groups


def validate_selection_external(
    path: Path, input_root: Path, input_audit: Path,
) -> tuple[dict, dict[str, Path]]:
    """Reconstruct selector metrics from frozen coordinates and official inputs."""
    aggregate, raw, receipt, inputs = _load_pair(path)
    if receipt is None or aggregate.get("schema_version") != "selection-external-v1":
        raise ValueError("selection external receipt or schema is invalid")
    if "completion_receipt" not in inputs:
        raise ValueError("selection external requires a completed experiment")
    if raw.get("schema_version") != "selection-external-v1":
        raise ValueError("selection external raw schema is invalid")
    methods = ("aligned_indexed", "aligned_closed", "aligned_melody")
    if aggregate.get("methods") != list(methods) or receipt.get("config", {}).get("methods") != list(methods):
        raise ValueError("selection external method declaration mismatch")
    cohort = receipt.get("case_cohort")
    if not isinstance(cohort, list) or len(cohort) != 16:
        raise ValueError("selection external frozen cohort must contain 16 inputs")
    cohort_counts = Counter(row.get("dataset") for row in cohort)
    if cohort_counts != {"theme": 6, "jku": 10} or len({row.get("case_id") for row in cohort}) != 16:
        raise ValueError("selection external frozen cohort coverage mismatch")

    from samuged.evaluate_themes import (
        ANNOTATORS, SONG_IDS, bootstrap_song_macro, classification_metrics,
        load_cases, prediction_indices,
    )
    theme_cases, _theme_receipts = load_cases(Path(input_root), Path(input_audit))
    expected_theme_cases = [case.receipt_metadata() for case in theme_cases]
    _same(raw.get("theme_cases"), expected_theme_cases, "selection.theme_cases")
    theme_by_id = {case.song_id: case for case in theme_cases}
    theme_runs = raw.get("theme_runs")
    if not isinstance(theme_runs, list):
        raise ValueError("selection external Theme runs are missing")
    expected_theme_keys = {(song, method) for song in SONG_IDS for method in methods}
    actual_theme_keys = [(row.get("case_id"), row.get("method")) for row in theme_runs]
    if len(actual_theme_keys) != 18 or len(set(actual_theme_keys)) != 18 or set(actual_theme_keys) != expected_theme_keys:
        raise ValueError("selection external Theme method coverage mismatch")
    expected_metric_rows = []
    theme_runs_by_key = {}
    for row in theme_runs:
        song_id, method = row["case_id"], row["method"]
        case = theme_by_id[song_id]
        phrases = row.get("selected_phrases")
        if not isinstance(phrases, list) or row.get("phrase_output_sha256") != _sha256_json(phrases):
            raise ValueError("selection external Theme phrase binding mismatch")
        predictions = {}
        for view, top_n in (("top1", 1), ("top3", 3)):
            predicted = prediction_indices(
                case.song, phrases, top_n=top_n,
                onset_merge_beats=receipt["config"]["aligned_config"]["onset_merge_beats"],
                require_source_verified=True,
            )
            predictions[view] = sorted(predicted)
            for annotator in ANNOTATORS:
                expected_metric_rows.append({
                    "song_id": song_id,
                    "method": method,
                    "view": view,
                    "annotator": annotator,
                    "truth_positive_notes": len(case.labels[str(annotator)]),
                    "predicted_positive_notes": len(predicted),
                    "metrics": classification_metrics(case.labels[str(annotator)], predicted),
                })
        _same(row.get("predicted_source_note_indices"), predictions,
              f"selection.theme.{song_id}.{method}.predictions")
        theme_runs_by_key[(song_id, method)] = row
    _same(raw.get("theme_note_classification"), expected_metric_rows,
          "selection.theme_note_classification")
    theme_groups = _selection_theme_groups(expected_metric_rows)
    _same(aggregate.get("theme", {}).get("method_views"), theme_groups,
          "selection.theme.method_views")
    for song_id in SONG_IDS:
        closed = theme_runs_by_key[(song_id, "aligned_closed")]["selected_phrases"]
        melody = theme_runs_by_key[(song_id, "aligned_melody")]["selected_phrases"]
        if closed != melody:
            raise ValueError("selection single-Part closed and melody outputs differ")
    if aggregate.get("theme", {}).get("single_part_closed_equals_melody") is not True:
        raise ValueError("selection single-Part restriction is not recorded")
    theme_changes = {
        method: sum(
            theme_runs_by_key[(song, method)]["phrase_output_sha256"]
            != theme_runs_by_key[(song, "aligned_indexed")]["phrase_output_sha256"]
            for song in SONG_IDS
        )
        for method in ("aligned_closed", "aligned_melody")
    }
    _same(aggregate["theme"].get("selection_changes_from_indexed"), theme_changes,
          "selection.theme.selection_changes_from_indexed")
    paired = {}
    for method in ("aligned_closed", "aligned_melody"):
        for view in ("top1", "top3"):
            baseline = theme_groups[f"aligned_indexed/{view}"]["per_song_mean_over_annotators"]
            selected = theme_groups[f"{method}/{view}"]["per_song_mean_over_annotators"]
            differences = {
                song: {
                    metric: selected[song][metric] - baseline[song][metric]
                    for metric in ("precision", "recall", "f1")
                }
                for song in SONG_IDS
            }
            paired[f"{method}_minus_aligned_indexed/{view}"] = {
                "per_song_mean_over_annotators": differences,
                "cluster_bootstrap_by_song": bootstrap_song_macro(
                    differences, samples=10_000, seed=20261031
                ),
            }
    _same(aggregate["theme"].get("paired_selector_differences"), paired,
          "selection.theme.paired_selector_differences")

    repository = Path(__file__).resolve().parent.parent
    jku_root = repository / "research_local" / "external" / "jkupdd"
    if not jku_root.is_dir():
        raise ValueError("selection external JKU source is unavailable")
    design_jku = receipt.get("design", {}).get("datasets", {}).get("jku", {})
    source_files = _jku_source_files(jku_root)
    if design_jku.get("source_files_sha256") != _sha256_json(source_files):
        raise ValueError("selection external JKU source bytes differ from the receipt")
    from samuged.evaluate_jku import (
        EXPECTED_PIECES, load_piece, metrics as jku_metrics,
        prediction_points, verify_published_examples,
    )
    expected_cohort = [
        {"case_id": f"theme:{case['song_id']}", "dataset": "theme", **case}
        for case in expected_theme_cases
    ]
    for piece in EXPECTED_PIECES:
        for variant in ("monophonic", "polyphonic"):
            prefix = f"groundTruth/{piece}/{variant}/"
            subset = {name: value for name, value in source_files.items() if name.startswith(prefix)}
            expected_cohort.append({
                "case_id": f"jku:{piece}/{variant}", "dataset": "jku",
                "piece": piece, "variant": variant,
                "source_subset_sha256": digest(subset), "source_file_count": len(subset),
            })
    _same(cohort, expected_cohort, "selection.frozen_cohort")
    golden = verify_published_examples(jku_root)
    for field in (
        "passed", "examples", "reference_patterns", "verified_metric_names",
        "metric_provenance", "mir_eval_version",
    ):
        _same(raw.get("jku_published_metric_examples", {}).get(field), golden.get(field),
              f"selection JKU published golden.{field}")
    jku_runs = raw.get("jku_runs")
    expected_jku_keys = {
        (f"{piece}/{variant}", method)
        for piece in EXPECTED_PIECES
        for variant in ("monophonic", "polyphonic")
        for method in methods
    }
    if not isinstance(jku_runs, list):
        raise ValueError("selection external JKU runs are missing")
    actual_jku_keys = [(row.get("case_id"), row.get("method")) for row in jku_runs]
    if len(actual_jku_keys) != 30 or len(set(actual_jku_keys)) != 30 or set(actual_jku_keys) != expected_jku_keys:
        raise ValueError("selection external JKU method coverage mismatch")
    for piece in EXPECTED_PIECES:
        for variant in ("monophonic", "polyphonic"):
            song, reference, provenance = load_piece(jku_root / "groundTruth" / piece / variant)
            point_lookup = provenance.pop("_point_lookup")
            for method in methods:
                row = next(
                    item for item in jku_runs
                    if item["case_id"] == f"{piece}/{variant}" and item["method"] == method
                )
                phrases = row.get("selected_phrases")
                if not isinstance(phrases, list) or row.get("phrase_output_sha256") != _sha256_json(phrases):
                    raise ValueError("selection external JKU phrase binding mismatch")
                prediction = prediction_points(
                    song, phrases, provenance["offset_beats"], point_lookup
                )
                prediction_json = json.loads(json.dumps(prediction))
                _same(row.get("prediction_patterns"), prediction_json,
                      f"selection.jku.{piece}.{variant}.{method}.prediction")
                if row.get("prediction_output_sha256") != _sha256_json(prediction_json):
                    raise ValueError("selection external JKU prediction hash mismatch")
                _same(row.get("metrics"), jku_metrics(reference, prediction),
                      f"selection.jku.{piece}.{variant}.{method}.metrics")
                if row.get("ground_truth_points_verified_in_score") is not True:
                    raise ValueError("selection external JKU annotations were not source verified")
    jku_groups = _selection_jku_groups(jku_runs)
    _same(aggregate.get("jku", {}).get("groups"), jku_groups,
          "selection.jku.groups")
    jku_by_key = {(row["case_id"], row["method"]): row for row in jku_runs}
    jku_case_ids = [
        f"{piece}/{variant}"
        for piece in EXPECTED_PIECES for variant in ("monophonic", "polyphonic")
    ]
    jku_changes = {
        method: sum(
            jku_by_key[(case_id, method)]["phrase_output_sha256"]
            != jku_by_key[(case_id, "aligned_indexed")]["phrase_output_sha256"]
            for case_id in jku_case_ids
        )
        for method in ("aligned_closed", "aligned_melody")
    }
    _same(aggregate["jku"].get("selection_changes_from_indexed"), jku_changes,
          "selection.jku.selection_changes_from_indexed")

    if sum(bool(row.get("telemetry", {}).get("curation_truncated")) for row in theme_runs + jku_runs) != 48:
        raise ValueError("selection external did not record all 48 truncated shortlists")
    if any(row.get("telemetry", {}).get("search_limited") for row in theme_runs + jku_runs):
        raise ValueError("selection external unexpectedly contains search-limited runs")
    prior = raw.get("prior_indexed_regression")
    _same(aggregate.get("prior_indexed_regression"), prior,
          "selection.prior_indexed_regression")
    frozen_prior = receipt.get("design", {}).get("prior_indexed_artifacts")
    if not isinstance(prior, dict) or not isinstance(frozen_prior, dict):
        raise ValueError("selection external prior regression binding is missing")
    for name in ("theme", "jku"):
        result = prior.get(name, {})
        if result.get("passed") is not True or result.get("comparable") is not True or result.get("mismatches") != []:
            raise ValueError(f"selection external {name} prior regression did not pass")
        if result.get("prior_artifact_hashes") != frozen_prior.get(name):
            raise ValueError(f"selection external {name} prior hashes differ from receipt")
        prior_root = Path(result.get("prior_path", "")).resolve(strict=True)
        if not prior_root.is_relative_to(repository):
            raise ValueError("selection external prior path escapes the repository")
        if name == "theme":
            from samuged.experiment import verify_completed_experiment
            verify_completed_experiment(prior_root)
        else:
            verify_start_receipt(prior_root)
            prior_aggregate = read(prior_root / "aggregate.json")
            if prior_aggregate.get("raw_results_sha256") != file_digest(prior_root / "raw_results.json"):
                raise ValueError("selection external legacy JKU result binding mismatch")
        for filename, expected in frozen_prior[name].items():
            artifact = prior_root / filename
            if not artifact.is_file() or file_digest(artifact) != expected:
                raise ValueError(f"selection external prior artifact changed: {name}/{filename}")
            inputs[f"prior_{name}_{filename}"] = artifact
    inputs["theme_input_audit"] = Path(input_audit)
    inputs["theme_download_receipts"] = Path(input_root) / "download_receipts.json"
    return {
        "theme": {"method_views": theme_groups, "paired": paired, "changes": theme_changes},
        "jku": {"groups": jku_groups, "changes": jku_changes},
        "all_runs_truncated": True,
        "run_count": 48,
    }, inputs


def validate_melody(path: Path) -> tuple[dict, dict | None, dict[str, Path]]:
    aggregate, raw, receipt, inputs = _load_pair(path)
    cases = raw.get("cases")
    if not isinstance(cases, list) or aggregate.get("case_count") != len(cases):
        raise ValueError("melodic evaluation case count mismatch")
    for mode in ("exact", "transposed", "approximate"):
        if mode not in aggregate.get("methods", {}):
            raise ValueError(f"melodic evaluation is missing {mode}")
        rows = [case["methods"][mode] for case in cases if case.get("split") == "test"]
        _same(
            aggregate["methods"][mode]["by_split"]["test"],
            aggregate_melody(rows), f"melody.{mode}.test",
        )
    return aggregate, receipt, inputs


def validate_drums(path: Path) -> tuple[dict, dict[str, Path]]:
    aggregate, raw, _receipt, inputs = _load_pair(path)
    cases = raw.get("cases")
    if not isinstance(cases, list) or aggregate.get("case_count") != len(cases):
        raise ValueError("percussion evaluation case count mismatch")
    for mode in ("exact", "tolerant"):
        rows = [case["methods"][mode] for case in cases if case.get("split") == "test"]
        _same(
            aggregate["methods"][mode]["by_split"]["test"],
            aggregate_drums(rows), f"drums.{mode}.test",
        )
    return aggregate, inputs


def validate_stress(path: Path) -> tuple[dict, dict[str, Path]]:
    aggregate, raw, receipt, inputs = _load_pair(path, allow_legacy_design=True)
    directory = Path(path).parent
    cases = raw.get("cases")
    if not isinstance(cases, list) or aggregate.get("case_count") != len(cases):
        raise ValueError("stress evaluation case count mismatch")
    design_path = directory / "design.json"
    if not design_path.is_file():
        raise ValueError("stress evaluation requires its frozen design artifact")
    frozen_design = read(design_path)
    design = frozen_design.get("design")
    frozen_cases = frozen_design.get("cases")
    if not isinstance(design, dict) or not isinstance(frozen_cases, list):
        raise ValueError("stress design is missing its design or case cohort")
    expected_version = design.get("version")
    if not expected_version or aggregate.get("stress_version") != expected_version:
        raise ValueError("stress version does not match frozen design")
    if raw.get("stress_version") != expected_version:
        raise ValueError("stress raw version does not match frozen design")
    expected_design_hash = _sha256_json(design)
    if frozen_design.get("design_sha256") != expected_design_hash:
        raise ValueError("stress frozen design hash mismatch")
    if aggregate.get("design_sha256") != expected_design_hash:
        raise ValueError("stress design hash mismatch")
    if raw.get("design_sha256") != expected_design_hash:
        raise ValueError("stress raw design hash mismatch")
    expected_cohort_hash = _sha256_json(frozen_cases)
    if frozen_design.get("cohort_sha256") != expected_cohort_hash:
        raise ValueError("stress frozen cohort payload mismatch")
    for result in (frozen_design, aggregate, raw):
        if result.get("cohort_sha256") != expected_cohort_hash:
            raise ValueError("stress cohort hash mismatch")
        if "case_cohort_sha256" in result and result.get("case_cohort_sha256") != expected_cohort_hash:
            raise ValueError("stress case cohort hash mismatch")
    if len(cases) != len(frozen_cases):
        raise ValueError("stress raw cohort row count mismatch")
    for index, (frozen_case, result_case) in enumerate(zip(frozen_cases, cases)):
        actual_metadata = {field: result_case.get(field) for field in frozen_case}
        _same(actual_metadata, frozen_case, f"stress.cases[{index}].metadata")
    for mode in ("exact", "tolerant"):
        rows = [case["methods"][mode] for case in cases if case.get("split") == "test"]
        _same(
            aggregate["methods"][mode]["by_split"]["test"],
            aggregate_stress(rows), f"stress.{mode}.test",
        )
    inputs["design"] = design_path
    validated = dict(aggregate)
    if receipt is None:
        validated["provenance_status"] = "legacy_no_executable_snapshot"
        validated["provenance_note"] = (
            "drum-stress-v01 predates executable source and dependency snapshots; "
            "the frozen design and cohort hashes were verified"
        )
    return validated, inputs


def _wilson_interval(successes: int, total: int) -> list[float] | None:
    if total < 1:
        return None
    z = 1.959963984540054
    rate = successes / total
    denominator = 1 + z * z / total
    centre = (rate + z * z / (2 * total)) / denominator
    margin = z * math.sqrt(
        (rate * (1 - rate) + z * z / (4 * total)) / total
    ) / denominator
    return [max(0.0, centre - margin), min(1.0, centre + margin)]


def _paired_role_bootstrap(differences: list[int], seed: int) -> dict:
    samples = 10_000
    if not differences:
        raise ValueError("part ranking bootstrap has no rows")
    generator = random.Random(seed)
    size = len(differences)
    estimates = sorted(
        sum(differences[generator.randrange(size)] for _ in range(size)) / size
        for _ in range(samples)
    )
    return {
        "difference": round(mean(differences), 8),
        "ci95": [
            round(estimates[math.floor(0.025 * (samples - 1))], 8),
            round(estimates[math.ceil(0.975 * (samples - 1))], 8),
        ],
        "samples": samples,
        "seed": seed,
    }


def _artifact_directory(path: Path, filename: str) -> Path:
    resolved = Path(path).resolve(strict=True)
    directory = resolved if resolved.is_dir() else resolved.parent
    if not (directory / filename).is_file():
        raise ValueError(f"required artifact is missing: {directory / filename}")
    return directory


def _validate_part_ranking_audit(
    study: Path, audit_path: Path, recomputed: dict, receipt: dict,
) -> dict[str, Path]:
    audit = _artifact_directory(audit_path, "audit_completion_receipt.json")
    completion_path = audit / "audit_completion_receipt.json"
    start_path = audit / "audit_start_receipt.json"
    results_path = audit / "audit_results.json"
    code_path = audit / "audit_logic.py"
    completion = read(completion_path)
    start = read(start_path)
    results = read(results_path)
    if completion.get("schema_version") != "part-ranking-independent-audit-completion-v1":
        raise ValueError("unsupported part ranking audit receipt")
    if completion.get("status") != "completed":
        raise ValueError("part ranking audit is incomplete")
    if completion.get("start_receipt_sha256") != file_digest(start_path):
        raise ValueError("part ranking audit start receipt hash mismatch")
    if completion.get("results_sha256") != file_digest(results_path):
        raise ValueError("part ranking audit result hash mismatch")
    if not code_path.is_file() or completion.get("audit_code_sha256") != file_digest(code_path):
        raise ValueError("part ranking audit code hash mismatch")
    if start.get("audit_code_sha256") != completion["audit_code_sha256"]:
        raise ValueError("part ranking audit code binding mismatch")
    expected_study = {
        name: file_digest(study / name)
        for name in (
            "experiment_receipt.json", "source_snapshot.json", "frozen_rule.json",
            "heldout_predictions.json", "raw_results.json", "aggregate.json",
            "completion_receipt.json",
        )
    }
    if start.get("study_artifacts") != expected_study:
        raise ValueError("part ranking audit is not bound to the current study")
    if completion.get("study_artifacts") != expected_study:
        raise ValueError("part ranking audit completion binding mismatch")
    if start.get("cohort_sha256") != receipt.get("case_cohort_sha256"):
        raise ValueError("part ranking audit cohort binding mismatch")
    if start.get("study_source_snapshot_sha256") != receipt.get("source_snapshot", {}).get("snapshot_sha256"):
        raise ValueError("part ranking audit source snapshot binding mismatch")
    if not results.get("passed") or not results.get("study_receipt_verified"):
        raise ValueError("part ranking independent audit did not pass")
    if results.get("cohort") != {"total": 180, "development": 60, "heldout": 120}:
        raise ValueError("part ranking audit coverage mismatch")
    if results.get("role_free_heldout_predictions_exact") != 120:
        raise ValueError("part ranking audit did not verify every heldout prediction")
    if (
        results.get("coordinate_mismatches") != []
        or results.get("label_mismatches") != []
        or results.get("structural_feature_rows_verified") != 180
        or results.get("development_replayed") != 60
    ):
        raise ValueError("part ranking independent audit has incomplete verification")
    for split in ("development", "heldout"):
        expected = recomputed[split]
        observed = results.get("metrics", {}).get(split, {})
        for field in ("songs", "baseline_top1", "prior_top1", "baseline_top3", "prior_top3"):
            if observed.get(field) != expected[field]:
                raise ValueError(f"part ranking audit metric mismatch: {split}.{field}")
        for view in ("top1", "top3"):
            _same(
                results.get("paired_bootstrap", {}).get(split, {}).get(view),
                expected[f"paired_{view}_difference"],
                f"part ranking audit bootstrap {split}.{view}",
            )
    return {
        "audit_start_receipt": start_path,
        "audit_results": results_path,
        "audit_completion_receipt": completion_path,
        "audit_code": code_path,
    }


def validate_part_ranking(
    path: Path, audit_path: Path,
) -> tuple[dict, dict[str, Path]]:
    study = _artifact_directory(path, "aggregate.json")
    aggregate, raw, receipt, inputs = _load_pair(study / "aggregate.json")
    if receipt is None:
        raise ValueError("part ranking study lacks a frozen receipt")
    rows = raw.get("rows")
    cohort = receipt.get("case_cohort")
    if not isinstance(rows, list) or not isinstance(cohort, list):
        raise ValueError("part ranking cohort is missing")
    if len(rows) != 180 or len({row.get("case_id") for row in rows}) != 180:
        raise ValueError("part ranking raw row coverage mismatch")
    if Counter(row.get("split") for row in rows) != {"development": 60, "heldout": 120}:
        raise ValueError("part ranking split coverage mismatch")
    if Counter(case.get("split") for case in cohort) != {"development": 60, "heldout": 120}:
        raise ValueError("part ranking receipt cohort coverage mismatch")
    cohort_fields = ("case_id", "split", "rank_sha256", "source_path", "source_sha256", "source_bytes")
    for index, (row, case) in enumerate(zip(rows, cohort)):
        if any(row.get(field) != case.get(field) for field in cohort_fields):
            raise ValueError(f"part ranking row differs from frozen cohort at index {index}")

    frozen_path = study / "frozen_rule.json"
    predictions_path = study / "heldout_predictions.json"
    frozen = read(frozen_path)
    predictions = read(predictions_path)
    frozen_hash = file_digest(frozen_path)
    predictions_hash = file_digest(predictions_path)
    for payload in (aggregate, raw):
        if payload.get("frozen_rule_sha256") != frozen_hash:
            raise ValueError("part ranking frozen rule link mismatch")
        if payload.get("heldout_predictions_sha256") != predictions_hash:
            raise ValueError("part ranking heldout prediction link mismatch")
    if predictions.get("frozen_rule_sha256") != frozen_hash:
        raise ValueError("heldout predictions are not bound to the frozen rule")
    selected = frozen.get("selected_preset")
    if not isinstance(selected, str) or any(
        payload.get("selected_preset") != selected
        for payload in (aggregate, raw, predictions)
    ):
        raise ValueError("part ranking selected preset mismatch")
    presets = receipt.get("config", {}).get("presets")
    fit = frozen.get("development_fit")
    if not isinstance(presets, list) or len(presets) != 8 or not isinstance(fit, list) or len(fit) != 8:
        raise ValueError("part ranking preset declaration is incomplete")
    preset_names = [preset.get("name") for preset in presets]
    if len(set(preset_names)) != 8 or [row.get("preset") for row in fit] != preset_names:
        raise ValueError("part ranking fit does not cover every declared preset")
    chosen = max(
        fit,
        key=lambda row: (
            row["top1_melody"], row["top3_melody"], -row["changed_songs"],
            -row["strength"], -row["preset_index"],
        ),
    )
    if chosen.get("preset") != selected or frozen.get("development_song_count") != 60:
        raise ValueError("part ranking frozen development decision mismatch")
    if frozen.get("selected_config") != aggregate.get("selected_config"):
        raise ValueError("part ranking selected configuration mismatch")

    heldout_rows = [row for row in rows if row["split"] == "heldout"]
    heldout_predictions = predictions.get("predictions")
    if (
        predictions.get("role_labels_included") is not False
        or predictions.get("prediction_count") != 120
        or not isinstance(heldout_predictions, list)
        or len(heldout_predictions) != 120
    ):
        raise ValueError("part ranking heldout prediction coverage mismatch")
    forbidden = {
        "role_map", "baseline_labels", "prior_labels", "melody_candidate_available",
        "selection_changed", "top1_part_changed", "selected_prior", "roles",
        "top1_melody", "top3_melody",
    }
    def scan_role_free(value: Any) -> None:
        if isinstance(value, dict):
            if forbidden & set(value):
                raise ValueError("part ranking heldout predictions contain role labels")
            for nested in value.values():
                scan_role_free(nested)
        elif isinstance(value, list):
            for nested in value:
                scan_role_free(nested)
    scan_role_free(heldout_predictions)
    by_id = {row["case_id"]: row for row in rows}
    if [row.get("case_id") for row in heldout_predictions] != [row["case_id"] for row in heldout_rows]:
        raise ValueError("part ranking heldout prediction order mismatch")
    for prediction in heldout_predictions:
        row = by_id[prediction["case_id"]]
        restored = {
            key: value for key, value in row.items()
            if key not in {
                "role_map", "baseline_labels", "prior_labels", "melody_candidate_available",
                "selection_changed", "top1_part_changed", "selected_prior",
            }
        }
        restored["priors"] = {selected: row["selected_prior"]}
        if restored != prediction:
            raise ValueError("part ranking heldout prediction differs from scored raw row")

    recomputed = {}
    for split in ("development", "heldout"):
        selected_rows = [row for row in rows if row["split"] == split]
        differences = {"top1": [], "top3": []}
        metrics = {
            "songs": len(selected_rows), "baseline_top1": 0, "prior_top1": 0,
            "baseline_top3": 0, "prior_top3": 0,
        }
        for row in selected_rows:
            role_map = row.get("role_map")
            if not isinstance(role_map, dict):
                raise ValueError("part ranking role map is missing")
            computed_labels = {}
            for method, key in (("baseline", "baseline"), ("prior", "selected_prior")):
                selection = row.get(key, {})
                phrases = selection.get("phrases")
                parts = selection.get("part_indices")
                families = selection.get("family_ids")
                if not isinstance(phrases, list) or not isinstance(parts, list) or not isinstance(families, list):
                    raise ValueError("part ranking selected candidate IDs are incomplete")
                if families != [phrase.get("family_id") for phrase in phrases]:
                    raise ValueError("part ranking family ID list mismatch")
                if parts != [phrase.get("part_index") for phrase in phrases]:
                    raise ValueError("part ranking part index list mismatch")
                roles = [role_map.get(str(index)) for index in parts]
                if any(role is None for role in roles):
                    raise ValueError("part ranking selected part is absent from role map")
                labels = {
                    "roles": roles,
                    "top1_melody": bool(roles and roles[0] == "MELODY"),
                    "top3_melody": "MELODY" in roles[:3],
                }
                if labels != row.get(f"{method}_labels"):
                    raise ValueError("part ranking saved role label differs from selected IDs")
                computed_labels[method] = labels
                metrics[f"{method}_top1"] += int(labels["top1_melody"])
                metrics[f"{method}_top3"] += int(labels["top3_melody"])
            for view in ("top1", "top3"):
                differences[view].append(
                    int(computed_labels["prior"][f"{view}_melody"])
                    - int(computed_labels["baseline"][f"{view}_melody"])
                )
        metrics["paired_top1_difference"] = _paired_role_bootstrap(differences["top1"], 20261003)
        metrics["paired_top3_difference"] = _paired_role_bootstrap(differences["top3"], 20261004)
        saved = aggregate.get(split, {})
        for method, saved_key in (("baseline", "baseline"), ("prior", "part_prior")):
            for view in ("top1", "top3"):
                if saved.get(saved_key, {}).get(f"{view}_melody_count") != metrics[f"{method}_{view}"]:
                    raise ValueError(f"part ranking aggregate count mismatch: {split}.{method}.{view}")
        for view in ("top1", "top3"):
            _same(
                saved.get(f"paired_{view}_difference"), metrics[f"paired_{view}_difference"],
                f"part ranking aggregate bootstrap {split}.{view}",
            )
        recomputed[split] = metrics

    inputs.update({"frozen_rule": frozen_path, "heldout_predictions": predictions_path})
    inputs.update(_validate_part_ranking_audit(study, audit_path, recomputed, receipt))
    return {
        "selected_preset": selected,
        "development": recomputed["development"],
        "heldout": recomputed["heldout"],
        "curation_truncated": {
            split: sum(bool(row.get("curation_truncated")) for row in rows if row["split"] == split)
            for split in ("development", "heldout")
        },
        "search_limited": {
            split: sum(bool(row.get("search_limited")) for row in rows if row["split"] == split)
            for split in ("development", "heldout")
        },
    }, inputs


def _certified_drum_summary(rows: list[dict]) -> dict:
    negatives = [row for row in rows if row.get("kind") == "certified_negative"]
    positives = [row for row in rows if row.get("kind") == "planted_positive"]
    outputs = sum(bool(row.get("negative_case_with_output")) for row in negatives)
    target_pairs = sum(row.get("target_pair_count", 0) for row in positives)
    covered = sum(
        row.get("target_pairs_covered_by_direct_detector_edges", 0) for row in positives
    )
    return {
        "cases": len(rows),
        "negative_cases": len(negatives),
        "negative_cases_with_output": outputs,
        "negative_output_rate": outputs / len(negatives) if negatives else None,
        "negative_output_wilson_95": _wilson_interval(outputs, len(negatives)),
        "positive_cases": len(positives),
        "positive_target_pairs": target_pairs,
        "positive_target_pairs_covered_by_direct_detector_edges": covered,
        "positive_oracle_edge_coverage": covered / target_pairs if target_pairs else None,
    }


def _validate_certified_drum_audit(
    study: Path, audit_path: Path, recomputed: dict,
) -> tuple[dict, dict[str, Path]]:
    audit_dir = _artifact_directory(audit_path, "audit_receipt.json")
    receipt_path = audit_dir / "audit_receipt.json"
    manifest_path = audit_dir / "input_manifest.json"
    report_path = audit_dir / "audit.json"
    receipt = read(receipt_path)
    manifest = read(manifest_path)
    report = read(report_path)
    if receipt.get("schema_version") != "samuged-certified-drum-audit-v1" or receipt.get("status") != "completed":
        raise ValueError("certified drum audit receipt is invalid")
    artifacts = receipt.get("artifacts")
    if not isinstance(artifacts, dict) or set(artifacts) != {"audit.json", "input_manifest.json"}:
        raise ValueError("certified drum audit artifact set mismatch")
    for name, expected in artifacts.items():
        artifact = audit_dir / name
        if expected.get("sha256") != file_digest(artifact) or expected.get("bytes") != artifact.stat().st_size:
            raise ValueError(f"certified drum audit artifact changed: {name}")
    manifest_hash = _sha256_json(manifest)
    if receipt.get("input_manifest_sha256") != manifest_hash or report.get("input_manifest_sha256") != manifest_hash:
        raise ValueError("certified drum audit manifest binding mismatch")
    if receipt.get("audit_sha256") != file_digest(report_path):
        raise ValueError("certified drum audit report binding mismatch")
    entries = manifest.get("artifacts")
    if not isinstance(entries, list) or not entries:
        raise ValueError("certified drum audit source-study manifest is missing")
    root = study.resolve()
    seen = set()
    for entry in entries:
        relative = entry.get("path")
        if not isinstance(relative, str) or relative in seen:
            raise ValueError("certified drum audit source-study manifest has invalid paths")
        seen.add(relative)
        artifact = (root / relative).resolve(strict=True)
        if not artifact.is_relative_to(root) or not artifact.is_file():
            raise ValueError("certified drum audit source-study path escapes study")
        if entry.get("sha256") != file_digest(artifact) or entry.get("bytes") != artifact.stat().st_size:
            raise ValueError(f"certified drum audit is not bound to current study: {relative}")
    if manifest.get("study_completion_receipt_sha256") != file_digest(study / "completion_receipt.json"):
        raise ValueError("certified drum audit completion binding mismatch")
    source_snapshot_hash = read(study / "source_snapshot.json").get("snapshot_sha256")
    if manifest.get("study_source_snapshot_sha256") != source_snapshot_hash:
        raise ValueError("certified drum audit source snapshot binding mismatch")
    if report.get("case_count") != 360 or report.get("split_kind_counts") != {
        "development/certified_negative": 120,
        "development/planted_positive": 60,
        "test/certified_negative": 120,
        "test/planted_positive": 60,
    }:
        raise ValueError("certified drum independent audit coverage mismatch")
    audited = report.get("aggregate_recomputed_from_raw", {})
    for mode in ("exact", "tolerant"):
        for split in ("development", "test"):
            actual = recomputed[mode][split]
            observed = audited.get(mode, {}).get("by_split", {}).get(split, {})
            for field, expected in actual.items():
                if observed.get(field) != expected:
                    raise ValueError(f"certified drum audit metric mismatch: {mode}.{split}.{field}")
    family = report.get("family_recovery_posthoc")
    for mode in ("exact", "tolerant"):
        for split in ("development", "test"):
            item = family.get(mode, {}).get(split, {}) if isinstance(family, dict) else {}
            if item.get("positive_cases") != 60:
                raise ValueError("certified drum posthoc family audit coverage mismatch")
            covered = item.get("families_covering_all_labelled_target_windows")
            if not isinstance(covered, int) or not 0 <= covered <= 60:
                raise ValueError("certified drum posthoc family result is invalid")
    return family, {
        "audit_receipt": receipt_path,
        "audit_input_manifest": manifest_path,
        "audit_report": report_path,
    }


def validate_certified_drums(
    path: Path, audit_path: Path,
) -> tuple[dict, dict[str, Path]]:
    study = _artifact_directory(path, "aggregate.json")
    aggregate, raw, receipt, inputs = _load_pair(study / "aggregate.json")
    if receipt is None:
        raise ValueError("certified drum study lacks a frozen receipt")
    cases = raw.get("cases")
    cohort = receipt.get("case_cohort")
    if not isinstance(cases, list) or not isinstance(cohort, list) or cases != cohort:
        raise ValueError("certified drum raw cohort differs from frozen receipt")
    counts = Counter((case.get("split"), case.get("kind")) for case in cases)
    expected = {
        (split, kind): 120 if kind == "certified_negative" else 60
        for split in ("development", "test")
        for kind in ("certified_negative", "planted_positive")
    }
    if len(cases) != 360 or len({case.get("case_id") for case in cases}) != 360 or counts != expected:
        raise ValueError("certified drum cohort coverage mismatch")
    case_by_id = {case["case_id"]: case for case in cases}
    recomputed = {mode: {} for mode in ("exact", "tolerant")}
    for mode in ("exact", "tolerant"):
        rows = raw.get("methods", {}).get(mode)
        if not isinstance(rows, list) or len(rows) != 360 or len({row.get("case_id") for row in rows}) != 360:
            raise ValueError(f"certified drum method coverage mismatch: {mode}")
        if {row["case_id"] for row in rows} != set(case_by_id):
            raise ValueError(f"certified drum method IDs differ from cohort: {mode}")
        for row in rows:
            case = case_by_id[row["case_id"]]
            if row.get("split") != case["split"] or row.get("kind") != case["kind"]:
                raise ValueError(f"certified drum method grouping mismatch: {mode}")
        for split in ("development", "test"):
            summary = _certified_drum_summary([row for row in rows if row["split"] == split])
            saved = aggregate.get("methods", {}).get(mode, {}).get("by_split", {}).get(split, {})
            for field, value in summary.items():
                _same(saved.get(field), value, f"certified drums {mode}.{split}.{field}")
            recomputed[mode][split] = summary
    family, audit_inputs = _validate_certified_drum_audit(study, audit_path, recomputed)
    inputs.update({
        "design": study / "design.json",
        "labels": study / "labels.json",
        **audit_inputs,
    })
    return {"methods": recomputed, "family_recovery_posthoc": family}, inputs


def _jku_groups(rows: list[dict]) -> dict:
    groups = {}
    for variant, mode in sorted({(row["variant"], row["mode"]) for row in rows}):
        selected = [row for row in rows if row["variant"] == variant and row["mode"] == mode]
        groups[f"{variant}/{mode}"] = {
            "works": len(selected),
            "macro_metrics": {
                name: sum(row["metrics"][name] for row in selected) / len(selected)
                for name in sorted(selected[0]["metrics"])
            },
            "search_limited_works": sum(bool(row["search_limited"]) for row in selected),
            "curation_truncated_works": sum(bool(row["curation_truncated"]) for row in selected),
            "total_runtime_seconds": sum(row["runtime_seconds"] for row in selected),
        }
    return groups


def _jku_source_root(directory: Path, design: dict) -> Path:
    source_root_name = design.get("source_root_name")
    if not isinstance(source_root_name, str) or not source_root_name:
        raise ValueError("external design has no source root name")
    configured = os.environ.get("SAMUGED_JKU_SOURCE_ROOT")
    candidates = []
    if configured:
        candidates.append(Path(configured).expanduser())
    repository = Path(__file__).resolve().parent.parent
    candidates.append(repository / "research_local" / "external" / source_root_name)
    candidates.append(directory.parents[1] / "external" / source_root_name)
    for candidate in candidates:
        try:
            resolved = candidate.resolve(strict=True)
        except OSError:
            continue
        if resolved.is_dir() and resolved.name == source_root_name:
            return resolved
    raise ValueError(f"external source root is unavailable: {source_root_name}")


def _jku_source_files(source_root: Path) -> dict[str, str]:
    return {
        path.relative_to(source_root).as_posix(): file_digest(path)
        for path in sorted(source_root.rglob("*"))
        if path.is_file() and path.suffix in {".csv", ".krn", ".txt"}
    }


def _jku_row_source_key(score_path: object, source_files: dict[str, str]) -> str:
    if not isinstance(score_path, str) or not score_path:
        raise ValueError("external score path is missing")
    value = Path(score_path).as_posix()
    if value in source_files:
        return value
    matches = [key for key in source_files if value.endswith("/" + key)]
    if len(matches) != 1:
        raise ValueError("external score path is not in the frozen source manifest")
    return matches[0]


def _validate_jku_provenance(directory: Path, aggregate: dict, design: dict) -> Path:
    code_snapshot = design.get("code_snapshot")
    if not isinstance(code_snapshot, str) or not code_snapshot:
        raise ValueError("external design has no code snapshot")
    code_path = directory / code_snapshot
    if not code_path.is_dir():
        raise ValueError("external code snapshot is missing")
    code_files = sorted(code_path.glob("*.py"))
    if not code_files:
        raise ValueError("external code snapshot is empty")
    code_hash = digest({
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in code_files
    })
    if design.get("code_sha256") != code_hash:
        raise ValueError("external code snapshot hash mismatch")
    dependencies = design.get("dependency_snapshot_sha256")
    if not isinstance(dependencies, dict) or not dependencies:
        raise ValueError("external dependency snapshot is missing")
    for name, expected in dependencies.items():
        dependency = code_path.parent / name
        if not dependency.is_file() or file_digest(dependency) != expected:
            raise ValueError(f"external dependency snapshot mismatch: {name}")
    source_root = _jku_source_root(directory, design)
    source_files = design.get("source_files")
    if not isinstance(source_files, dict) or not source_files:
        raise ValueError("external source manifest is missing")
    source_field = (
        "external_source_snapshot_sha256"
        if "external_source_snapshot_sha256" in design
        else "source_snapshot_sha256"
    )
    expected_source_hash = digest(source_files)
    if design.get(source_field) != expected_source_hash:
        raise ValueError("external source manifest hash mismatch")
    if aggregate.get(source_field) != expected_source_hash:
        raise ValueError("external aggregate source hash mismatch")
    if _jku_source_files(source_root) != source_files:
        raise ValueError("external source bytes do not match frozen manifest")
    return source_root


def _validate_jku_schema(aggregate: dict, raw: dict, design: dict, published: dict) -> None:
    expected = design.get("schema_version")
    if type(expected) is not int or expected not in (2, 3):
        raise ValueError("external design schema version is unsupported")
    for name, value in (("aggregate", aggregate), ("raw", raw), ("design", design)):
        if value.get("schema_version") != expected:
            raise ValueError(f"external {name} schema version mismatch")
    if "schema_version" in published and published.get("schema_version") != expected:
        raise ValueError("external published schema version mismatch")


def validate_external(path: Path) -> tuple[dict, dict[str, Path]]:
    aggregate, raw, _receipt, inputs = _load_pair(path, allow_legacy_design=True)
    directory = Path(path).parent
    raw_path = directory / "raw_results.json"
    if aggregate.get("raw_results_sha256") != file_digest(raw_path):
        raise ValueError("external aggregate is not bound to its raw results")
    design_path = directory / "design.json"
    published_path = directory / "published_examples.json"
    if not design_path.is_file() or not published_path.is_file():
        raise ValueError("external evaluation is missing a frozen design or published examples")
    design = read(design_path)
    published = read(published_path)
    design_link = "frozen_design_sha256" if "frozen_design_sha256" in aggregate else "design_sha256"
    design_hash = (
        design.get("frozen_design_sha256")
        if design_link == "frozen_design_sha256"
        else file_digest(design_path)
    )
    if not isinstance(design_hash, str) or not design_hash:
        raise ValueError("external design binding is missing")
    for name, value in (("aggregate", aggregate), ("raw", raw), ("published", published)):
        if value.get(design_link) != design_hash:
            raise ValueError(f"external {name} is not bound to design.json")
    _validate_jku_schema(aggregate, raw, design, published)
    source_root = _validate_jku_provenance(directory, aggregate, design)
    rows = raw.get("results")
    if not isinstance(rows, list) or not rows:
        raise ValueError("external evaluation has no result rows")
    source_files = design.get("source_files", {})
    pieces = sorted({
        parts[1]
        for name in source_files
        if (parts := name.split("/"))[:1] == ["groundTruth"] and len(parts) > 2
    })
    from samuged.evaluate_jku import EXPECTED_PIECES
    if tuple(pieces) != tuple(EXPECTED_PIECES):
        raise ValueError("external result cohort differs from the five published works")
    variants = sorted({
        parts[2]
        for name in source_files
        if (parts := name.split("/"))[:1] == ["groundTruth"] and len(parts) > 2
    })
    variants = [variant for variant in ("monophonic", "polyphonic") if variant in variants]
    modes = sorted(design.get("configs", {}))
    expected_rows = {
        (piece, variant, mode)
        for piece in pieces
        for variant in variants
        for mode in modes
    }
    actual_rows = []
    for row in rows:
        key = (row.get("piece"), row.get("variant"), row.get("mode"))
        actual_rows.append(key)
        if row.get("ground_truth_points_verified_in_score") is not True:
            raise ValueError("external evaluation contains unverified annotation points")
        source_key = _jku_row_source_key(row.get("score_path"), source_files)
        if row.get("score_sha256") != source_files.get(source_key):
            raise ValueError("external score is not bound to the frozen source manifest")
    if (
        len(actual_rows) != len(expected_rows)
        or len(set(actual_rows)) != len(actual_rows)
        or set(actual_rows) != expected_rows
    ):
        raise ValueError("external result row coverage does not match frozen cohort")
    _same(aggregate.get("groups"), _jku_groups(rows), "external.groups")
    if aggregate.get("published_examples_sha256") != file_digest(published_path):
        raise ValueError("external published examples hash mismatch")
    from samuged.evaluate_jku import verify_published_examples
    expected_published = verify_published_examples(source_root)
    for field in (
        "passed", "examples", "reference_patterns", "verified_metric_names",
        "metric_provenance", "mir_eval_version",
    ):
        _same(
            published.get(field), expected_published.get(field),
            f"external published golden.{field}",
        )
    if not published.get("passed") or not aggregate.get("published_metric_examples_verified"):
        raise ValueError("published external metric checks did not pass")
    inputs["design.json"] = design_path
    inputs["published_examples.json"] = published_path
    return aggregate, inputs


def validate_aligned(path: Path) -> tuple[dict, dict[str, Path]]:
    aggregate, raw, _receipt, inputs = _load_pair(path)
    synthetic = raw.get("synthetic_rows")
    if not isinstance(synthetic, dict):
        raise ValueError("aligned evaluation has no synthetic rows")
    for method in ("reference_approximate", "aligned"):
        rows = [row for row in synthetic.get(method, []) if row.get("split") == "test"]
        recomputed = aggregate_melody(rows)
        recomputed["search_limited_cases"] = sum(bool(row.get("search_limited")) for row in rows)
        recomputed["curation_truncated_cases"] = sum(bool(row.get("curation_truncated")) for row in rows)
        _same(
            aggregate["synthetic"]["methods"][method]["by_split"]["test"],
            recomputed, f"aligned.synthetic.{method}.test",
        )
    _same(
        aggregate["real_pilot"], aggregate_real_rows(raw.get("real_rows", [])),
        "aligned.real_pilot",
    )
    return aggregate, inputs


def _closed_method_aggregate(rows: list[dict]) -> dict:
    result = aggregate_melody(rows)
    result["changed_selection_cases"] = sum(bool(row.get("selection_changed")) for row in rows)
    result["closed_extension_replacements"] = sum(
        row.get("closed_extension_count", 0) for row in rows
    )
    result["by_kind"] = {
        kind: aggregate_melody([row for row in rows if row.get("kind") == kind])
        for kind in CASE_KINDS
    }
    return result


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    position = fraction * (len(ordered) - 1)
    low, high = math.floor(position), math.ceil(position)
    if low == high:
        return ordered[low]
    weight = position - low
    return ordered[low] * (1 - weight) + ordered[high] * weight


def _closed_paired_delta(original: list[dict], closed: list[dict], seed: int) -> dict:
    original_by_id = {row["case_id"]: row for row in original}
    closed_by_id = {row["case_id"]: row for row in closed}
    if len(original_by_id) != len(original) or len(closed_by_id) != len(closed):
        raise ValueError("closed evaluation contains duplicate synthetic case ids")
    if set(original_by_id) != set(closed_by_id):
        raise ValueError("closed evaluation paired synthetic rows differ")
    case_ids = sorted(original_by_id)

    def delta(sample: list[str]) -> dict[str, float]:
        left = aggregate_melody([original_by_id[case_id] for case_id in sample])
        right = aggregate_melody([closed_by_id[case_id] for case_id in sample])
        return {
            "candidate_f1": right["candidate"]["f1"] - left["candidate"]["f1"],
            "occurrence_f1": right["occurrence"]["f1"] - left["occurrence"]["f1"],
            "top1_recovery": right["top1_recovery"] - left["top1_recovery"],
            "recovered_positive_cases": (
                right["recovered_positive_cases"] - left["recovered_positive_cases"]
            ),
            "false_positive_case_count": (
                right["false_positive_case_count"] - left["false_positive_case_count"]
            ),
        }

    point = delta(case_ids)
    rng = random.Random(seed)
    samples = {key: [] for key in point}
    for _ in range(1000):
        selected = [case_ids[rng.randrange(len(case_ids))] for _ in case_ids]
        values = delta(selected)
        for key, value in values.items():
            samples[key].append(value)
    return {
        key: {
            "closed_minus_original": point[key],
            "case_bootstrap_ci95": [
                _percentile(values, 0.025), _percentile(values, 0.975)
            ],
        }
        for key, values in samples.items()
    }


def _closed_real_aggregate(rows: list[dict], algorithm: str) -> dict:
    selected = [row for row in rows if row.get("algorithm") == algorithm]
    if len(selected) != 128:
        raise ValueError(f"closed evaluation {algorithm} real row count is not 128")
    if len({row.get("source_path") for row in selected}) != len(selected):
        raise ValueError(f"closed evaluation {algorithm} has duplicate real sources")
    for row in selected:
        changed = row.get("original") != row.get("closed_exact_extension")
        if row.get("selection_changed") is not changed:
            raise ValueError("closed evaluation real changed flag differs from phrase coordinates")
        trace = row.get("trace")
        if not isinstance(trace, list) or row.get("closed_extension_count") != len(trace):
            raise ValueError("closed evaluation real replacement count differs from trace")
        if not changed and trace:
            raise ValueError("closed evaluation unchanged real row has a replacement trace")
    changed = [row for row in selected if row["selection_changed"]]
    elapsed = [row["detection_seconds"] for row in selected]
    return {
        "files": len(selected),
        "changed_file_count": len(changed),
        "changed_source_paths": [row["source_path"] for row in changed],
        "closed_extension_replacements": sum(row["closed_extension_count"] for row in selected),
        "search_limited_files": sum(bool(row["search_limited"]) for row in selected),
        "curation_truncated_files": sum(bool(row["curation_truncated"]) for row in selected),
        "runtime_seconds": {
            "total": sum(elapsed),
            "mean": mean(elapsed),
            "median": median(elapsed),
            "maximum": max(elapsed),
        },
        "changed_selections": [
            {
                "source_path": row["source_path"],
                "trace": row["trace"],
                "original": row["original"],
                "closed_exact_extension": row["closed_exact_extension"],
            }
            for row in changed
        ],
    }


def validate_closed(path: Path) -> tuple[dict, dict[str, Path]]:
    """Reconstruct the optional closed-pattern study from frozen raw rows."""
    aggregate, raw, receipt, inputs = _load_pair(path)
    if receipt is None:
        raise ValueError("closed evaluation requires a frozen experiment receipt")
    design = receipt.get("design", {})
    fresh = design.get("fresh_synthetic", {})
    real_design = design.get("real_pilot", {})
    if (
        design.get("version") != "closed-patterns-fresh-v1"
        or fresh.get("seed_base") != 30_000_000
        or fresh.get("seed_last") != 30_000_499
        or fresh.get("case_count") != 500
        or fresh.get("split_label") != "fresh_holdout"
        or fresh.get("thresholds_frozen_before_scoring") is not True
        or real_design.get("source_count") != 128
        or real_design.get("labels") is not False
    ):
        raise ValueError("closed evaluation frozen design differs from the reported study")
    cohort = receipt.get("case_cohort", [])
    synthetic_cohort = [row for row in cohort if row.get("cohort_type") == "fresh_synthetic"]
    real_cohort = [row for row in cohort if row.get("cohort_type") == "fixed_real_unlabelled"]
    if (
        len(synthetic_cohort) != 500
        or [row.get("rng_seed") for row in synthetic_cohort]
        != list(range(30_000_000, 30_000_500))
        or len(real_cohort) != 128
    ):
        raise ValueError("closed evaluation receipt cohort differs from the frozen seed or real source set")

    synthetic = raw.get("synthetic_rows")
    real_rows = raw.get("real_rows")
    if not isinstance(synthetic, dict) or not isinstance(real_rows, list):
        raise ValueError("closed evaluation raw rows are missing")
    if (
        aggregate.get("study_version") != design["version"]
        or raw.get("study_version") != design["version"]
    ):
        raise ValueError("closed evaluation result version differs from its frozen design")
    algorithms = ("aligned", "aligned_indexed")
    variants = ("original", "closed_exact_extension")
    expected_case_ids = {row["case_id"] for row in synthetic_cohort}
    expected_real = {
        row["source_path"]: row["source_sha256"] for row in real_cohort
    }
    for algorithm in algorithms:
        methods = synthetic.get(algorithm)
        if not isinstance(methods, dict):
            raise ValueError(f"closed evaluation is missing {algorithm}")
        for variant in variants:
            rows = methods.get(variant)
            if (
                not isinstance(rows, list)
                or len(rows) != 500
                or {row.get("case_id") for row in rows} != expected_case_ids
                or any(row.get("split") != "fresh_holdout" for row in rows)
            ):
                raise ValueError("closed evaluation synthetic coverage differs from the frozen cohort")
            _same(
                aggregate["synthetic"][algorithm][variant],
                _closed_method_aggregate(rows),
                f"closed.synthetic.{algorithm}.{variant}",
            )
        _same(
            aggregate["paired_deltas"][algorithm],
            _closed_paired_delta(
                methods["original"], methods["closed_exact_extension"],
                73_000 + algorithms.index(algorithm),
            ),
            f"closed.paired_deltas.{algorithm}",
        )
        expected_negative = {
            variant: aggregate["synthetic"][algorithm][variant]["false_positive_case_ids"]
            for variant in variants
        }
        _same(
            aggregate["negative_outputs"][algorithm], expected_negative,
            f"closed.negative_outputs.{algorithm}",
        )
        algorithm_real = [row for row in real_rows if row.get("algorithm") == algorithm]
        if (
            {row.get("source_path") for row in algorithm_real} != set(expected_real)
            or any(row.get("source_sha256") != expected_real.get(row.get("source_path"))
                   for row in algorithm_real)
        ):
            raise ValueError("closed evaluation real rows differ from the frozen source cohort")
        _same(
            aggregate["real_pilot"][algorithm],
            _closed_real_aggregate(real_rows, algorithm),
            f"closed.real_pilot.{algorithm}",
        )
    return aggregate, inputs


def validate_metamorphic(path: Path) -> tuple[dict, dict[str, Path]]:
    """Check coverage and reconstruct the reported invariance counts."""
    try:
        from scripts.evaluate_metamorphic import _aggregate, DETECTOR_NAMES, TRANSFORMS
    except ModuleNotFoundError as exc:  # Direct ``python scripts/make_paper.py``.
        if exc.name != "scripts":
            raise
        from evaluate_metamorphic import _aggregate, DETECTOR_NAMES, TRANSFORMS

    aggregate, raw, receipt, inputs = _load_pair(path)
    if receipt is None or receipt["design"].get("version") != "metamorphic-real-v1":
        raise ValueError("metamorphic evaluation requires its frozen design")
    cohort = receipt["case_cohort"]
    sources = {row["source_id"]: row for row in cohort}
    if len(sources) != len(cohort) or not sources:
        raise ValueError("metamorphic cohort contains missing or duplicate sources")
    _same(receipt["design"]["source_count"], len(sources), "metamorphic design source count")
    _same(receipt["design"]["detectors"], list(DETECTOR_NAMES), "metamorphic detectors")
    _same(set(receipt["design"]["transforms"]), set(TRANSFORMS), "metamorphic transforms")
    expected = {(source, detector, transform) for source in sources
                for detector in DETECTOR_NAMES for transform in TRANSFORMS}
    rows = raw.get("rows")
    if not isinstance(rows, list) or len(rows) != len(expected):
        raise ValueError("metamorphic row coverage differs from frozen cohort")
    actual = {(row.get("source_id"), row.get("detector"), row.get("transform")) for row in rows}
    if actual != expected:
        raise ValueError("metamorphic row coverage differs from frozen cohort")
    for row in rows:
        source = sources[row["source_id"]]
        if any(row.get(key) != source[key] for key in ("source_path", "source_sha256")):
            raise ValueError("metamorphic source identity differs from frozen cohort")
        if type(row.get("skipped")) is not bool:
            raise ValueError("metamorphic skipped flag must be boolean")
        if row["skipped"]:
            if row["transform"] != "melodic_transpose_plus5":
                raise ValueError("metamorphic skip is outside the declared pitch overflow rule")
            continue
        comparison = row["comparison"]
        for key in ("invariant", "musical_payload_equal", "family_id_order_equal", "phrase_count_equal", "telemetry_equal"):
            if type(comparison.get(key)) is not bool:
                raise ValueError("metamorphic comparison flag must be boolean")
        expected_invariant = comparison["musical_payload_equal"] and comparison["family_id_order_equal"]
        _same(comparison["invariant"], expected_invariant, "metamorphic invariant flag")
        _same(comparison["family_id_order_equal"],
              comparison["baseline_family_ids"] == comparison["variant_family_ids"],
              "metamorphic family order flag")
        for side in ("baseline", "variant"):
            _same(comparison[f"{side}_phrase_count"], len(comparison[f"{side}_family_ids"]),
                  f"metamorphic {side} phrase count")
        _same(comparison["phrase_count_equal"],
              comparison["baseline_phrase_count"] == comparison["variant_phrase_count"],
              "metamorphic phrase count flag")
        _same(comparison["musical_payload_equal"], not bool(comparison["difference_paths"]),
              "metamorphic musical difference paths")
    _same(aggregate["groups"], _aggregate(rows), "metamorphic groups")
    _same(aggregate["source_count"], len(sources), "metamorphic source count")
    _same(aggregate["evaluated_rows"], sum(not row["skipped"] for row in rows), "metamorphic evaluated rows")
    _same(aggregate["skipped_rows"], sum(row["skipped"] for row in rows), "metamorphic skipped rows")
    _same(aggregate["total_failures"], sum(not row["comparison"]["invariant"] for row in rows if not row["skipped"]),
          "metamorphic failure count")
    return aggregate, inputs


def resolve_report_date(explicit: str | None, receipt: dict | None) -> tuple[str, str]:
    if explicit:
        try:
            return datetime.strptime(explicit, "%Y-%m-%d").date().isoformat(), "explicit"
        except ValueError as exc:
            raise ValueError("--report-date must use YYYY-MM-DD") from exc
    epoch = os.environ.get("SOURCE_DATE_EPOCH")
    if epoch is not None:
        try:
            value = datetime.fromtimestamp(int(epoch), tz=timezone.utc).date().isoformat()
        except (ValueError, OverflowError) as exc:
            raise ValueError("SOURCE_DATE_EPOCH must be an integer Unix timestamp") from exc
        return value, "SOURCE_DATE_EPOCH UTC"
    started = receipt.get("started_at_utc") if receipt else None
    if started:
        try:
            parsed = datetime.fromisoformat(started.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("experiment receipt started_at_utc is invalid") from exc
        if parsed.tzinfo is None:
            raise ValueError("experiment receipt started_at_utc must include a timezone")
        return parsed.astimezone(timezone.utc).date().isoformat(), "melodic experiment receipt UTC"
    raise ValueError(f"report date is unavailable; policy is: {DATE_POLICY}")


def method_description(algorithm: str, config: dict) -> tuple[str, str]:
    if algorithm == "reference":
        lengths = ", ".join(str(value) for value in config.get("lengths", [])) or "configured"
        return (
            "Reference fixed window detector",
            f"The melodic branch tests fixed note windows ({lengths}) and verifies a constant pitch shift, "
            "onset timing and duration. It has no insertion or deletion alignment.",
        )
    edits = config.get("max_edits", "configured")
    fraction = config.get("max_edit_fraction", "configured")
    bounds = f"{config.get('min_notes', 6)} to {config.get('max_notes', 32)}"
    common = (
        f"The melodic branch tests {bounds} note source windows. A monotone alignment keeps a fixed "
        f"transposition and explicit timing and duration bounds, with at most {edits} edits and an edit "
        f"fraction of {fraction}. It does not warp tempo."
    )
    if algorithm == "aligned":
        return "Aligned detector", common + " Candidate anchors are heuristic and bounded by disclosed search limits."
    if algorithm == "aligned_indexed":
        return (
            "Indexed aligned detector",
            common + " An experimental index and exact signature cache schedule candidate pairs before the same "
            "verifier. The index changes candidate coverage and retains explicit limit telemetry.",
        )
    if algorithm == "aligned_closed":
        return (
            "Indexed alignment with closed exact selection",
            common + " Indexed candidate generation is followed by an optional selection rule. A longer exact "
            "family may replace a nested family when both have at least three zero-residual occurrences, equal "
            "support, one-to-one endpoint containment and a score within 0.02 of the current selection. "
            "This is structural selection, not a listener-validated phrase boundary rule.",
        )
    if algorithm == "aligned_melody":
        return (
            "Indexed alignment with optional melody part prior",
            common + " Indexed candidate generation applies a fixed structural part prior before closed exact "
            "selection. The prior combines onset monophony with weight 0.65 and voice independence with weight "
            "0.35. Selection uses recurrence score + 0.08 × (part prior - 0.5). The original recurrence score is "
            "preserved and the adjusted selection score is recorded separately. The prior was selected for "
            "POP909 MELODY part agreement and is not a listener-validated phrase quality rule.",
        )
    raise ValueError(f"unsupported extraction algorithm: {algorithm}")


def validate_screening(dataset: Path, screening_path: Path) -> tuple[dict, dict[str, Path]]:
    """Run the shared verifier and enforce the paper's zero cross-edge claim."""
    screening_dir = Path(screening_path)
    if screening_dir.is_file():
        screening_dir = screening_dir.parent
    summary = verify_screening(Path(dataset), screening_dir)
    if summary.get("retained_cross_split_candidate_edges") != 0:
        raise ValueError("screening retains cross split candidate edges")
    inputs = {
        name: screening_dir / name for name in (
            "summary.json", "source_splits.jsonl", "phrase_splits.jsonl", "candidate_edges.jsonl", "duplicate_report.json",
        )
    }
    return summary, inputs


def validate_selection_replay(dataset_info: dict, replay_path: Path) -> tuple[dict, dict[str, Path], dict[str, dict]]:
    """Reuse the package verifier and freeze every portable replay artifact."""
    replay = Path(replay_path)
    binding = _selection_replay_binding(
        replay,
        dataset_info["path"],
        dataset_info["summary"],
        dataset_info["audit"],
        dataset_info["build"],
    )
    files = sorted(binding.pop("files"))
    replay = replay.resolve(strict=True)
    inputs: dict[str, Path] = {}
    artifacts: dict[str, dict] = {}
    for index, relative in enumerate(files):
        path = replay / relative
        key = f"artifact_{index:04d}_{Path(relative).name}"
        inputs[key] = path
        artifacts[key] = {
            "relative_path": relative,
            "bytes": path.stat().st_size,
            "sha256": file_digest(path),
        }
    summary = {
        **binding,
        "portable_artifact_count": len(files),
        "portable_artifacts_sha256": _sha256_json(
            {item["relative_path"]: {"bytes": item["bytes"], "sha256": item["sha256"]}
             for item in artifacts.values()}
        ),
    }
    return summary, inputs, artifacts


def _recheck_selection_replay(
    dataset_info: dict,
    replay_path: Path,
    expected_summary: dict,
    expected_artifacts: dict[str, dict],
) -> None:
    summary, _inputs, artifacts = validate_selection_replay(dataset_info, replay_path)
    if summary != expected_summary or artifacts != expected_artifacts:
        raise ValueError("selection replay input changed before paper receipt")


def selection_replay_scope_text(audit: dict, replay: dict | None) -> tuple[str, str | None]:
    """Describe primary audit and supplementary replay scopes without quality claims."""
    if audit.get("reextraction_required") is True:
        primary = (
            "The primary artifact audit re-extracted every successful source and compared the complete selected "
            "output and detector evidence."
        )
    else:
        primary = (
            "The primary artifact audit did not repeat candidate generation and selection for every successful "
            "source. Stored candidate ordering and selection decisions are not fully replayed by that audit."
        )
    if replay is None:
        return primary, None
    selected = replay["selection_count"]
    passed = replay["passed_count"]
    successful = replay["successful_source_count"]
    errors = replay["error_source_count"]
    total = successful + errors
    result = (
        f"The supplementary selection replay selected {selected:,} successful sources and passed {passed:,} of "
        f"{selected:,}, with {replay['failure_count']:,} failures. "
    )
    if replay["selection_covers_all_successful_sources"]:
        result += f"It covers all {successful:,} successful sources"
    else:
        result += f"It is a bounded cohort of {selected:,} from {successful:,} successful sources"
    result += (
        f"; the full manifest denominator is {successful:,} successful and {errors:,} error sources "
        f"({total:,} total). This replay is a consistency check and makes no musical quality claim."
    )
    return primary, result


def _paper_input_records(
    inputs: dict[str, Path],
    selection_replay_artifacts: dict[str, dict] | None = None,
) -> dict[str, dict]:
    records = {
        key: {"path": str(path), "sha256": file_digest(path)}
        for key, path in sorted(inputs.items())
    }
    for key, artifact in (selection_replay_artifacts or {}).items():
        receipt_key = f"selection_replay_{key}"
        if receipt_key not in records:
            raise ValueError("selection replay artifact is absent from paper inputs")
        records[receipt_key].update(
            {
                "sha256": artifact["sha256"],
                "bytes": artifact["bytes"],
                "relative_path": artifact["relative_path"],
            }
        )
    return records


def pipeline() -> Drawing:
    drawing = Drawing(480, 84)
    labels = [
        ("Source MIDI", "hash + parse", "#e5edf5"),
        ("Two branches", "melody / drums", "#dcefe9"),
        ("Verify repeats", "timing + pitch", "#dcefe9"),
        ("Local candidates", "audit + review", "#f7ecd9"),
    ]
    for index, (title, subtitle, color) in enumerate(labels):
        x = index * 122
        drawing.add(Rect(x, 17, 112, 54, rx=5, fillColor=colors.HexColor(color), strokeColor=None))
        drawing.add(String(x + 56, 49, title, textAnchor="middle", fontName="Helvetica-Bold", fontSize=10, fillColor=INK))
        drawing.add(String(x + 56, 32, subtitle, textAnchor="middle", fontSize=9, fillColor=MUTED))
        if index < 3:
            drawing.add(Line(x + 113, 44, x + 120, 44, strokeColor=MUTED))
            drawing.add(Polygon([x + 118, 47, x + 122, 44, x + 118, 41], fillColor=MUTED, strokeColor=None))
    return drawing


def _footer(canvas, doc) -> None:
    canvas.saveState()
    canvas.setStrokeColor(colors.HexColor("#c7d4de"))
    canvas.line(20 * mm, 17 * mm, A4[0] - 20 * mm, 17 * mm)
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(MUTED)
    canvas.drawString(20 * mm, 12 * mm, "SaMuGeD | recurring phrase dataset | no listener labels")
    canvas.drawRightString(A4[0] - 20 * mm, 12 * mm, str(doc.page))
    canvas.restoreState()


def _build_pdf(output: Path, story: list, title: str = "SaMuGeD recurring phrase candidates") -> None:
    """Build a byte reproducible PDF from a newly constructed story."""
    output.parent.mkdir(parents=True, exist_ok=True)
    document = SimpleDocTemplate(
        str(output), pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm,
        topMargin=18 * mm, bottomMargin=23 * mm, title=title,
        author="SaMuGeD project", subject="Audited recurring phrase candidate dataset",
        creator="SaMuGeD make_paper.py", producer="ReportLab",
        pageCompression=1, invariant=1,
    )
    document.build(story, onFirstPage=_footer, onLaterPages=_footer)


def render(
    dataset: Path, melody_path: Path, drums_path: Path, output: Path,
    stress_path: Path, external_path: Path, aligned_path: Path | None = None,
    screening_path: Path | None = None, report_date: str | None = None,
    theme_path: Path | None = None, theme_input_root: Path | None = None,
    theme_input_audit: Path | None = None, closed_path: Path | None = None,
    metamorphic_path: Path | None = None,
    part_ranking_path: Path | None = None,
    part_ranking_audit_path: Path | None = None,
    certified_drums_path: Path | None = None,
    certified_drums_audit_path: Path | None = None,
    selection_external_path: Path | None = None,
    comparison_paths: list[Path] | tuple[Path, ...] | None = None,
    selection_replay_path: Path | None = None,
) -> None:
    dataset_info = validate_dataset(dataset)
    comparison_datasets = validate_comparison_datasets(
        dataset_info, comparison_paths,
    )
    summary, audit, build = dataset_info["summary"], dataset_info["audit"], dataset_info["build"]
    selection_replay, selection_replay_inputs, selection_replay_artifacts = None, {}, {}
    if selection_replay_path is not None:
        selection_replay, selection_replay_inputs, selection_replay_artifacts = validate_selection_replay(
            dataset_info, selection_replay_path,
        )
    profiles = phrase_profile(dataset_info)
    melody, melody_receipt, melody_inputs = validate_melody(melody_path)
    drums, drum_inputs = validate_drums(drums_path)
    stress, stress_inputs = validate_stress(stress_path)
    external, external_inputs = validate_external(external_path)
    aligned, aligned_inputs = (None, {})
    if aligned_path:
        aligned, aligned_inputs = validate_aligned(aligned_path)
    closed, closed_inputs = (None, {})
    if closed_path:
        closed, closed_inputs = validate_closed(closed_path)
    metamorphic, metamorphic_inputs = (None, {})
    if metamorphic_path:
        metamorphic, metamorphic_inputs = validate_metamorphic(metamorphic_path)
    screening, screening_inputs = (None, {})
    if screening_path:
        screening, screening_inputs = validate_screening(dataset_info["path"], screening_path)
    themes, theme_inputs = None, {}
    if any(value is not None for value in (theme_path, theme_input_root, theme_input_audit)):
        if any(value is None for value in (theme_path, theme_input_root, theme_input_audit)):
            raise ValueError("theme evaluation requires its input root and input audit")
        themes, theme_inputs = validate_themes(theme_path, theme_input_root, theme_input_audit)
    part_ranking, part_ranking_inputs = None, {}
    if any(value is not None for value in (part_ranking_path, part_ranking_audit_path)):
        if part_ranking_path is None or part_ranking_audit_path is None:
            raise ValueError("part ranking evidence requires its independent audit")
        part_ranking, part_ranking_inputs = validate_part_ranking(
            part_ranking_path, part_ranking_audit_path,
        )
    certified_drums, certified_drums_inputs = None, {}
    if any(value is not None for value in (certified_drums_path, certified_drums_audit_path)):
        if certified_drums_path is None or certified_drums_audit_path is None:
            raise ValueError("certified drum evidence requires its independent audit")
        certified_drums, certified_drums_inputs = validate_certified_drums(
            certified_drums_path, certified_drums_audit_path,
        )
    selection_external, selection_external_inputs = None, {}
    if selection_external_path is not None:
        if theme_input_root is None or theme_input_audit is None:
            raise ValueError("external selector evidence requires Theme input root and audit")
        selection_external, selection_external_inputs = validate_selection_external(
            selection_external_path, theme_input_root, theme_input_audit,
        )
    paper_date, date_source = resolve_report_date(report_date, melody_receipt)
    algorithm = dataset_info["algorithm"]
    method_title, method_text = method_description(algorithm, build.get("config", {}))
    full = summary["source_files"] == summary.get("discovered_source_files") and summary.get("cohort_limit") is None
    scope = "Full processed corpus" if full else "Pilot only"

    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle("TitleLocal", fontName="Helvetica-Bold", fontSize=25, leading=29, textColor=INK, spaceAfter=12))
    styles.add(ParagraphStyle("Deck", fontName="Helvetica", fontSize=11, leading=16, textColor=MUTED, spaceAfter=15))
    styles.add(ParagraphStyle("BodyLocal", fontName="Helvetica", fontSize=9.7, leading=13.3, textColor=INK, spaceAfter=7))
    styles.add(ParagraphStyle("SmallLocal", fontName="Helvetica", fontSize=8.1, leading=10.8, textColor=MUTED, spaceAfter=5))
    styles.add(ParagraphStyle("SectionLocal", fontName="Helvetica-Bold", fontSize=13, leading=16, textColor=BLUE, spaceBefore=9, spaceAfter=6, keepWithNext=True))
    styles.add(ParagraphStyle("CellLocal", fontName="Helvetica", fontSize=8.7, leading=11.2, textColor=INK))
    story: list = []

    def p(text: str, style: str = "BodyLocal") -> None:
        story.append(Paragraph(text, styles[style]))

    def heading(text: str) -> None:
        p(text, "SectionLocal")

    def table(values: list[list[Any]], widths: list[int]) -> None:
        data = [[Paragraph(str(cell), styles["CellLocal"]) for cell in row] for row in values]
        item = Table(data, colWidths=widths, hAlign="LEFT", repeatRows=1)
        item.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), PALE), ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LINEBELOW", (0, 0), (-1, 0), 0.6, BLUE),
            ("LINEBELOW", (0, 1), (-1, -1), 0.3, colors.HexColor("#dbe2e8")),
            ("LEFTPADDING", (0, 0), (-1, -1), 7), ("RIGHTPADDING", (0, 0), (-1, -1), 7),
            ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        story.extend([item, Spacer(1, 7)])

    def page() -> None:
        story.append(PageBreak())

    p("SaMuGeD recurring<br/>phrase candidates", "TitleLocal")
    p("An audited MIDI dataset with separate melodic and percussion tracks", "Deck")
    p(f"Research note · {paper_date} · {scope} · {method_title} · Research release", "SmallLocal")
    heading("Abstract")
    p("This note describes a reproducible pipeline for finding recurring symbolic phrases in multitrack MIDI. "
      "Melodic candidates are checked with pitch, onset and duration constraints. A separate percussion detector "
      "retains distinct simultaneous kit pitches and compares meter aware patterns without pitch transposition. Every "
      "output links to source coordinates and a checksum. Controlled planted patterns test the implemented rules. "
      "The collection contains recurring candidates. It has no listener evidence for hooks, salience or memorability.")
    story.append(pipeline())
    heading("1. Data and accounting")
    parsed = summary["source_status"].get("ok", 0)
    table([
        ["Measure", "Observed value"],
        ["Source files considered", f"{summary['source_files']:,}"],
        ["Parsed and processed / errors", f"{parsed:,} / {summary['source_status'].get('error', 0):,}"],
        ["Melodic / percussion candidates", f"{summary['phrase_counts'].get('melodic', 0):,} / {summary['phrase_counts'].get('percussion', 0):,}"],
        ["Files with melodic / percussion output", f"{summary['source_files_with_melodic_phrases']:,} / {summary['source_files_with_percussion_phrases']:,}"],
        ["MIDI excerpts verified by audit", f"{audit['counts'].get('midi_verified', 0):,}"],
    ], [295, 185])
    p(f"The study uses a local copy labelled Lakh MIDI Clean [1, 10]. The manifest defines the processed snapshot of "
      f"{summary['source_files']:,} paths, not a verified copy of an upstream archive. Byte identity does "
      "not establish unique musical works. Path labels may be incomplete or wrong. Every selected source has a "
      "terminal processing record and failed inputs remain in the denominator. Original MIDI files are not rewritten.")
    p("Pattern discovery can disagree with human annotation [3]. We therefore separate tests of implemented "
      "matching rules from external human theme diagnostics and future listening judgements.", "SmallLocal")
    if comparison_datasets:
        values = [[
            "Full build", "Melodic", "Drums", "Parsed OK", "No match",
            "Melody limits", "Drum limit",
        ]]
        for info in (dataset_info, *comparison_datasets):
            counts = info["manifest_counts"]
            values.append([
                ALGORITHM_LABELS[info["algorithm"]],
                f"{counts['phrase_counts']['melodic']:,}",
                f"{counts['phrase_counts']['percussion']:,}",
                f"{counts['successful_files']:,}",
                f"{counts['no_match_files']:,}",
                f"{counts['search_limited_files']:,} / {counts['curation_truncated_files']:,}",
                f"{counts['drum_search_limited_files']:,}",
            ])
        table(values, [92, 56, 56, 54, 48, 88, 66])
        p(
            "All rows use the same source IDs, paths, bytes, terminal status and metadata repair receipts. "
            "Melody limits report search-limited / shortlist-truncated files. These are output and selection "
            "counts, not accuracy estimates, and no optional algorithm is promoted as the default.",
            "SmallLocal",
        )

    page()
    heading("2. Extraction method")
    p("The parser retains integer source ticks, meter, tempo, channel, program and velocity information. MIDI format "
      "and parse failures remain explicit. Exported excerpts begin at tick zero and retain the active timing context.")
    heading(method_title)
    p("Notes are partitioned by track, channel and program. Percussion channel notes are excluded from the melodic "
      "branch. An onset skyline keeps the highest pitch in each configured onset group. This heuristic can select "
      "chord tops or accompaniment.")
    p(method_text)
    cfg = build.get("config", {})
    limits = "configured"
    if isinstance(cfg.get("max_comparisons"), int) and isinstance(cfg.get("max_windows"), int):
        limits = f"{cfg['max_comparisons']:,} / {cfg['max_windows']:,}"
    table([
        ["Configured bound", "Value"],
        ["Phrase span in beats", f"{cfg.get('min_beats', 'n/a')} to {cfg.get('max_beats', 'n/a')}"],
        ["Onset / duration tolerance", f"{cfg.get('timing_tolerance', 'n/a')} / {cfg.get('duration_tolerance', 'n/a')} beats"],
        ["Maximum comparisons / windows", limits],
        ["Returned candidates per source", str(cfg.get("top_k", "n/a"))],
    ], [270, 210])
    p("Support uses nonoverlapping occurrences. Ranking and shortlist limits are engineering choices. Search and "
      "curation limits are retained in the source manifest, so the output is a selected candidate set rather than an "
      "exhaustive catalogue.")
    heading("Percussion patterns")
    p("The percussion branch retains distinct simultaneous kit pitches and merges exact onset/pitch duplicates "
      "across parts. Matching uses kit pitch and strike onset, without transposition, gate length or velocity. "
      "Candidates span configured bar counts without crossing a meter change. Tick zero and meter changes "
      "define bar origins, so pickup handling is a known limitation.")
    def displayed(value: float | None) -> str:
        return "n/a" if value is None else f"{value:g}"
    table([
        ["Median selected phrase", "Melodic", "Percussion"],
        ["Notes or strikes", *[displayed(profiles[k]["notes"]) for k in ("melodic", "percussion")]],
        ["Span in quarter notes", *[displayed(round(profiles[k]["beats"], 2)) if profiles[k]["beats"] is not None else "n/a" for k in ("melodic", "percussion")]],
        ["Nonoverlapping occurrences", *[displayed(profiles[k]["occurrences"]) for k in ("melodic", "percussion")]],
    ], [250, 115, 115])

    if algorithm == "reference" and (aligned or closed or part_ranking):
        heading("Evaluated extensions")
        if aligned:
            p("Indexed alignment searches 6 to 32 note windows. It verifies a constant pitch shift and "
              "bounded onset and duration differences. The internal edit budget is 15% of the longer window "
              "length, rounded down, with a minimum of one and maximum of four. It does not warp tempo or allow terminal "
              "gaps. Indexed anchors reduce pair enumeration but can miss valid repetitions.", "SmallLocal")
        if closed:
            p("Closed exact selection can replace a shorter family with a containing longer family. Both "
              "must have the same support of at least three exact occurrences, with one-to-one containment "
              "and a shared endpoint. The recurrence score may decrease by at most 0.02 per replacement "
              "step. This recovers planted longer repeats in controlled cases, not established human phrase "
              "boundaries. Periodic passages can extend beyond a listener's preferred boundary. This project-specific "
              "selector differs from geometric compression [8] and multiparametric closed-pattern mining [9]; "
              "no general pattern-discovery novelty is claimed.", "SmallLocal")
        if part_ranking:
            p("The optional melody selector uses a part prior of 0.65 × onset monophony + 0.35 × voice "
              "independence. It ranks candidates by recurrence score + 0.08 × (prior - 0.5) before closed "
              "selection. Track names and instrument programs are not features. The original recurrence "
              "score is retained separately.", "SmallLocal")

    page()
    heading("3. Controlled evaluation")
    p("Synthetic songs contain planted motifs with known intervals and negative controls. Development and test use "
      "separate seed namespaces. Candidate and occurrence measures use temporal intersection over union of at least "
      f"{melody.get('iou_threshold', 0.8):.1f}. These diagnostics do not estimate accuracy on real music.")
    mt = {name: value["by_split"]["test"] for name, value in melody["methods"].items()}
    values = [["Melodic mode", "Cases", "Occurrence precision", "Recall", "F1"]]
    for name in ("exact", "transposed", "approximate"):
        item = mt[name]
        values.append([name.capitalize(), item["cases"], f"{item['occurrence']['precision']:.3f}", f"{item['occurrence']['recall']:.3f}", f"{item['occurrence']['f1']:.3f}"])
    table(values, [110, 60, 120, 95, 95])
    approx = mt["approximate"]
    p(f"Approximate mode recovered {approx['recovered_positive_cases']} of {approx['positive_cases']} positive test "
      f"cases. It returned candidates in {approx['false_positive_case_count']} of {approx['negative_cases']} generated "
      "negative cases. A zero observed count, when present, is not evidence of zero real world error.")
    dt = {name: value["by_split"]["test"] for name, value in drums["methods"].items()}
    values = [["Percussion mode", "Positive recovery", "Occurrence F1", "Negative cases with output"]]
    for name in ("exact", "tolerant"):
        item = dt[name]
        values.append([name.capitalize(), f"{item['recovered_positive_cases']} / {item['positive_cases']}", f"{item['occurrence']['f1']:.3f}", f"{item['false_positive_case_count']} / {item['negative_cases']}"])
    table(values, [125, 125, 100, 130])
    upper = dt["tolerant"].get("zero_false_positive_upper_95")
    if upper is not None:
        p(f"For tolerant percussion matching, the Wilson 95% upper bound for the observed zero negative case output "
          f"rate is {upper:.2%}. The controls were designed around detector tolerances and are not a blind challenge.", "SmallLocal")
    p("The historical detector exports prototypes without occurrence coordinates. Its occurrence F1 is therefore not "
      "reported. Human phrase boundaries, perceptual identity and memorability remain unmeasured.")

    if certified_drums:
        heading("Oracle certified percussion controls")
        certified_test = {
            mode: certified_drums["methods"][mode]["test"]
            for mode in ("exact", "tolerant")
        }
        certified_family = certified_drums["family_recovery_posthoc"]
        table([
            ["Heldout measure", "Exact", "Tolerant"],
            ["Certified negatives returning output", *[
                f"{certified_test[mode]['negative_cases_with_output']} / {certified_test[mode]['negative_cases']}"
                for mode in ("exact", "tolerant")
            ]],
            ["Direct labelled edges recovered", *[
                f"{certified_test[mode]['positive_target_pairs_covered_by_direct_detector_edges']} / "
                f"{certified_test[mode]['positive_target_pairs']}"
                for mode in ("exact", "tolerant")
            ]],
            ["One family covers all labelled windows", *[
                f"{certified_family[mode]['test']['families_covering_all_labelled_target_windows']} / 60"
                for mode in ("exact", "tolerant")
            ]],
        ], [265, 105, 110])
        upper = certified_test["tolerant"]["negative_output_wilson_95"][1]
        p(
            f"The test split had 120 oracle certified negatives and 60 planted positives. A separate development "
            f"split had another 120 negatives and 60 positives. Zero of 120 test negatives returned output "
            f"(Wilson 95% upper bound {upper:.1%}). "
            "The 120 of 180 positive result counts labelled prototype to occurrence edges, not occurrence recall. "
            "The 60 of 60 family result is a posthoc measure from the independently bound replay audit.",
            "SmallLocal",
        )

    if certified_drums:
        page()
    heading("4. Alignment and full-phrase selection")
    if aligned:
        methods = aligned["synthetic"]["methods"]
        ref = methods["reference_approximate"]["by_split"]["test"]
        ali = methods["aligned"]["by_split"]["test"]
        table([
            [f"{ali['cases']} case test measure", "Reference approximate", "Aligned"],
            ["Occurrence F1", f"{ref['occurrence']['f1']:.3f}", f"{ali['occurrence']['f1']:.3f}"],
            ["Positive cases recovered", f"{ref['recovered_positive_cases']} / {ref['positive_cases']}", f"{ali['recovered_positive_cases']} / {ali['positive_cases']}"],
            ["Negative cases with output", f"{ref['false_positive_case_count']} / {ref['negative_cases']}", f"{ali['false_positive_case_count']} / {ali['negative_cases']}"],
        ], [230, 125, 125])
        paired = aligned["synthetic"]["paired_bootstrap"]["test"]["occurrence_f1"]
        ci = paired["bootstrap_ci95"]
        p(f"The paired occurrence F1 difference is {paired['aligned_minus_reference']:.3f}, with a 95% "
          f"case-bootstrap interval from {ci[0]:.3f} to {ci[1]:.3f}.", "SmallLocal")
        for condition in ("inserted_note", "deleted_note", "legacy_contiguous_exact"):
            left, right = ref["by_kind"].get(condition), ali["by_kind"].get(condition)
            if left and right:
                p(f"{condition.replace('_', ' ').capitalize()}: reference recovered {left['recovered_cases']} of "
                  f"{left['positive_cases']}; aligned recovered {right['recovered_cases']} of {right['positive_cases']}.", "SmallLocal")
        real = aligned["real_pilot"]["methods"]
        if "reference_approximate" in real and "aligned" in real:
            left, right = real["reference_approximate"], real["aligned"]
            p(f"On {left['successful_files']} unlabeled real pilot files, reference runtime was "
              f"{left['runtime_seconds']['total']:.1f} seconds and aligned runtime was "
              f"{right['runtime_seconds']['total']:.1f} seconds. Search limits occurred in "
              f"{left['search_limited_files']} and {right['search_limited_files']} files. These measurements provide "
              "runtime and limit evidence only.")
    else:
        p("No separately validated alignment comparison was supplied. This page therefore makes no insertion or "
          "deletion recovery comparison.")
    if closed:
        variants = closed["synthetic"]["aligned_indexed"]
        original = variants["original"]
        optional = variants["closed_exact_extension"]
        table([
            ["Fresh 500-case measure", "Original selection", "Closed exact selection"],
            ["Occurrence F1", f"{original['occurrence']['f1']:.3f}", f"{optional['occurrence']['f1']:.3f}"],
            ["Positive cases recovered", f"{original['recovered_positive_cases']} / {original['positive_cases']}",
             f"{optional['recovered_positive_cases']} / {optional['positive_cases']}"],
            ["Negative cases with output", f"{original['false_positive_case_count']} / {original['negative_cases']}",
             f"{optional['false_positive_case_count']} / {optional['negative_cases']}"],
        ], [230, 125, 125])
        paired = closed["paired_deltas"]["aligned_indexed"]["occurrence_f1"]
        ci = paired["case_bootstrap_ci95"]
        real = closed["real_pilot"]["aligned_indexed"]
        p(
            f"Closed exact selection changed occurrence F1 by {paired['closed_minus_original']:+.3f} "
            f"(95% paired case-bootstrap interval {ci[0]:+.3f} to {ci[1]:+.3f}). It changed selected "
            f"output in {real['changed_file_count']} of {real['files']} unlabeled real pilot files. New seeds reuse "
            "the same synthetic generator after development diagnosis. This measures repeat recovery within that "
            "generator. The real examples remain unlabelled, and neither study measures memorability.",
            "SmallLocal",
        )
    if part_ranking:
        heading("Optional source part prior")
        development = part_ranking["development"]
        heldout = part_ranking["heldout"]
        table([
            ["POP909 MELODY role agreement", "Baseline", "Optional prior"],
            ["Development top one", f"{development['baseline_top1']} / 60", f"{development['prior_top1']} / 60"],
            ["Heldout top one", f"{heldout['baseline_top1']} / 120", f"{heldout['prior_top1']} / 120"],
            ["Heldout top three", f"{heldout['baseline_top3']} / 120", f"{heldout['prior_top3']} / 120"],
        ], [265, 105, 110])
        top1_ci = heldout["paired_top1_difference"]["ci95"]
        top3_ci = heldout["paired_top3_difference"]["ci95"]
        p(
            f"One of eight declared timing and pitch structure priors was selected on 60 POP909 [7] development "
            "songs, then "
            f"frozen. Heldout improvements were 34 of 120 for top one (paired song bootstrap 95% interval "
            f"{top1_ci[0]:.1%} to {top1_ci[1]:.1%}) and 17 of 120 for top three "
            f"({top3_ci[0]:.1%} to {top3_ci[1]:.1%}). All 120 heldout shortlists were truncated. Labels were "
            "process separated, not physically inaccessible. This measures official MELODY part agreement only, "
            "not hook quality, and the prior remains optional. The fixed rule uses note structure only, but transfer "
            "from POP909 role labels to the different Lakh corpus and arrangement domain remains unmeasured.",
            "SmallLocal",
        )

    page()
    heading("5. Harder and external diagnostics")
    st = {name: value["by_split"]["test"] for name, value in stress["methods"].items()}
    heading("Longer percussion contexts")
    if stress.get("provenance_status") == "legacy_no_executable_snapshot":
        p(
            "The accepted drum stress artifact is a legacy v01 diagnostic. Its frozen design and cohort hashes "
            "are verified, but it predates executable source, dependency and interpreter snapshots.",
            "SmallLocal",
        )
    table([
        ["Test measure", "Exact", "Tolerant"],
        ["Exact identity controls recovered", *[f"{st[m]['exact_identity_control_recovered']} / {st[m]['exact_identity_control_cases']}" for m in ("exact", "tolerant")]],
        ["Supported controls recovered", *[f"{st[m]['tolerant_supported_control_recovered']} / {st[m]['tolerant_supported_control_cases']}" for m in ("exact", "tolerant")]],
        ["Negative cases returning output", *[f"{st[m]['negative_cases_with_output']} / {st[m]['negative_cases']}" for m in ("exact", "tolerant")]],
    ], [270, 105, 105])
    interval = st["tolerant"].get("negative_case_output_wilson_95")
    if interval:
        p(f"Tolerant mode returned output in {st['tolerant']['negative_case_output_rate']:.1%} of generated negative "
          f"test cases (Wilson 95% interval {interval[0]:.1%} to {interval[1]:.1%}). Recurring subpatterns can satisfy "
          "the symbolic rule, so this is a generator output rate rather than verified musical false positive precision.")
    if certified_drums:
        p(
            "The certified control result and this stress result answer different questions. Certified negatives "
            "were conditioned to contain no admissible detector window pair. Stress negatives can contain chance or "
            "genuine recurring substructure, and tolerant mode returned output in "
            f"{st['tolerant']['negative_cases_with_output']} of {st['tolerant']['negative_cases']} test cases.",
            "SmallLocal",
        )
    heading("Externally annotated classical works")
    values = [["Representation / mode", "Works", "Establishment F1", "Occurrence F1 (0.75)"]]
    for key in sorted(external["groups"]):
        if themes and not key.endswith("/approximate"):
            continue
        item = external["groups"][key]
        metric = item["macro_metrics"]
        values.append([key, item["works"], f"{metric['F_est']:.3f}", f"{metric['F_occ.75']:.3f}"])
    table(values, [210, 55, 105, 110])
    p(f"The JKU-PDD adapter [4, 5, 11] verified annotation points against the score and reproduced the stored metric checks. "
      f"Results use top k = {external.get('top_k', 3)}. This small development set is not an official MIREX result and "
      "does not estimate popular music performance.")
    if themes:
        heading("Six popular songs with three annotators")
        values = [["Detector", "Top-one note F1", "95% song interval", "Top-three F1"]]
        for key, label in (("reference_approximate", "Reference"), ("aligned_indexed", "Aligned indexed")):
            first = themes["method_views"][f"{key}/top1"]
            third = themes["method_views"][f"{key}/top3"]
            ci = first["cluster_bootstrap_by_song"]["f1"]
            values.append([label, f"{first['macro_over_songs']['f1']:.3f}",
                           f"{ci['ci95_low']:.3f} to {ci['ci95_high']:.3f}",
                           f"{third['macro_over_songs']['f1']:.3f}"])
        table(values, [130, 110, 130, 110])
        if selection_external:
            indexed = selection_external["jku"]["groups"]["polyphonic/aligned_indexed"]["macro_metrics"]
            prior = selection_external["jku"]["groups"]["polyphonic/aligned_melody"]["macro_metrics"]
            p(
                "The selector diagnostic reuses these six songs [6] and the five JKU development works. Theme uses "
                "one neutral Part, so the melody prior equals closed selection and cannot test part-role choice; "
                "all note F1 values were unchanged. Closed selection changed none of ten JKU outputs. The melody "
                f"prior changed three polyphonic outputs: establishment F1 {indexed['F_est']:.6f} to "
                f"{prior['F_est']:.6f}, while occurrence F1 at 0.75 stayed {indexed['F_occ.75']:.6f}. All 48 "
                "shortlists were truncated at 80 candidates. This is reused development evidence, not a fresh "
                "heldout test or evidence of memorability.",
                "SmallLocal",
            )
        else:
            p("Theme Transformer annotations [6] share exact note universes across three annotators. Annotation partitions "
              "are removed before detection. These scores classify notes, not the authors' beat regions. Agreement "
              "varies substantially and includes negative kappa. All 24 runs reached the candidate shortlist cap. "
              "Top three expands coverage and is a sensitivity view. No parameter was tuned on these songs.", "SmallLocal")

    if metamorphic:
        heading("Symbolic invariance")
        p(f"Across {metamorphic['source_count']} fixed real files, reference melody, indexed alignment and percussion "
          "were checked after tempo changes, doubled tick resolution and a five-semitone melodic transposition "
          f"that retained drum pitches. There were {metamorphic['total_failures']} failures in "
          f"{metamorphic['evaluated_rows']:,} eligible comparisons and {metamorphic['skipped_rows']} skipped comparisons. "
          "Ranked musical fields and family identities were compared after inverse normalization. This checks "
          "representation consistency, not phrase quality.", "SmallLocal")

    page()
    heading("6. Dataset structure and limitations")
    p("Phrase rows contain source identity, tick bounds, note arrays, occurrence coordinates, scores and excerpt "
      "checksums. Source rows retain parser outcomes and limit diagnostics. Split groups use available path identity, "
      "byte and arrangement evidence. Covers, aliases and near duplicates can remain.")
    if screening:
        excluded = screening["newly_excluded_phrase_counts"]
        p(f"The supplementary split view quarantines {screening['excluded_source_groups']} original groups, "
          f"newly excluding {excluded.get('validation', 0):,} validation and {excluded.get('test', 0):,} test "
          "phrase rows. No retained strong candidate edge crosses splits. These edges are heuristic duplicate "
          "signals; the view changes evaluation distributions and does not establish composition identity.")
    else:
        p("No verified supplementary duplicate screening view was supplied. Base split grouping and canonical family "
          "exclusions remain the only split controls described here.")
    table([
        ["Audit or limit", "Observed value"],
        ["Melodic files with a search limit", f"{summary['search_limited_files']:,}"],
        ["Melodic files with shortlist truncation", f"{summary['curation_truncated_files']:,}"],
        ["Percussion files with a search or curation limit", f"{summary['drum_search_limited_files']:,}"],
        ["Canonical family rows excluded across splits", f"{summary['family_split_conflict_rows']:,}"],
        ["Artifact audit failures", str(audit["failure_count"])],
    ], [350, 130])
    primary_replay_scope, supplementary_replay_scope = selection_replay_scope_text(
        audit, selection_replay,
    )
    p(primary_replay_scope, "SmallLocal")
    if supplementary_replay_scope is not None:
        p(supplementary_replay_scope, "SmallLocal")
    p("The audit checks source and excerpt consistency within this repository, without external certification. "
      "Human phrase labels remain uncollected. Lakh is distributed under CC BY 4.0 but reports inconsistent MIDI "
      "attribution [1]. This audit does not establish rights to compositions, arrangements or excerpts. "
      "The release follows the upstream collection licence with source attribution. No independent clearance of underlying compositions or arrangements is claimed. Listener ratings are outside this release.")
    p(f"Run fingerprint: <font name='Courier'>{summary['run_key']}</font>", "SmallLocal")
    p(f"Source manifest SHA256: <font name='Courier'>{summary['source_manifest_sha256']}</font>", "SmallLocal")
    p(f"Phrase manifest SHA256: <font name='Courier'>{summary['phrase_manifest_sha256']}</font>", "SmallLocal")
    heading("References")
    refs = [
        ("1", "Raffel. The Lakh MIDI Dataset v0.1.", "https://colinraffel.com/projects/lmd/"),
        ("2", "Choi et al. (2025). On the de-duplication of the Lakh MIDI dataset.", "https://arxiv.org/abs/2509.16662"),
        ("3", "Ren et al. (2020). A computational evaluation of musical pattern discovery algorithms.", "https://arxiv.org/abs/2010.12325"),
        ("4", "MIREX. Discovery of repeated themes and sections.", "https://music-ir.org/mirex/wiki/2014%3ADiscovery_of_Repeated_Themes_%26_Sections"),
        ("5", "Raffel et al. (2014). mir_eval.", "https://colinraffel.com/publications/ismir2014mir_eval.pdf"),
        ("6", "Shih et al. (2022). Theme Transformer: Symbolic Music Generation with Theme-Conditioned Transformer. IEEE TMM.", "https://arxiv.org/abs/2111.04093v2"),
        ("7", "Wang et al. (2020). POP909: A pop-song dataset for music arrangement generation. ISMIR.", "https://github.com/music-x-lab/POP909-Dataset"),
        ("8", "Meredith (2013). COSIATEC and SIATECCompress: Pattern discovery by geometric compression.", "https://vbn.aau.dk/en/publications/cosiatec-and-siateccompress-pattern-discovery-by-geometric-compre/"),
        ("9", "Lartillot (2014). In-depth motivic analysis based on multiparametric closed pattern and cyclic sequence mining.", "https://archives.ismir.net/ismir2014/paper/000308.pdf"),
        ("10", "Raffel (2016). Learning-Based Methods for Comparing Sequences, with Applications to Audio-to-MIDI Alignment and Matching. PhD thesis, Columbia University.", "https://colinraffel.com/publications/thesis.pdf"),
        ("11", "Collins (2013). JKU Patterns Development Database. August 2013 no-audio distribution.", "https://tomcollinsresearch.net/research/data/mirex/"),
    ]
    for number, title, url in refs:
        p(f"[{number}] <link href='{escape(url, quote=True)}' color='#265e83'>{escape(title)}</link>", "SmallLocal")

    _build_pdf(Path(output), story)
    for info in (dataset_info, *comparison_datasets):
        _recheck_dataset_bindings(info)
    if selection_replay is not None:
        _recheck_selection_replay(
            dataset_info, selection_replay_path, selection_replay,
            selection_replay_artifacts,
        )
    inputs: dict[str, Path] = {
        "dataset_summary": dataset_info["path"] / "summary.json",
        "dataset_audit": dataset_info["path"] / "audit.json",
        "dataset_build_config": dataset_info["path"] / "build_config.json",
        "dataset_sources": dataset_info["path"] / "sources.jsonl",
        "dataset_phrases": dataset_info["path"] / "phrases.jsonl",
    }
    for info in comparison_datasets:
        prefix = f"comparison_{info['algorithm']}"
        inputs.update({
            f"{prefix}_summary": info["path"] / "summary.json",
            f"{prefix}_audit": info["path"] / "audit.json",
            f"{prefix}_build_config": info["path"] / "build_config.json",
            f"{prefix}_sources": info["path"] / "sources.jsonl",
            f"{prefix}_phrases": info["path"] / "phrases.jsonl",
        })
    for prefix, values in (
        ("melody", melody_inputs), ("drums", drum_inputs), ("stress", stress_inputs),
        ("external", external_inputs), ("aligned", aligned_inputs), ("closed", closed_inputs),
        ("metamorphic", metamorphic_inputs),
        ("screening", screening_inputs),
        ("themes", theme_inputs),
        ("part_ranking", part_ranking_inputs),
        ("certified_drums", certified_drums_inputs),
        ("selection_external", selection_external_inputs),
        ("selection_replay", selection_replay_inputs),
    ):
        inputs.update({f"{prefix}_{name}": path for name, path in values.items()})
    input_records = _paper_input_records(inputs, selection_replay_artifacts)
    for info in (dataset_info, *comparison_datasets):
        _recheck_dataset_bindings(info)
    if selection_replay is not None:
        _recheck_selection_replay(
            dataset_info, selection_replay_path, selection_replay,
            selection_replay_artifacts,
        )
    receipt = {
        "run_key": summary["run_key"], "algorithm": algorithm,
        "report_date": paper_date, "report_date_source": date_source,
        "report_date_policy": DATE_POLICY, "deterministic_pdf": True,
        "pdf_sha256": file_digest(Path(output)),
        "generator_sha256": file_digest(Path(__file__)),
        "dataset_audit_bindings": dataset_info["hashes"],
        "dataset_audit_sha256": dataset_info["audit_sha256"],
        "comparison_datasets": [
            {
                "algorithm": info["algorithm"],
                "path": str(info["path"]),
                "run_key": info["summary"]["run_key"],
                "dataset_audit_bindings": info["hashes"],
                "audit_sha256": info["audit_sha256"],
                "source_identity_sha256": info["manifest_counts"]["source_identity_sha256"],
                "metadata_repairs_sha256": info["manifest_counts"]["metadata_repairs_sha256"],
                "manifest_counts": {
                    key: value for key, value in info["manifest_counts"].items()
                    if key not in {"source_identities", "metadata_repairs"}
                },
            }
            for info in comparison_datasets
        ],
        "selection_replay": selection_replay,
        "inputs": input_records,
    }
    Path(output).with_suffix(".inputs.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--melody-evaluation", type=Path, required=True)
    parser.add_argument("--drum-evaluation", type=Path, required=True)
    parser.add_argument("--drum-stress", type=Path, required=True)
    parser.add_argument("--external-evaluation", type=Path, required=True)
    parser.add_argument("--aligned-evaluation", type=Path)
    parser.add_argument("--closed-evaluation", type=Path)
    parser.add_argument("--metamorphic-evaluation", type=Path)
    parser.add_argument("--screening", type=Path, help="screening directory or summary.json")
    parser.add_argument("--report-date", help="frozen paper date in YYYY-MM-DD")
    parser.add_argument("--theme-evaluation", type=Path)
    parser.add_argument("--theme-input-root", type=Path)
    parser.add_argument("--theme-input-audit", type=Path)
    parser.add_argument("--part-ranking-evaluation", type=Path)
    parser.add_argument("--part-ranking-audit", type=Path)
    parser.add_argument("--certified-drum-evaluation", type=Path)
    parser.add_argument("--certified-drum-audit", type=Path)
    parser.add_argument("--selection-external-evaluation", type=Path)
    parser.add_argument(
        "--selection-replay", type=Path,
        help="completed supplementary selection replay for the primary dataset",
    )
    parser.add_argument(
        "--comparison-dataset", action="append", type=Path, default=[],
        help="audited full-corpus variant; repeat up to three times",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    render(
        dataset=args.dataset,
        melody_path=args.melody_evaluation,
        drums_path=args.drum_evaluation,
        output=args.output,
        stress_path=args.drum_stress,
        external_path=args.external_evaluation,
        aligned_path=args.aligned_evaluation,
        screening_path=args.screening,
        report_date=args.report_date,
        theme_path=args.theme_evaluation,
        theme_input_root=args.theme_input_root,
        theme_input_audit=args.theme_input_audit,
        closed_path=args.closed_evaluation,
        metamorphic_path=args.metamorphic_evaluation,
        part_ranking_path=args.part_ranking_evaluation,
        part_ranking_audit_path=args.part_ranking_audit,
        certified_drums_path=args.certified_drum_evaluation,
        certified_drums_audit_path=args.certified_drum_audit,
        selection_external_path=args.selection_external_evaluation,
        comparison_paths=args.comparison_dataset,
        selection_replay_path=args.selection_replay,
    )
    print(args.output.resolve())


if __name__ == "__main__":
    main()
