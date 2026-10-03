#!/usr/bin/env python3
"""Evaluate an optional note-structure part prior on frozen POP909 splits."""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict
from hashlib import sha256
import json
import math
from pathlib import Path
import random
import statistics
import time

from samuged.aligned import AlignedConfig
from samuged.aligned_indexed import detect_indexed_part
from samuged.closed_patterns import select_closed_candidates
from samuged.experiment import (
    canonical_json,
    complete_experiment,
    prepare_experiment,
    receipt_links,
    sha256_bytes,
    sha256_json,
    verify_completed_experiment,
)
from samuged.midi import MidiSong, Part, load_midi
from samuged.part_ranking import (
    PART_PRIOR_VERSION,
    PRESET_CONFIGS,
    PartPriorConfig,
    select_part_ranked_closed_candidates,
)


SCHEMA_VERSION = "samuged-part-ranking-evaluation-v1"
EXPECTED_UPSTREAM_SHA = "d83e6edba6872a704f5d3b8b32f5cb540088dae6"
EXCLUDED_IDS = ("065", "284", "310", "422", "449", "464")
TOP_K = 3
BOOTSTRAP_SAMPLES = 10_000
BOOTSTRAP_SEED = 20_261_003
RESULT_ARTIFACTS = (
    "aggregate.json",
    "frozen_rule.json",
    "heldout_predictions.json",
    "raw_results.json",
)
ROLE_NAMES = frozenset({"MELODY", "BRIDGE", "PIANO"})


def _write_json(path: Path, value: dict) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        + "\n"
    )


def _file_sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _load_selection(input_root: Path) -> tuple[dict, list[dict]]:
    path = input_root / "selection_manifest.json"
    manifest = json.loads(path.read_text())
    if manifest.get("schema_version") != "samuged-pop909-role-selection-v1":
        raise ValueError("unsupported POP909 selection manifest")
    if manifest.get("upstream", {}).get("commit_sha") != EXPECTED_UPSTREAM_SHA:
        raise ValueError("POP909 upstream commit differs from the frozen design")
    if tuple(manifest.get("excluded_song_ids", ())) != EXCLUDED_IDS:
        raise ValueError("POP909 exclusion set differs from the frozen design")
    rows = manifest.get("selected")
    if not isinstance(rows, list) or len(rows) != 180:
        raise ValueError("POP909 selection must contain 180 songs")
    if len({row.get("song_id") for row in rows}) != len(rows):
        raise ValueError("POP909 selection contains duplicate song IDs")
    counts = Counter(row.get("split") for row in rows)
    if counts != {"development": 60, "heldout": 120}:
        raise ValueError("POP909 selection must contain 60 development and 120 heldout songs")
    expected = sorted(rows, key=lambda row: (row["rank_sha256"], row["song_id"]))
    if rows != expected or [row["split"] for row in rows] != ["development"] * 60 + ["heldout"] * 120:
        raise ValueError("POP909 split order differs from the frozen rank order")
    return manifest, rows


def _cohort(input_root: Path, selected: list[dict]) -> list[dict]:
    rows = []
    midi_root = (input_root / "midi").resolve(strict=True)
    for selected_row in selected:
        song_id = selected_row["song_id"]
        path = (midi_root / f"{song_id}.mid").resolve(strict=True)
        if not path.is_relative_to(midi_root):
            raise ValueError("POP909 MIDI path escapes the frozen input root")
        rows.append(
            {
                "case_id": song_id,
                "split": selected_row["split"],
                "rank_sha256": selected_row["rank_sha256"],
                "source_path": path.relative_to(input_root.resolve()).as_posix(),
                "source_sha256": _file_sha256(path),
                "source_bytes": path.stat().st_size,
            }
        )
    return rows


def _blind_song(song: MidiSong) -> MidiSong:
    """Remove role-bearing metadata before detection and feature scoring."""
    return MidiSong(
        ticks_per_beat=song.ticks_per_beat,
        parts=[
            Part(
                index=part.index,
                track=0,
                channel=0,
                program=0,
                name="",
                is_drum=part.is_drum,
                notes=part.notes,
            )
            for part in song.parts
        ],
        tempos=song.tempos,
        meters=song.meters,
        warnings=song.warnings,
        metadata_repairs=song.metadata_repairs,
    )


