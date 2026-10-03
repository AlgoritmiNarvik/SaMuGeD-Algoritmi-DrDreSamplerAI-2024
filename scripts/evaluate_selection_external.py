"""Frozen external diagnostic for closed and optional part-prior selection.

The six ThemeTransformer songs and five JKU works are reused development
diagnostics.  This script changes only the selector applied to the fixed
aligned-indexed candidate generator.  It does not create a fresh heldout set.
"""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path
import time
from typing import Any

from samuged.aligned import AlignedConfig
from samuged.aligned_indexed import extract_indexed
from samuged.closed_patterns import extract_closed_patterns
from samuged.dataset import digest, file_digest
from samuged.evaluate_jku import (
    EXPECTED_PIECES,
    METRIC_PROVENANCE,
    load_piece,
    metrics as jku_metrics,
    prediction_points,
    verify_published_examples,
)
from samuged.evaluate_themes import (
    ANNOTATORS,
    OFFICIAL_SOURCE,
    SONG_IDS,
    bootstrap_song_macro,
    classification_metrics,
    load_cases,
    prediction_indices,
)
from samuged.experiment import (
    canonical_json,
    complete_experiment,
    prepare_experiment,
    receipt_links,
    sha256_json,
    verify_completed_experiment,
    verify_start_receipt,
)
from samuged.part_ranking import extract_part_ranked


VERSION = "selection-external-v1"
METHODS = ("aligned_indexed", "aligned_closed", "aligned_melody")
THEME_VIEWS = ("top1", "top3")
BOOTSTRAP_SEED = 20261031
BOOTSTRAP_SAMPLES = 10_000


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False)
        + "\n",
        encoding="utf-8",
    )


def _hashes(root: Path, names: tuple[str, ...]) -> dict[str, str]:
    return {name: file_digest(root / name) for name in names if (root / name).is_file()}


def _source_hash(snapshot: dict[str, Any], relative: str) -> str | None:
    for row in snapshot.get("files", []):
        if row.get("path") == relative:
            return row.get("sha256")
    return None


def _validate_theme_representation(case: Any) -> None:
    """Require a single neutral Part so annotation identities cannot reach detection."""
    if len(case.song.parts) != 1:
        raise ValueError(f"Theme song {case.song_id} is not represented as one Part")
    part = case.song.parts[0]
    expected = (0, 0, 0, 0, "canonical_melody", False)
    observed = (part.index, part.track, part.channel, part.program, part.name, part.is_drum)
    if observed != expected:
        raise ValueError(f"Theme song {case.song_id} retains annotation or instrument identity")
    if not part.notes:
        raise ValueError(f"Theme song {case.song_id} has no canonical notes")


def _detect(method: str, song: Any, config: dict[str, Any]) -> dict[str, Any]:
    cfg = AlignedConfig(**config)
    if method == "aligned_indexed":
        return extract_indexed(song, cfg)
    if method == "aligned_closed":
        return extract_closed_patterns(song, cfg, algorithm="aligned_indexed")
    if method == "aligned_melody":
        return extract_part_ranked(song, cfg)
    raise ValueError(f"unknown method: {method}")


def _telemetry(found: dict[str, Any]) -> dict[str, Any]:
    flags = (
        "note_limit_reached",
        "window_limit_reached",
        "comparison_limit_reached",
        "group_limit_reached",
        "candidate_limit_reached",
    )
    return {
        "search_limited": bool(found.get("search_limited")),
        "curation_truncated": bool(found.get("curation_truncated")),
        "candidate_count": found.get("candidate_count"),
        "part_limit_counts": {
            flag: sum(bool(part.get(flag, False)) for part in found.get("part_stats", []))
            for flag in flags
        },
        "part_stats": found.get("part_stats", []),
    }


def validate_method_coverage(
    rows: list[dict[str, Any]], case_ids: list[str], *, field: str = "case_id"
) -> None:
    expected = Counter((case_id, method) for case_id in case_ids for method in METHODS)
    observed = Counter((row.get(field), row.get("method")) for row in rows)
    if observed != expected:
        raise ValueError("selected method coverage differs from the frozen cohort")


def assert_single_part_selection_equivalence(
    case_id: str, outputs: dict[str, dict[str, Any]]
) -> None:
    """Prove the optional part prior reduces to closed selection for one Part."""
    closed = outputs["aligned_closed"].get("phrases")
    melody = outputs["aligned_melody"].get("phrases")
    if canonical_json(closed) != canonical_json(melody):
        raise ValueError(f"single-Part closed and melody selection differ: {case_id}")


