#!/usr/bin/env python3
"""Replay three frozen reference to indexed no-match regressions.

This is a bounded diagnostic.  It does not alter detector configuration or
fall back from the indexed detector when candidate generation misses a pair.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path
import sys
import time
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from samuged import aligned
from samuged.aligned_indexed import extract_indexed
from samuged.experiment import complete_experiment, prepare_experiment, receipt_links, sha256_json
from samuged.midi import load_midi
from samuged.phrases import Config, Window, match, skyline, window


VERSION = "samuged-no-match-regression-audit-v1"
SOURCE_IDS = (
    "505a593b4bb78fb0913f503e",
    "7f008f441e679da594f68111",
    "9f60267f5b12ba99c1d0c9a9",
)
REQUIRED_FILES = (
    "scripts/audit_no_match_regressions.py",
    "samuged/aligned.py",
    "samuged/aligned_indexed.py",
    "samuged/experiment.py",
    "samuged/midi.py",
    "samuged/phrases.py",
    "samuged/metadata_recovery.py",
    "pyproject.toml",
    "requirements-research.lock",
)


def _hash(data: bytes) -> str:
    return sha256(data).hexdigest()


def _read_json_stable(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    before = path.read_bytes()
    value = json.loads(before)
    after = path.read_bytes()
    if before != after:
        raise RuntimeError(f"input changed while read: {path}")
    return value, {"path": str(path.resolve()), "sha256": _hash(before), "bytes": len(before)}


def _file_receipt(path: Path) -> dict[str, Any]:
    data = path.read_bytes()
    return {"path": str(path.resolve()), "sha256": _hash(data), "bytes": len(data)}


def _atomic_json(path: Path, value: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _alignment_dict(result: aligned.Alignment | None) -> dict[str, Any] | None:
    return asdict(result) if result is not None else None


def pair_diagnostics(left: Window, right: Window, cfg: aligned.AlignedConfig) -> dict[str, Any]:
    """Evaluate the final verifier and every ordered indexed precheck."""
    allowed = aligned._allowed_edits(len(left.notes), len(right.notes), cfg)
    left_keys = set(aligned._seed_keys(left, cfg))
    right_keys = set(aligned._seed_keys(right, cfg))
    common = left_keys & right_keys
    # Diagnostic projections identify which composite seed component prevents
    # a collision.  They are not used to generate or accept candidates.
    def without_span(key: tuple) -> tuple:
        return key[:-1]

    def pitch_rhythm_only(key: tuple) -> tuple:
        return key[:3] if key[0] == "single" else key[:5]

    projected = {
        "without_span_bucket": len(
            {without_span(key) for key in left_keys}
            & {without_span(key) for key in right_keys}
        ),
        "pitch_and_rhythm_descriptors_only": len(
            {pitch_rhythm_only(key) for key in left_keys}
            & {pitch_rhythm_only(key) for key in right_keys}
        ),
    }
    timing_pairs = aligned._timing_alignment(left, right, allowed, cfg.timing_tolerance)
    pitch_feasible = bool(
        timing_pairs is not None
        and aligned._pitch_feasible(left, right, timing_pairs, allowed)
    )
    anchor_result = (
        aligned._anchor_alignment(left, right, timing_pairs, cfg)
        if timing_pairs is not None and pitch_feasible
        else None
    )
    shifts = aligned._shift_candidates(left, right, allowed, cfg.max_shift_candidates)
    direct = aligned._align_with_shifts(left, right, cfg, shifts)
    return {
        "left": _window_identity(left),
        "right": _window_identity(right),
        "allowed_edits": allowed,
        "nonoverlap": left.end <= right.start or right.end <= left.start,
        "length_difference": abs(len(left.notes) - len(right.notes)),
        "terminal_onset_error_beats": round(abs(left.onsets[-1] - right.onsets[-1]), 8),
        "terminal_timing_pass": abs(left.onsets[-1] - right.onsets[-1]) <= cfg.timing_tolerance,
        "full_span_beats": [
            round(max(onset + duration for onset, duration in zip(candidate.onsets, candidate.durations)), 8)
            for candidate in (left, right)
        ],
        "left_seed_key_count": len(left_keys),
        "right_seed_key_count": len(right_keys),
        "shared_seed_key_count": len(common),
        "shared_seed_key_types": dict(sorted(Counter(key[0] for key in common).items())),
        "shared_seed_projection_counts": projected,
        "minimum_seed_support": cfg.min_seed_support,
        "seed_support_pass": len(common) >= cfg.min_seed_support,
        "timing_pairs": [list(pair) for pair in timing_pairs] if timing_pairs is not None else None,
        "timing_feasibility_pass": timing_pairs is not None,
        "pitch_feasibility_pass": pitch_feasible,
        "anchor_alignment": _alignment_dict(anchor_result),
        "shift_candidates": shifts,
        "direct_alignment": _alignment_dict(direct),
    }


def _window_identity(candidate: Window) -> dict[str, Any]:
    return {
        "note_index": candidate.index,
        "note_count": len(candidate.notes),
        "start_tick": candidate.start,
        "end_tick": candidate.end,
        "pitches": list(candidate.pitches),
        "onsets_beats": [round(value, 8) for value in candidate.onsets],
        "durations_beats": [round(value, 8) for value in candidate.durations],
    }


def _trace_index_generation(
    song, part, cfg: aligned.AlignedConfig, targets: set[tuple[int, int]]
) -> dict[str, Any]:
    """Replay only indexed candidate generation and record target decisions.

    The aggregate counters are checked against the frozen indexed record.  This
    independent trace intentionally stops before final group verification.
    """
    stream = skyline(part, song.ticks_per_beat, cfg.onset_merge_beats)
    groups: list[list[Window]] = []
    seed_index: dict[tuple, list[int]] = defaultdict(list)
    exact_index: dict[tuple, int] = {}
    saturated: set[tuple] = set()
    events: list[dict[str, Any]] = []
    stats = Counter()
    stop = False
    for count in range(cfg.max_notes, cfg.min_notes - 1, -1):
        if count > len(stream):
            continue
        for start in range(len(stream) - count + 1):
            if stats["windows_considered"] >= cfg.max_windows:
                stats["window_limit_reached"] = 1
                stop = True
                break
            stats["windows_considered"] += 1
            candidate = aligned._valid_window(stream, start, count, song, cfg)
            if candidate is None:
                continue
            stats["windows"] += 1
            target = (candidate.index, len(candidate.notes)) in targets
            event: dict[str, Any] | None = {
                "candidate": _window_identity(candidate), "evaluations": []
            } if target else None
            exact_key = aligned._exact_key(candidate)
            exact_group = exact_index.get(exact_key)
            if exact_group is not None:
                groups[exact_group].append(candidate)
                stats["exact_signature_hits"] += 1
                if event is not None:
                    event.update(action="exact_group", group_index=exact_group)
                    events.append(event)
                continue
            query_keys = aligned._seed_keys(candidate, cfg)
            postings = [seed_index.get(key, ()) for key in query_keys]
            group_votes = Counter(group for posting in postings for group in posting)
            stats["seed_support_rejections"] += sum(
                votes < cfg.min_seed_support for votes in group_votes.values()
            )
            candidate_groups = sorted(
                group for group, votes in group_votes.items() if votes >= cfg.min_seed_support
            )
            if event is not None:
                event.update(
                    query_key_count=len(query_keys),
                    candidate_group_count=len(candidate_groups),
                    group_votes=[
                        {"group_index": group, "votes": votes}
                        for group, votes in sorted(group_votes.items())
                    ],
                )
            best: tuple[float, int] | None = None
            for group_index in candidate_groups:
                stats["proposed_pairs"] += 1
                representative = groups[group_index][0]
                check: dict[str, Any] = {
                    "group_index": group_index,
                    "votes": group_votes[group_index],
                    "representative": _window_identity(representative),
                }
                if not (candidate.end <= representative.start or representative.end <= candidate.start):
                    stats["overlap_rejections"] += 1
                    check["decision"] = "overlap_rejection"
                else:
                    allowed = aligned._allowed_edits(len(representative.notes), len(candidate.notes), cfg)
                    if abs(len(representative.notes) - len(candidate.notes)) > allowed:
                        stats["length_rejections"] += 1
                        check["decision"] = "length_rejection"
                    elif abs(representative.onsets[-1] - candidate.onsets[-1]) > cfg.timing_tolerance:
                        stats["terminal_timing_rejections"] += 1
                        check["decision"] = "terminal_timing_rejection"
                    else:
                        pairs = aligned._timing_alignment(
                            representative, candidate, allowed, cfg.timing_tolerance
                        )
                        if pairs is None:
                            stats["timing_feasibility_rejections"] += 1
                            check["decision"] = "timing_feasibility_rejection"
                        elif not aligned._pitch_feasible(representative, candidate, pairs, allowed):
                            stats["pitch_feasibility_rejections"] += 1
                            check["decision"] = "pitch_feasibility_rejection"
                        else:
                            result = aligned._anchor_alignment(representative, candidate, pairs, cfg)
                            if result is None:
                                stats["anchor_alignment_rejections"] += 1
                                check["decision"] = "anchor_alignment_rejection"
                            else:
                                stats["anchor_alignment_hits"] += 1
                                check["decision"] = "accepted"
                                check["alignment"] = _alignment_dict(result)
                                if best is None or result.similarity > best[0]:
                                    best = (result.similarity, group_index)
                if event is not None:
                    event["evaluations"].append(check)
            if best is None:
                if len(groups) >= cfg.max_groups:
                    stats["group_limit_reached"] = 1
                    stop = True
                    break
                group_index = len(groups)
                groups.append([candidate])
                exact_index[exact_key] = group_index
                for key in query_keys:
                    bucket = seed_index[key]
                    if len(bucket) < cfg.max_bucket:
                        bucket.append(group_index)
                    else:
                        saturated.add(key)
                action = "new_group"
            else:
                group_index = best[1]
                groups[group_index].append(candidate)
                action = "grouped"
            if event is not None:
                event.update(action=action, group_index=group_index)
                events.append(event)
        if stop:
            break
    stats["groups"] = len(groups)
    stats["saturated_seed_buckets"] = len(saturated)
    return {"stats": dict(sorted(stats.items())), "target_events": events}


TRACE_COUNTERS = (
    "windows_considered", "windows", "groups", "exact_signature_hits",
    "seed_support_rejections", "proposed_pairs", "overlap_rejections",
    "length_rejections", "terminal_timing_rejections",
    "timing_feasibility_rejections", "pitch_feasibility_rejections",
    "anchor_alignment_hits", "anchor_alignment_rejections",
    "saturated_seed_buckets",
)


def _choose_phrase(record: dict[str, Any]) -> dict[str, Any]:
    phrases = [row for row in record.get("phrases", []) if row.get("kind") == "melodic"]
    if len(phrases) != 1 or phrases[0].get("occurrence_count") != 2:
        raise ValueError(f"expected one two-occurrence melodic phrase: {record.get('source_id')}")
    return phrases[0]


def _classify(pair: dict[str, Any], trace_event: dict[str, Any]) -> tuple[str, str]:
    if pair["direct_alignment"] is None:
        return "intentional_rule_difference", "final_aligned_verifier_rejects_reference_pair"
    if not pair["seed_support_pass"]:
        return "candidate_generation_recall_defect", "shared_seed_votes_below_minimum"
    rejected = {row["decision"] for row in trace_event.get("evaluations", [])}
    if trace_event.get("action") == "new_group":
        if "anchor_alignment_rejection" in rejected:
            return "candidate_generation_recall_defect", "anchor_precheck_rejects_dp_valid_pair"
        return "candidate_generation_recall_defect", "grouping_path_does_not_propose_dp_valid_pair"
    return "other", "target_pair_grouped_but_no_final_repeat"


def run(args: argparse.Namespace) -> dict[str, Any]:
    reference = args.reference.resolve(strict=True)
    indexed = args.indexed.resolve(strict=True)
    comparison = args.comparison.resolve(strict=True)
    source_root = args.source_root.resolve(strict=True)
    output = args.output.resolve()

    comparison_value, comparison_receipt = _read_json_stable(comparison)
    selected_changes = {
        row["source_id"]: row
        for row in comparison_value.get("source_outcome_changes", [])
        if row.get("source_id") in SOURCE_IDS
    }
    if set(selected_changes) != set(SOURCE_IDS):
        raise ValueError("comparison does not contain all three named outcome regressions")

    inventory: list[dict[str, Any]] = [comparison_receipt]
    for dataset, expected_algorithm in (
        (reference, "reference"),
        (indexed, "aligned_indexed"),
    ):
        audit, audit_receipt = _read_json_stable(dataset / "audit.json")
        build, build_receipt = _read_json_stable(dataset / "build_config.json")
        if audit.get("passed") is not True or audit.get("failures"):
            raise ValueError(f"dataset audit is not clean: {dataset}")
        if build.get("algorithm") != expected_algorithm:
            raise ValueError(f"unexpected dataset algorithm: {dataset}")
        inventory.extend((audit_receipt, build_receipt))
    comparison_root = comparison.parent
    for name in ("experiment_receipt.json", "completion_receipt.json"):
        receipt_path = comparison_root / name
        if receipt_path.is_file():
            inventory.append(_file_receipt(receipt_path))
    frozen: list[dict[str, Any]] = []
    for source_id in SOURCE_IDS:
        reference_record, reference_receipt = _read_json_stable(reference / "records" / f"{source_id}.json")
        indexed_record, indexed_receipt = _read_json_stable(indexed / "records" / f"{source_id}.json")
        phrase = _choose_phrase(reference_record)
        source_path = source_root / reference_record["source_path"]
        source_receipt = _file_receipt(source_path)
        if source_receipt["sha256"] != reference_record["source_sha256"]:
            raise ValueError(f"source hash mismatch: {source_id}")
        if reference_record["outcome"] != "matched" or indexed_record["outcome"] != "no_match":
            raise ValueError(f"unexpected frozen outcome pair: {source_id}")
        inventory.extend((reference_receipt, indexed_receipt, source_receipt))
        frozen.append({
            "source_id": source_id,
            "source_path": reference_record["source_path"],
            "source_sha256": source_receipt["sha256"],
            "reference_record_sha256": reference_receipt["sha256"],
            "indexed_record_sha256": indexed_receipt["sha256"],
            "comparison_row_sha256": sha256_json(selected_changes[source_id]),
            "reference_phrase_sha256": sha256_json(phrase),
            "reference_occurrences": phrase["occurrences"],
        })

    design = {
        "version": VERSION,
        "purpose": "causal replay of three frozen reference to indexed no-match regressions",
        "source_ids": list(SOURCE_IDS),
        "detectors": ["reference_pair_verifier", "aligned", "aligned_indexed"],
        "result_artifacts": ["aggregate.json", "input_manifest.json", "raw_results.json"],
        "claim_boundary": "candidate recall diagnosis on three named corpus files, not accuracy or musical quality",
    }
    config = {
        "reconstruct_reference_windows_from_saved_note_indices": True,
        "replay_unindexed_full_detector": True,
        "replay_indexed_full_detector": True,
        "recover_invalid_keys": True,
        "require_exact_input_hash_recheck": True,
    }
    receipt = prepare_experiment(
        output, design=design, config=config, cases=frozen, required_files=REQUIRED_FILES
    )
    links = receipt_links(receipt)
    _atomic_json(output / "input_manifest.json", {
        **links, "version": VERSION, "files": inventory, "cases": frozen,
    })

    started = time.monotonic()
    rows = []
    for case in frozen:
        source_id = case["source_id"]
        reference_record = json.loads((reference / "records" / f"{source_id}.json").read_text())
        indexed_record = json.loads((indexed / "records" / f"{source_id}.json").read_text())
        phrase = _choose_phrase(reference_record)
        song = load_midi(source_root / case["source_path"], recover_invalid_keys=True)
        if song.ticks_per_beat != reference_record["ticks_per_beat"]:
            raise ValueError(f"PPQ mismatch: {source_id}")
        part = song.parts[phrase["part_index"]]
        stream = skyline(part, song.ticks_per_beat, phrase["config"]["onset_merge_beats"] if "config" in phrase else reference_record["config"]["onset_merge_beats"])
        occurrences = phrase["occurrences"]
        reconstructed = [window(stream, occurrence["note_index"], phrase["note_count"], song.ticks_per_beat) for occurrence in occurrences]
        for expected, actual in zip(occurrences, reconstructed):
            if (actual.start, actual.end) != (expected["start_tick"], expected["end_tick"]):
                raise ValueError(f"saved occurrence coordinates do not reconstruct: {source_id}")
        if list(reconstructed[0].pitches) != phrase["pitches"]:
            raise ValueError(f"saved prototype pitches do not reconstruct: {source_id}")

        aligned_cfg = aligned.AlignedConfig(**indexed_record["config"])
        reference_cfg = Config(**reference_record["config"])
        pair = pair_diagnostics(reconstructed[0], reconstructed[1], aligned_cfg)
        reference_direct = match(reconstructed[0], reconstructed[1], reference_cfg)
        targets = {(item.index, len(item.notes)) for item in reconstructed}
        trace = _trace_index_generation(song, part, aligned_cfg, targets)
        frozen_stats = indexed_record["part_stats"][phrase["part_index"]]
        counter_check = {
            key: {"trace": trace["stats"].get(key, 0), "frozen": frozen_stats.get(key, 0)}
            for key in TRACE_COUNTERS
        }
        if any(value["trace"] != value["frozen"] for value in counter_check.values()):
            raise RuntimeError(f"independent indexed generation trace differs from frozen counters: {source_id}")
        second_event = next(
            event for event in trace["target_events"]
            if event["candidate"]["note_index"] == reconstructed[1].index
            and event["candidate"]["note_count"] == len(reconstructed[1].notes)
        )
        classification, cause = _classify(pair, second_event)

        unindexed = aligned.extract_aligned(song, aligned_cfg)
        indexed_replay = extract_indexed(song, aligned_cfg)
        if indexed_replay["phrases"] != indexed_record["phrases"]:
            raise RuntimeError(f"indexed phrase replay differs from frozen record: {source_id}")
        if indexed_replay["part_stats"] != indexed_record["part_stats"]:
            raise RuntimeError(f"indexed stats replay differs from frozen record: {source_id}")
        rows.append({
            "source_id": source_id,
            "source_path": case["source_path"],
            "source_sha256": case["source_sha256"],
            "reference_phrase": phrase,
            "reference_pair_verification": {
                "accepted": reference_direct is not None,
                "result": list(reference_direct) if reference_direct is not None else None,
            },
            "aligned_pair_diagnostics": pair,
            "indexed_generation_trace": trace,
            "trace_counter_check": counter_check,
            "unindexed_replay": {
                "phrase_count": len(unindexed["phrases"]),
                "candidate_count": unindexed["candidate_count"],
                "search_limited": unindexed["search_limited"],
                "part_stats": unindexed["part_stats"],
                "phrases": unindexed["phrases"],
            },
            "indexed_replay": {
                "phrase_count": len(indexed_replay["phrases"]),
                "candidate_count": indexed_replay["candidate_count"],
                "search_limited": indexed_replay["search_limited"],
                "frozen_output_exact_match": True,
            },
            "classification": classification,
            "cause": cause,
        })

    # Bind the exact input bytes again after all detector calls.
    for entry in inventory:
        path = Path(entry["path"])
        current = _file_receipt(path)
        if (current["sha256"], current["bytes"]) != (entry["sha256"], entry["bytes"]):
            raise RuntimeError(f"input changed during experiment: {path}")

    counts = Counter(row["classification"] for row in rows)
    aggregate = {
        **links,
        "version": VERSION,
        "case_count": len(rows),
        "classification_counts": dict(sorted(counts.items())),
        "reference_pair_acceptances": sum(row["reference_pair_verification"]["accepted"] for row in rows),
        "aligned_direct_acceptances": sum(row["aligned_pair_diagnostics"]["direct_alignment"] is not None for row in rows),
        "seed_support_passes": sum(row["aligned_pair_diagnostics"]["seed_support_pass"] for row in rows),
        "unindexed_no_match_cases": sum(row["unindexed_replay"]["phrase_count"] == 0 for row in rows),
        "indexed_no_match_cases": sum(row["indexed_replay"]["phrase_count"] == 0 for row in rows),
        "follow_up_warranted": any(row["classification"] == "candidate_generation_recall_defect" for row in rows),
        "elapsed_seconds": round(time.monotonic() - started, 6),
        "claim_boundary": design["claim_boundary"],
    }
    _atomic_json(output / "raw_results.json", {**links, "version": VERSION, "rows": rows})
    _atomic_json(output / "aggregate.json", aggregate)
    complete_experiment(output)
    return aggregate


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, default=ROOT / "research_local/lakh_phrases_v03")
    parser.add_argument("--indexed", type=Path, default=ROOT / "research_local/lakh_aligned_indexed_v01")
    parser.add_argument("--comparison", type=Path, default=ROOT / "research_local/indexed_full_comparison_v02/raw_results.json")
    parser.add_argument("--source-root", type=Path, default=ROOT / "datasets/Lakh MIDI Clean")
    parser.add_argument("--output", type=Path, default=ROOT / "research_local/no_match_regressions_v01")
    return parser.parse_args(argv)


if __name__ == "__main__":
    print(json.dumps(run(parse_args()), sort_keys=True))