def _candidate_digest(candidates: list[dict]) -> str:
    identity = [
        {
            "family_id": row["family_id"],
            "part_index": row["part_index"],
            "start_tick": row["start_tick"],
            "end_tick": row["end_tick"],
            "note_count": row["note_count"],
            "recurrence_score": row["recurrence_score"],
            "occurrences": [
                [item["start_tick"], item["end_tick"], item["note_index"], item["note_count"]]
                for item in row["occurrences"]
            ],
        }
        for row in candidates
    ]
    return sha256_json(identity)


def _phrase_summary(phrases: list[dict]) -> list[dict]:
    return [
        {
            "family_id": row["family_id"],
            "part_index": row["part_index"],
            "start_tick": row["start_tick"],
            "end_tick": row["end_tick"],
            "note_count": row["note_count"],
            "occurrence_count": row["occurrence_count"],
            "recurrence_score": row["recurrence_score"],
        }
        for row in phrases
    ]


def _detect_candidates(song: MidiSong, config: AlignedConfig) -> tuple[list[dict], list[dict], float]:
    started = time.monotonic()
    candidates: list[dict] = []
    stats: list[dict] = []
    for part in song.parts:
        found, audit = detect_indexed_part(song, part, config)
        candidates.extend(found)
        stats.append(audit)
    return candidates, stats, time.monotonic() - started


def _search_limited(stats: list[dict]) -> bool:
    keys = ("note_limit_reached", "window_limit_reached", "comparison_limit_reached", "group_limit_reached")
    return any(any(part[key] for key in keys) or part["saturated_seed_buckets"] for part in stats)


def _selection_row(phrases: list[dict]) -> dict:
    return {
        "phrases": _phrase_summary(phrases),
        "family_ids": [row["family_id"] for row in phrases],
        "part_indices": [row["part_index"] for row in phrases],
    }


def _run_case(
    case: dict,
    input_root: Path,
    detector_config: AlignedConfig,
    prior_configs: tuple[PartPriorConfig, ...],
) -> tuple[dict, MidiSong]:
    source_path = input_root / case["source_path"]
    if _file_sha256(source_path) != case["source_sha256"]:
        raise ValueError(f"source changed after cohort freeze: {case['case_id']}")
    parsed = load_midi(source_path)
    blind = _blind_song(parsed)
    candidates, stats, detection_elapsed = _detect_candidates(blind, detector_config)
    baseline_started = time.monotonic()
    baseline = select_closed_candidates(candidates, TOP_K)
    baseline_elapsed = time.monotonic() - baseline_started
    priors = {}
    for config in prior_configs:
        started = time.monotonic()
        phrases, evidence = select_part_ranked_closed_candidates(
            candidates, blind, config, top_k=TOP_K
        )
        priors[config.name] = {
            **_selection_row(phrases),
            "selection_elapsed_seconds": round(time.monotonic() - started, 8),
            "part_scores": evidence["part_scores"],
            "part_features": evidence["part_features"],
        }
    row = {
        **case,
        "candidate_count": len(candidates),
        "candidate_sha256": _candidate_digest(candidates),
        "candidate_part_indices": [row["part_index"] for row in candidates],
        "baseline": {
            **_selection_row(baseline),
            "selection_elapsed_seconds": round(baseline_elapsed, 8),
        },
        "priors": priors,
        "detection_elapsed_seconds": round(detection_elapsed, 6),
        "search_limited": _search_limited(stats),
        "curation_truncated": any(part["candidate_limit_reached"] for part in stats),
        "limits": [
            {
                "part_index": part["part_index"],
                "comparison_limit_reached": part["comparison_limit_reached"],
                "window_limit_reached": part["window_limit_reached"],
                "group_limit_reached": part["group_limit_reached"],
                "note_limit_reached": part["note_limit_reached"],
                "saturated_seed_buckets": part["saturated_seed_buckets"],
                "candidate_limit_reached": part["candidate_limit_reached"],
            }
            for part in stats
        ],
    }
    return row, parsed


def _role_map(song: MidiSong) -> dict[int, str]:
    roles = {part.index: part.name.strip().upper() for part in song.parts if not part.is_drum}
    if set(roles.values()) != ROLE_NAMES or len(roles) != 3:
        raise ValueError("official POP909 file must contain one MELODY, BRIDGE and PIANO part")
    return roles