def _theme_groups(rows: list[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[str, Any] = {}
    for method in METHODS:
        for view in THEME_VIEWS:
            selected = [row for row in rows if row["method"] == method and row["view"] == view]
            per_song = {}
            for song_id in SONG_IDS:
                song_rows = [row for row in selected if row["song_id"] == song_id]
                if len(song_rows) != len(ANNOTATORS):
                    raise ValueError("Theme annotation coverage differs from the frozen design")
                per_song[song_id] = {
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


def _theme_paired(groups: dict[str, Any]) -> dict[str, Any]:
    comparisons = {}
    for method in ("aligned_closed", "aligned_melody"):
        for view in THEME_VIEWS:
            baseline = groups[f"aligned_indexed/{view}"]["per_song_mean_over_annotators"]
            selected = groups[f"{method}/{view}"]["per_song_mean_over_annotators"]
            differences = {
                song: {
                    metric: selected[song][metric] - baseline[song][metric]
                    for metric in ("precision", "recall", "f1")
                }
                for song in SONG_IDS
            }
            comparisons[f"{method}_minus_aligned_indexed/{view}"] = {
                "per_song_mean_over_annotators": differences,
                "cluster_bootstrap_by_song": bootstrap_song_macro(
                    differences, samples=BOOTSTRAP_SAMPLES, seed=BOOTSTRAP_SEED
                ),
            }
    return comparisons


def _jku_groups(rows: list[dict[str, Any]]) -> dict[str, Any]:
    groups = {}
    for variant in ("monophonic", "polyphonic"):
        for method in METHODS:
            selected = [
                row for row in rows if row["variant"] == variant and row["method"] == method
            ]
            if len(selected) != len(EXPECTED_PIECES):
                raise ValueError("JKU work coverage differs from the frozen design")
            metric_names = tuple(selected[0]["metrics"])
            groups[f"{variant}/{method}"] = {
                "works": len(selected),
                "macro_metrics": {
                    metric: sum(row["metrics"][metric] for row in selected) / len(selected)
                    for metric in metric_names
                },
                "search_limited_works": sum(row["telemetry"]["search_limited"] for row in selected),
                "curation_truncated_works": sum(
                    row["telemetry"]["curation_truncated"] for row in selected
                ),
                "runtime_seconds": sum(row["runtime_seconds"] for row in selected),
            }
    return groups


def _jku_paired(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_key = {(row["case_id"], row["method"]): row for row in rows}
    output = {}
    for variant in ("monophonic", "polyphonic"):
        case_ids = [f"{piece}/{variant}" for piece in EXPECTED_PIECES]
        for method in ("aligned_closed", "aligned_melody"):
            metric_names = tuple(by_key[(case_ids[0], method)]["metrics"])
            output[f"{variant}/{method}_minus_aligned_indexed"] = {
                metric: sum(
                    by_key[(case_id, method)]["metrics"][metric]
                    - by_key[(case_id, "aligned_indexed")]["metrics"][metric]
                    for case_id in case_ids
                )
                / len(case_ids)
                for metric in metric_names
            }
    return output


def _prior_theme_regression(
    prior: Path,
    case_receipts: list[dict[str, Any]],
    config: dict[str, Any],
    runs: list[dict[str, Any]],
) -> dict[str, Any]:
    verification = verify_completed_experiment(prior)
    receipt = json.loads((prior / "experiment_receipt.json").read_text())
    snapshot = json.loads((prior / "source_snapshot.json").read_text())
    relevant = ("samuged/aligned.py", "samuged/aligned_indexed.py")
    code_equal = all(
        _source_hash(snapshot, name) == sha256(Path(name).read_bytes()).hexdigest()
        for name in relevant
    )
    config_equal = receipt.get("config", {}).get("detectors", {}).get("aligned_indexed") == config
    cohort_equal = receipt.get("case_cohort") == case_receipts
    prior_raw = json.loads((prior / "raw_results.json").read_text())
    prior_rows = {
        row["song_id"]: row
        for row in prior_raw["detector_runs"]
        if row["method"] == "aligned_indexed"
    }
    current_rows = {row["case_id"]: row for row in runs if row["method"] == "aligned_indexed"}
    comparable = code_equal and config_equal and cohort_equal and verification["status"] == "completed"
    mismatches = []
    if comparable:
        for song_id in SONG_IDS:
            for key in ("phrase_output_sha256", "predicted_source_note_indices"):
                if prior_rows[song_id][key] != current_rows[song_id][key]:
                    mismatches.append(f"{song_id}:{key}")
    return {
        "prior_path": prior.as_posix(),
        "prior_artifact_hashes": _hashes(
            prior,
            (
                "experiment_receipt.json",
                "source_snapshot.json",
                "raw_results.json",
                "aggregate.json",
                "completion_receipt.json",
            ),
        ),
        "completion_verified": verification["status"] == "completed",
        "detector_code_equal": code_equal,
        "config_equal": config_equal,
        "cohort_equal": cohort_equal,
        "comparable": comparable,
        "mismatches": mismatches,
        "passed": comparable and not mismatches,
    }


def _prior_jku_regression(
    prior: Path,
    case_receipts: list[dict[str, Any]],
    config: dict[str, Any],
    runs: list[dict[str, Any]],
) -> dict[str, Any]:
    receipt = verify_start_receipt(prior)
    snapshot = json.loads((prior / "source_snapshot.json").read_text())
    relevant = ("samuged/aligned.py", "samuged/aligned_indexed.py")
    code_equal = all(
        _source_hash(snapshot, name) == sha256(Path(name).read_bytes()).hexdigest()
        for name in relevant
    )
    config_equal = receipt.get("config", {}).get("detector_configs", {}).get("aligned_indexed") == config
    cohort_equal = receipt.get("case_cohort") == case_receipts
    raw_path = prior / "raw_results.json"
    aggregate = json.loads((prior / "aggregate.json").read_text())
    legacy_result_binding = aggregate.get("raw_results_sha256") == file_digest(raw_path)
    prior_raw = json.loads(raw_path.read_text())
    prior_rows = {(row["piece"] + "/" + row["variant"]): row for row in prior_raw["results"]}
    current_rows = {row["case_id"]: row for row in runs if row["method"] == "aligned_indexed"}
    comparable = code_equal and config_equal and cohort_equal and legacy_result_binding
    mismatches = []
    if comparable:
        for case_id in sorted(current_rows):
            for key in ("phrase_output_sha256", "prediction_output_sha256"):
                if prior_rows[case_id][key] != current_rows[case_id][key]:
                    mismatches.append(f"{case_id}:{key}")
    return {
        "prior_path": prior.as_posix(),
        "prior_artifact_hashes": _hashes(
            prior,
            ("experiment_receipt.json", "source_snapshot.json", "raw_results.json", "aggregate.json"),
        ),
        "legacy_start_receipt_verified": receipt["status"] == "started",
        "legacy_result_binding_verified": legacy_result_binding,
        "completion_receipt_available": (prior / "completion_receipt.json").is_file(),
        "detector_code_equal": code_equal,
        "config_equal": config_equal,
        "cohort_equal": cohort_equal,
        "comparable": comparable,
        "mismatches": mismatches,
        "passed": comparable and not mismatches,
    }


def run(
    theme_root: Path,
    theme_audit: Path,
    jku_root: Path,
    output: Path,
    *,
    theme_prior: Path,
    jku_prior: Path,
) -> dict[str, Any]:
    theme_root = theme_root.resolve(strict=True)
    theme_audit = theme_audit.resolve(strict=True)
    jku_root = jku_root.resolve(strict=True)
    theme_prior = theme_prior.resolve(strict=True)
    jku_prior = jku_prior.resolve(strict=True)
    cases, theme_inputs = load_cases(theme_root, theme_audit)
    for case in cases:
        _validate_theme_representation(case)
    theme_case_receipts = [case.receipt_metadata() for case in cases]

    jku_files = {
        path.relative_to(jku_root).as_posix(): file_digest(path)
        for path in sorted(jku_root.rglob("*"))
        if path.suffix in {".csv", ".krn", ".txt"} and path.is_file()
    }
    jku_case_receipts = []
    for piece in EXPECTED_PIECES:
        for variant in ("monophonic", "polyphonic"):
            prefix = f"groundTruth/{piece}/{variant}/"
            subset = {name: value for name, value in jku_files.items() if name.startswith(prefix)}
            jku_case_receipts.append({
                "case_id": f"jku:{piece}/{variant}",
                "dataset": "jku",
                "piece": piece,
                "variant": variant,
                "source_subset_sha256": digest(subset),
                "source_file_count": len(subset),
            })
    frozen_cases = [
        {"case_id": f"theme:{case['song_id']}", "dataset": "theme", **case}
        for case in theme_case_receipts
    ] + jku_case_receipts
    config = asdict(AlignedConfig(top_k=3))
    design = {
        "schema_version": VERSION,
        "datasets": {
            "theme": {
                "songs": list(SONG_IDS),
                "official_source": OFFICIAL_SOURCE,
                "input_receipts": theme_inputs,
                "role": "reused external POP909 development diagnostic",
            },
            "jku": {
                "works": list(EXPECTED_PIECES),
                "variants": ["monophonic", "polyphonic"],
                "source_files_sha256": sha256_json(jku_files),
                "role": "reused external classical development diagnostic",
            },
        },
        "methods": list(METHODS),
        "comparison": "fixed aligned-indexed shortlist with indexed, closed and optional part-prior selection",
        "theme_prediction_views": {
            "top1": "note union over verified occurrences of first selected family",
            "top3": "note union over verified occurrences of up to three selected families",
        },
        "jku_metric": METRIC_PROVENANCE,
        "bootstrap": {
            "scope": "ThemeTransformer paired selector differences only",
            "unit": "song retaining all three annotators",
            "songs": 6,
            "samples": BOOTSTRAP_SAMPLES,
            "seed": BOOTSTRAP_SEED,
        },
        "claim_boundary": (
            "reused development diagnostics; no fresh-heldout, corpus accuracy, role accuracy, "
            "perceptual identity or memorability claim"
        ),
        "prior_indexed_artifacts": {
            "theme": _hashes(
                theme_prior,
                ("experiment_receipt.json", "source_snapshot.json", "raw_results.json", "aggregate.json", "completion_receipt.json"),
            ),
            "jku": _hashes(
                jku_prior,
                ("experiment_receipt.json", "source_snapshot.json", "raw_results.json", "aggregate.json"),
            ),
        },
        "result_artifacts": ["raw_results.json", "aggregate.json"],
    }
    required_files = [
        "scripts/evaluate_selection_external.py",
        "samuged/evaluate_themes.py",
        "samuged/evaluate_jku.py",
        "samuged/aligned.py",
        "samuged/aligned_indexed.py",
        "samuged/closed_patterns.py",
        "samuged/part_ranking.py",
        "samuged/experiment.py",
        "pyproject.toml",
        "requirements-research.lock",
    ]
    receipt = prepare_experiment(
        output,
        design=design,
        config={"aligned_config": config, "methods": list(METHODS), "top_k": 3},
        cases=frozen_cases,
        required_files=required_files,
    )
    links = receipt_links(receipt)

    theme_runs: list[dict[str, Any]] = []
    theme_metrics: list[dict[str, Any]] = []
    for case in cases:
        outputs = {}
        for method in METHODS:
            started = time.monotonic()
            found = _detect(method, case.song, config)
            runtime = time.monotonic() - started
            outputs[method] = found
            predictions = {}
            for view, top_n in (("top1", 1), ("top3", 3)):
                predicted = prediction_indices(
                    case.song,
                    found["phrases"],
                    top_n=top_n,
                    onset_merge_beats=config["onset_merge_beats"],
                    require_source_verified=True,
                )
                predictions[view] = sorted(predicted)
                for annotator in ANNOTATORS:
                    theme_metrics.append({
                        "song_id": case.song_id,
                        "method": method,
                        "view": view,
                        "annotator": annotator,
                        "truth_positive_notes": len(case.labels[str(annotator)]),
                        "predicted_positive_notes": len(predicted),
                        "metrics": classification_metrics(case.labels[str(annotator)], predicted),
                    })
            theme_runs.append({
                "case_id": case.song_id,
                "song_id": case.song_id,
                "method": method,
                "runtime_seconds": runtime,
                "selected_phrases": found["phrases"],
                "phrase_output_sha256": sha256_json(found["phrases"]),
                "predicted_source_note_indices": predictions,
                "telemetry": _telemetry(found),
            })
        assert_single_part_selection_equivalence(case.song_id, outputs)
    validate_method_coverage(theme_runs, list(SONG_IDS))

    sanity = verify_published_examples(jku_root)
    if not sanity["passed"]:
        raise ValueError("mir_eval differs from the official published metric examples")
    jku_runs: list[dict[str, Any]] = []
    for piece in EXPECTED_PIECES:
        for variant in ("monophonic", "polyphonic"):
            song, reference, provenance = load_piece(jku_root / "groundTruth" / piece / variant)
            point_lookup = provenance.pop("_point_lookup")
            case_id = f"{piece}/{variant}"
            for method in METHODS:
                started = time.monotonic()
                found = _detect(method, song, config)
                runtime = time.monotonic() - started
                estimated = prediction_points(
                    song, found["phrases"], provenance["offset_beats"], point_lookup
                )
                jku_runs.append({
                    "case_id": case_id,
                    "piece": piece,
                    "variant": variant,
                    "method": method,
                    "runtime_seconds": runtime,
                    "selected_phrases": found["phrases"],
                    "phrase_output_sha256": sha256_json(found["phrases"]),
                    "prediction_patterns": estimated,
                    "prediction_output_sha256": sha256_json(estimated),
                    "metrics": jku_metrics(reference, estimated),
                    "telemetry": _telemetry(found),
                    **provenance,
                })
    jku_ids = [f"{piece}/{variant}" for piece in EXPECTED_PIECES for variant in ("monophonic", "polyphonic")]
    validate_method_coverage(jku_runs, jku_ids)

    theme_groups = _theme_groups(theme_metrics)
    jku_groups = _jku_groups(jku_runs)
    prior_regression = {
        "theme": _prior_theme_regression(theme_prior, theme_case_receipts, config, theme_runs),
        "jku": _prior_jku_regression(
            jku_prior,
            [
                {
                    **{key: value for key, value in row.items() if key not in {"dataset", "case_id"}},
                    "case_id": f"{row['piece']}/{row['variant']}",
                }
                for row in jku_case_receipts
            ],
            config,
            jku_runs,
        ),
    }
    raw = {
        "schema_version": VERSION,
        **links,
        "theme_cases": theme_case_receipts,
        "jku_cases": jku_case_receipts,
        "theme_runs": theme_runs,
        "theme_note_classification": theme_metrics,
        "jku_published_metric_examples": sanity,
        "jku_runs": jku_runs,
        "prior_indexed_regression": prior_regression,
    }
    _write_json(output / "raw_results.json", raw)
    aggregate = {
        "schema_version": VERSION,
        **links,
        "claim_boundary": design["claim_boundary"],
        "methods": list(METHODS),
        "theme": {
            "songs": len(SONG_IDS),
            "single_part_closed_equals_melody": all(
                next(row for row in theme_runs if row["case_id"] == song and row["method"] == "aligned_closed")["phrase_output_sha256"]
                == next(row for row in theme_runs if row["case_id"] == song and row["method"] == "aligned_melody")["phrase_output_sha256"]
                for song in SONG_IDS
            ),
            "method_views": theme_groups,
            "paired_selector_differences": _theme_paired(theme_groups),
            "selection_changes_from_indexed": {
                method: sum(
                    next(row for row in theme_runs if row["case_id"] == song and row["method"] == method)["phrase_output_sha256"]
                    != next(row for row in theme_runs if row["case_id"] == song and row["method"] == "aligned_indexed")["phrase_output_sha256"]
                    for song in SONG_IDS
                )
                for method in ("aligned_closed", "aligned_melody")
            },
        },
        "jku": {
            "works": len(EXPECTED_PIECES),
            "representations": len(jku_ids),
            "published_metric_examples_verified": sanity["passed"],
            "groups": jku_groups,
            "paired_selector_differences": _jku_paired(jku_runs),
            "selection_changes_from_indexed": {
                method: sum(
                    next(row for row in jku_runs if row["case_id"] == case_id and row["method"] == method)["phrase_output_sha256"]
                    != next(row for row in jku_runs if row["case_id"] == case_id and row["method"] == "aligned_indexed")["phrase_output_sha256"]
                    for case_id in jku_ids
                )
                for method in ("aligned_closed", "aligned_melody")
            },
        },
        "prior_indexed_regression": prior_regression,
        "total_runtime_seconds": sum(row["runtime_seconds"] for row in theme_runs + jku_runs),
    }
    _write_json(output / "aggregate.json", aggregate)
    complete_experiment(output)
    return aggregate


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--theme-root", type=Path, required=True)
    parser.add_argument("--theme-audit", type=Path, required=True)
    parser.add_argument("--jku-root", type=Path, required=True)
    parser.add_argument("--theme-prior", type=Path, required=True)
    parser.add_argument("--jku-prior", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    result = run(
        args.theme_root,
        args.theme_audit,
        args.jku_root,
        args.output,
        theme_prior=args.theme_prior,
        jku_prior=args.jku_prior,
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