def _label_selection(selection: dict, roles: dict[int, str]) -> dict:
    part_indices = selection["part_indices"]
    selected_roles = [roles[index] for index in part_indices]
    return {
        "roles": selected_roles,
        "top1_melody": bool(selected_roles and selected_roles[0] == "MELODY"),
        "top3_melody": "MELODY" in selected_roles,
    }


def fit_preset(dev_rows: list[dict]) -> tuple[str, list[dict]]:
    """Choose one declared preset using development role agreement only."""
    metrics = []
    for preset_index, config in enumerate(PRESET_CONFIGS):
        top1 = top3 = changed = 0
        for row in dev_rows:
            roles = row["role_map"]
            baseline = row["baseline"]
            prior = row["priors"][config.name]
            labels = _label_selection(prior, roles)
            top1 += labels["top1_melody"]
            top3 += labels["top3_melody"]
            changed += prior["family_ids"] != baseline["family_ids"]
        metrics.append(
            {
                "preset": config.name,
                "top1_melody": top1,
                "top3_melody": top3,
                "changed_songs": changed,
                "strength": config.strength,
                "preset_index": preset_index,
            }
        )
    selected = max(
        metrics,
        key=lambda row: (
            row["top1_melody"],
            row["top3_melody"],
            -row["changed_songs"],
            -row["strength"],
            -row["preset_index"],
        ),
    )
    return selected["preset"], metrics


def _score_rows(rows: list[dict], preset: str) -> list[dict]:
    scored = []
    for row in rows:
        roles = row["role_map"]
        baseline_labels = _label_selection(row["baseline"], roles)
        prior_labels = _label_selection(row["priors"][preset], roles)
        scored.append(
            {
                **row,
                "baseline_labels": baseline_labels,
                "prior_labels": prior_labels,
                "melody_candidate_available": any(
                    roles[index] == "MELODY" for index in row["candidate_part_indices"]
                ),
                "selection_changed": row["baseline"]["family_ids"] != row["priors"][preset]["family_ids"],
                "top1_part_changed": row["baseline"]["part_indices"][:1] != row["priors"][preset]["part_indices"][:1],
            }
        )
    return scored


def _paired_bootstrap(differences: list[int], seed: int) -> dict:
    if not differences:
        return {"difference": 0.0, "ci95": [0.0, 0.0], "samples": BOOTSTRAP_SAMPLES, "seed": seed}
    generator = random.Random(seed)
    size = len(differences)
    estimates = sorted(
        sum(differences[generator.randrange(size)] for _ in range(size)) / size
        for _ in range(BOOTSTRAP_SAMPLES)
    )
    return {
        "difference": round(statistics.mean(differences), 8),
        "ci95": [
            round(estimates[math.floor(0.025 * (BOOTSTRAP_SAMPLES - 1))], 8),
            round(estimates[math.ceil(0.975 * (BOOTSTRAP_SAMPLES - 1))], 8),
        ],
        "samples": BOOTSTRAP_SAMPLES,
        "seed": seed,
    }


def summarize_split(rows: list[dict], split: str) -> dict:
    selected = [row for row in rows if row["split"] == split]
    if not selected:
        raise ValueError(f"no rows for split: {split}")
    def count(method: str, metric: str) -> int:
        return sum(row[f"{method}_labels"][metric] for row in selected)
    baseline_top1 = count("baseline", "top1_melody")
    prior_top1 = count("prior", "top1_melody")
    baseline_top3 = count("baseline", "top3_melody")
    prior_top3 = count("prior", "top3_melody")
    return {
        "song_count": len(selected),
        "baseline": {
            "top1_melody_count": baseline_top1,
            "top1_melody_rate": round(baseline_top1 / len(selected), 8),
            "top3_melody_count": baseline_top3,
            "top3_melody_rate": round(baseline_top3 / len(selected), 8),
        },
        "part_prior": {
            "top1_melody_count": prior_top1,
            "top1_melody_rate": round(prior_top1 / len(selected), 8),
            "top3_melody_count": prior_top3,
            "top3_melody_rate": round(prior_top3 / len(selected), 8),
        },
        "paired_top1_difference": _paired_bootstrap(
            [int(row["prior_labels"]["top1_melody"]) - int(row["baseline_labels"]["top1_melody"]) for row in selected],
            BOOTSTRAP_SEED,
        ),
        "paired_top3_difference": _paired_bootstrap(
            [int(row["prior_labels"]["top3_melody"]) - int(row["baseline_labels"]["top3_melody"]) for row in selected],
            BOOTSTRAP_SEED + 1,
        ),
        "selection_changed_songs": sum(row["selection_changed"] for row in selected),
        "top1_part_changed_songs": sum(row["top1_part_changed"] for row in selected),
        "melody_candidate_available_songs": sum(row["melody_candidate_available"] for row in selected),
        "search_limited_songs": sum(row["search_limited"] for row in selected),
        "curation_truncated_songs": sum(row["curation_truncated"] for row in selected),
        "mean_candidate_count": round(statistics.mean(row["candidate_count"] for row in selected), 8),
        "mean_detection_seconds": round(statistics.mean(row["detection_elapsed_seconds"] for row in selected), 8),
        "mean_baseline_selection_seconds": round(statistics.mean(row["baseline"]["selection_elapsed_seconds"] for row in selected), 8),
        "mean_prior_selection_seconds": round(statistics.mean(row["selected_prior"]["selection_elapsed_seconds"] for row in selected), 8),
    }


def _validate_source_manifest_after_prediction_freeze(
    input_root: Path, cohort: list[dict]
) -> dict[str, dict]:
    manifest = json.loads((input_root / "source_manifest.json").read_text())
    if manifest.get("schema_version") != "samuged-pop909-role-v1":
        raise ValueError("unsupported POP909 source manifest")
    if manifest.get("upstream", {}).get("commit_sha") != EXPECTED_UPSTREAM_SHA:
        raise ValueError("source manifest upstream commit mismatch")
    records = manifest.get("records")
    if not isinstance(records, list) or len(records) != 180:
        raise ValueError("source manifest must contain 180 records")
    by_id = {row["song_id"]: row for row in records}
    if len(by_id) != 180:
        raise ValueError("source manifest contains duplicate song IDs")
    for case in cohort:
        source = by_id.get(case["case_id"])
        if source is None or source.get("source_sha256") != case["source_sha256"] or source.get("split") != case["split"]:
            raise ValueError(f"source manifest record mismatch: {case['case_id']}")
    return by_id


def run(input_root: Path, output: Path) -> dict:
    input_root = input_root.resolve(strict=True)
    selection, selected = _load_selection(input_root)
    cohort = _cohort(input_root, selected)
    selection_path = input_root / "selection_manifest.json"
    source_manifest_path = input_root / "source_manifest.json"
    download_receipt_path = input_root / "download_receipt.json"
    detector_config = AlignedConfig(top_k=TOP_K)
    design = {
        "study": "optional-source-structure-part-prior-v1",
        "algorithm": "aligned_closed candidate generation with optional full-shortlist part reranking",
        "candidate_invariance": "baseline and prior use the same aligned indexed candidate objects and top_k=3",
        "selection_scope": "rerank all shortlisted candidates before redundancy and closed exact extension selection",
        "development_fit": "choose one of the source-frozen presets by top1 MELODY agreement on 60 development songs, then top3 agreement, fewer changed songs, lower strength and declaration order",
        "heldout_boundary": "write and hash the selected rule and all 120 role-free heldout predictions before evaluator role mapping or heldout scoring",
        "label_meaning": "official POP909 MELODY versus BRIDGE versus PIANO part names assess part-choice agreement only",
        "claim_boundary": "no hook quality, human memorability, phrase accuracy or general corpus accuracy claim; accompaniment riffs can be valid sampling material",
        "result_artifacts": list(RESULT_ARTIFACTS),
        "upstream_commit": EXPECTED_UPSTREAM_SHA,
        "excluded_song_ids": list(EXCLUDED_IDS),
        "selection_manifest_sha256": _file_sha256(selection_path),
        "source_manifest_sha256": _file_sha256(source_manifest_path),
        "download_receipt_sha256": _file_sha256(download_receipt_path),
        "selection_namespace": selection["namespace"],
        "bootstrap": {"samples": BOOTSTRAP_SAMPLES, "seed": BOOTSTRAP_SEED, "unit": "song"},
    }
    config = {
        "detector": asdict(detector_config),
        "part_prior_version": PART_PRIOR_VERSION,
        "presets": [asdict(row) for row in PRESET_CONFIGS],
        "top_k": TOP_K,
    }
    receipt = prepare_experiment(
        output,
        design=design,
        config=config,
        cases=cohort,
        required_files=["scripts/evaluate_part_ranking.py", "samuged/part_ranking.py"],
    )
    links = receipt_links(receipt)

    dev_rows = []
    for case in (row for row in cohort if row["split"] == "development"):
        row, parsed = _run_case(case, input_root, detector_config, PRESET_CONFIGS)
        row["role_map"] = _role_map(parsed)
        dev_rows.append(row)
    selected_name, dev_fit = fit_preset(dev_rows)
    selected_config = next(row for row in PRESET_CONFIGS if row.name == selected_name)
    frozen_rule = {
        "schema_version": SCHEMA_VERSION,
        **links,
        "selected_preset": selected_name,
        "selected_config": asdict(selected_config),
        "development_fit": dev_fit,
        "development_song_count": len(dev_rows),
        "source_role_features": "timing and pitch only; names, tracks, channels and programs blanked before detection and scoring",
    }
    _write_json(output / "frozen_rule.json", frozen_rule)
    frozen_rule_sha256 = _file_sha256(output / "frozen_rule.json")

    heldout_rows = []
    for case in (row for row in cohort if row["split"] == "heldout"):
        row, _ = _run_case(case, input_root, detector_config, (selected_config,))
        heldout_rows.append(row)
    heldout_predictions = {
        "schema_version": SCHEMA_VERSION,
        **links,
        "frozen_rule_sha256": frozen_rule_sha256,
        "selected_preset": selected_name,
        "role_labels_included": False,
        "prediction_count": len(heldout_rows),
        "predictions": heldout_rows,
    }
    _write_json(output / "heldout_predictions.json", heldout_predictions)
    heldout_predictions_sha256 = _file_sha256(output / "heldout_predictions.json")

    # Role-bearing metadata is dereferenced only after predictions are frozen.
    source_records = _validate_source_manifest_after_prediction_freeze(input_root, cohort)
    for row in heldout_rows:
        parsed = load_midi(input_root / row["source_path"])
        row["role_map"] = _role_map(parsed)
        source_parts = source_records[row["case_id"]].get("parts", [])
        manifest_roles = {part["part_index"]: part["name"].strip().upper() for part in source_parts if not part["is_drum"]}
        if manifest_roles != row["role_map"]:
            raise ValueError(f"source role metadata mismatch: {row['case_id']}")

    scored = _score_rows(dev_rows + heldout_rows, selected_name)
    for row in scored:
        row["selected_prior"] = row["priors"][selected_name]
        del row["priors"]
    development = summarize_split(scored, "development")
    heldout = summarize_split(scored, "heldout")
    raw_results = {
        "schema_version": SCHEMA_VERSION,
        **links,
        "frozen_rule_sha256": frozen_rule_sha256,
        "heldout_predictions_sha256": heldout_predictions_sha256,
        "selected_preset": selected_name,
        "rows": scored,
    }
    aggregate = {
        "schema_version": SCHEMA_VERSION,
        **links,
        "frozen_rule_sha256": frozen_rule_sha256,
        "heldout_predictions_sha256": heldout_predictions_sha256,
        "selected_preset": selected_name,
        "selected_config": asdict(selected_config),
        "development": development,
        "heldout": heldout,
        "total_detection_seconds": round(sum(row["detection_elapsed_seconds"] for row in scored), 6),
        "source_manifest_validated_after_prediction_freeze": True,
        "role_free_prediction_count": len(heldout_rows),
        "decision": "experimental optional prior; no default promotion is implied by part-role agreement",
        "claim_boundary": design["claim_boundary"],
    }
    _write_json(output / "raw_results.json", raw_results)
    _write_json(output / "aggregate.json", aggregate)
    complete_experiment(output)
    verify_completed_experiment(output)
    return aggregate


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("research_local/external/pop909_role_v01"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("research_local/part_ranking_v01"),
    )
    args = parser.parse_args()
    aggregate = run(args.input, args.output)
    print(canonical_json(aggregate))


if __name__ == "__main__":
    main()
