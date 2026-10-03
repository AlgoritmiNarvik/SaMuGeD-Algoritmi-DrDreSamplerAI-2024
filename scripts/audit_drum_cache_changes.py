"""Independently audit changed drum cache selections against source MIDI.

This report is a semantic verification of the 16 changed parsed files in a
completed baseline/candidate cache comparison. It does not rerun either
detector and it does not make a musical quality or promotion claim.
"""
from __future__ import annotations

import argparse
from collections import Counter
from fractions import Fraction
from hashlib import sha256
import json
import math
from pathlib import Path, PurePosixPath
from typing import Any

from samuged.dataset import atomic_json, file_digest
from samuged.drum_oracle import ORACLE_VERSION, enumerate_windows, verify_pair
from samuged.experiment import (
    complete_experiment,
    prepare_experiment,
    receipt_links,
    verify_completed_experiment,
)
from samuged.midi import load_midi


EXPECTED_CHANGED_FILES = 16
EXPECTED_PARSED_ROWS = 16_967
ORACLE_CONFIG = {
    "bar_counts": [1, 2, 4],
    "min_hits": 8,
    "min_pitches": 2,
    "timing_tolerance_beats": [1, 12],
    "hit_error_fraction": [1, 10],
    "direct_edge_rule": "prototype and occurrence must be distinct nonoverlapping oracle windows with admissible pitch-onset edits",
    "canonical_rule": "window pitches, relative onset fractions, durations and velocities must match source drum ensemble",
}


def _fraction_payload(window: Any, ppq: int) -> dict[str, Any]:
    span = Fraction(window.end - window.start, ppq)
    hits = []
    for note in window.notes:
        onset = Fraction(note.start - window.start, ppq)
        hits.append((note.pitch, onset.numerator, onset.denominator))
    return {"window_beats": (span.numerator, span.denominator), "hits": hits}


def _family_id(window: Any, ppq: int) -> str:
    payload = json.dumps(_fraction_payload(window, ppq), sort_keys=True, separators=(",", ":"))
    return sha256(payload.encode("utf-8")).hexdigest()


def _round(value: Fraction | float, places: int = 8) -> float:
    return round(float(value), places)


def _identity(phrase: dict[str, Any]) -> tuple[int, int, int, int, int]:
    names = ("bar_count", "meter_numerator", "meter_denominator", "start_tick", "end_tick")
    values = tuple(phrase.get(name) for name in names)
    if any(type(value) is not int for value in values):
        raise ValueError("phrase geometry fields must be integers")
    return values  # type: ignore[return-value]


def _occurrence_identity(phrase: dict[str, Any], occurrence: dict[str, Any]) -> tuple[int, int, int, int, int]:
    names = ("bar_count", "meter_numerator", "meter_denominator")
    geometry = tuple(phrase.get(name) for name in names)
    start, end = occurrence.get("start_tick"), occurrence.get("end_tick")
    if any(type(value) is not int for value in (*geometry, start, end)):
        raise ValueError("occurrence geometry fields must be integers")
    return (*geometry, start, end)  # type: ignore[return-value]


def _coordinates(phrase: dict[str, Any]) -> list[tuple[int, int]]:
    return [(item["start_tick"], item["end_tick"]) for item in phrase["occurrences"]]


def _canonical_fields(phrase: dict[str, Any], window: Any, ppq: int) -> None:
    notes = window.notes
    expected = {
        "kind": "percussion",
        "channel": 9,
        "part_index": -1,
        "bar_count": window.bar_count,
        "meter_numerator": window.numerator,
        "meter_denominator": window.denominator,
        "start_tick": window.start,
        "end_tick": window.end,
        "family_id": _family_id(window, ppq),
        "note_count": len(notes),
        "duration_beats": _round(Fraction(window.end - window.start, ppq)),
        "pitches": [note.pitch for note in notes],
        "onsets_beats": [_round(Fraction(note.start - window.start, ppq)) for note in notes],
        "durations_beats": [_round(Fraction(note.end - note.start, ppq)) for note in notes],
        "velocities": [note.velocity for note in notes],
        "duration_policy": "clip_at_next_same_pitch_hit",
    }
    for key, value in expected.items():
        if phrase.get(key) != value:
            raise ValueError(f"canonical {key} mismatch")


def _validate_phrase(
    phrase: dict[str, Any],
    windows: dict[tuple[int, ...], Any],
    ppq: int,
    source_metadata: tuple[list[int], list[int], list[int]] | None = None,
) -> dict[str, Any]:
    """Validate one saved phrase and all of its direct prototype edges."""
    if not isinstance(phrase, dict):
        raise ValueError("phrase must be an object")
    geometry = _identity(phrase)
    prototype = windows.get(geometry)
    if prototype is None:
        raise ValueError("prototype coordinates are not an oracle window")
    _canonical_fields(phrase, prototype, ppq)
    if not isinstance(phrase.get("source_part_indices"), list):
        raise ValueError("source part indices are missing")
    if not isinstance(phrase.get("source_tracks"), list):
        raise ValueError("source tracks are missing")
    if not isinstance(phrase.get("kit_programs"), list):
        raise ValueError("kit programs are missing")
    if source_metadata is not None:
        for key, value in zip(
            ("source_part_indices", "source_tracks", "kit_programs"), source_metadata
        ):
            if phrase.get(key) != value:
                raise ValueError(f"source metadata {key} mismatch")
    occurrences = phrase.get("occurrences")
    if not isinstance(occurrences, list) or len(occurrences) < 2:
        raise ValueError("phrase must contain at least two occurrences")
    if phrase.get("occurrence_count") != len(occurrences):
        raise ValueError("occurrence count mismatch")
    seen: set[tuple[int, int]] = set()
    direct_edges = []
    prototype_coordinates = (prototype.start, prototype.end)
    self_count = 0
    previous_start = -1
    previous_end = -1
    for occurrence in occurrences:
        if not isinstance(occurrence, dict):
            raise ValueError("occurrence must be an object")
        identity = _occurrence_identity(phrase, occurrence)
        window = windows.get(identity)
        if window is None:
            raise ValueError("occurrence coordinates are not oracle windows")
        start, end = identity[-2:]
        if (start, end) in seen:
            raise ValueError("duplicate occurrence coordinates")
        seen.add((start, end))
        if start < previous_start or (start == previous_start and end < previous_end):
            raise ValueError("occurrences are not sorted")
        previous_start, previous_end = start, end
        similarity = occurrence.get("similarity")
        if isinstance(similarity, bool) or not isinstance(similarity, (int, float)):
            raise ValueError("occurrence similarity is not numeric")
        if not math.isfinite(similarity) or not 0 <= similarity <= 1:
            raise ValueError("occurrence similarity is outside [0, 1]")
        if occurrence.get("transpose_semitones") != 0:
            raise ValueError("percussion occurrence has nonzero transpose")
        if (start, end) == prototype_coordinates:
            self_count += 1
            continue
        checked = verify_pair(prototype, window, ppq)
        if not checked.admissible:
            raise ValueError(f"direct edge is inadmissible: {checked.reason}")
        direct_edges.append({
            "prototype": [prototype.start, prototype.end],
            "occurrence": [window.start, window.end],
            "similarity": similarity,
            "matched_hits": checked.matched_hits,
            "edit_count": checked.total_edits,
            "allowed_edits": checked.allowed_edits,
            "oracle_reason": checked.reason,
        })
    if self_count != 1:
        raise ValueError("phrase must contain exactly one prototype occurrence")
    return {
        "family_id": phrase["family_id"],
        "geometry": list(geometry),
        "occurrence_count": len(occurrences),
        "direct_edge_count": len(direct_edges),
        "direct_edges": direct_edges,
    }


def _phrase_summary(phrase: dict[str, Any], rank: int) -> dict[str, Any]:
    return {
        "rank": rank,
        "family_id": phrase["family_id"],
        "start_tick": phrase["start_tick"],
        "end_tick": phrase["end_tick"],
        "bar_count": phrase["bar_count"],
        "note_count": phrase["note_count"],
        "occurrence_count": phrase["occurrence_count"],
        "occurrences": _coordinates(phrase),
        "recurrence_score": phrase["recurrence_score"],
    }


def _semantic_difference(baseline: list[dict[str, Any]], candidate: list[dict[str, Any]]) -> dict[str, Any]:
    baseline_summary = [_phrase_summary(phrase, index) for index, phrase in enumerate(baseline, 1)]
    candidate_summary = [_phrase_summary(phrase, index) for index, phrase in enumerate(candidate, 1)]
    baseline_by_family = {item["family_id"]: item for item in baseline_summary}
    candidate_by_family = {item["family_id"]: item for item in candidate_summary}
    baseline_families = set(baseline_by_family)
    candidate_families = set(candidate_by_family)
    replacements = []
    for index in range(max(len(baseline_summary), len(candidate_summary))):
        left = baseline_summary[index] if index < len(baseline_summary) else None
        right = candidate_summary[index] if index < len(candidate_summary) else None
        if (left is None or right is None or left["family_id"] != right["family_id"]):
            replacements.append({"baseline": left, "candidate": right})
    support = []
    for family_id in sorted(baseline_families | candidate_families):
        left, right = baseline_by_family.get(family_id), candidate_by_family.get(family_id)
        left_occurrences = set(map(tuple, left["occurrences"])) if left else set()
        right_occurrences = set(map(tuple, right["occurrences"])) if right else set()
        gained = sorted(right_occurrences - left_occurrences)
        lost = sorted(left_occurrences - right_occurrences)
        score_delta = None if left is None or right is None else right["recurrence_score"] - left["recurrence_score"]
        support.append({
            "family_id": family_id,
            "baseline_rank": left["rank"] if left else None,
            "candidate_rank": right["rank"] if right else None,
            "baseline_occurrence_count": left["occurrence_count"] if left else 0,
            "candidate_occurrence_count": right["occurrence_count"] if right else 0,
            "gained_occurrences": [list(item) for item in gained],
            "lost_occurrences": [list(item) for item in lost],
            "score_delta": score_delta,
        })
    return {
        "baseline": baseline_summary,
        "candidate": candidate_summary,
        "rank_replacements": replacements,
        "baseline_disappeared": [baseline_by_family[item] for item in sorted(baseline_families - candidate_families)],
        "candidate_new": [candidate_by_family[item] for item in sorted(candidate_families - baseline_families)],
        "occurrence_support": support,
        "top1_changed": bool(baseline_summary and candidate_summary
                              and baseline_summary[0]["family_id"] != candidate_summary[0]["family_id"]),
    }


def _safe_source(root: Path, relative: str) -> Path:
    path = PurePosixPath(relative)
    if path.is_absolute() or ".." in path.parts or "\\" in relative:
        raise ValueError("unsafe source path")
    root = root.resolve(strict=True)
    resolved = (root / relative).resolve(strict=True)
    if not resolved.is_file() or not resolved.is_relative_to(root):
        raise ValueError("source path escapes source root")
    return resolved


def _load_manifest(path: Path) -> dict[str, dict[str, Any]]:
    rows = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        source_path = row.get("source_path")
        if not isinstance(source_path, str) or source_path in rows:
            raise ValueError("manifest has duplicate or invalid source paths")
        rows[source_path] = row
    return rows


def run(cache: Path, source_root: Path, manifest: Path, output: Path) -> dict[str, Any]:
    repository = Path(__file__).resolve().parents[1]
    cache, source_root, manifest = cache.resolve(strict=True), source_root.resolve(strict=True), manifest.resolve(strict=True)
    if not cache.is_dir() or not source_root.is_dir() or not manifest.is_file():
        raise ValueError("cache, source root and manifest must exist")
    if file_digest(manifest) != "fa4c3010b8b17fdd8fbd58c87257281c01abf4a7325f94481fd9b5dfd3380823":
        raise ValueError("unexpected strict v02 source manifest")
    completion = verify_completed_experiment(cache)
    start_receipt = json.loads((cache / "experiment_receipt.json").read_text(encoding="utf-8"))
    raw_path, aggregate_path = cache / "raw_results.json", cache / "aggregate.json"
    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    if file_digest(raw_path) != completion["artifacts"]["raw_results.json"]["sha256"]:
        raise ValueError("cache raw results changed after completion")
    if file_digest(aggregate_path) != completion["artifacts"]["aggregate.json"]["sha256"]:
        raise ValueError("cache aggregate changed after completion")
    if start_receipt["design"].get("manifest_sha256") != file_digest(manifest):
        raise ValueError("cache and requested manifest differ")
    rows = raw.get("rows")
    if not isinstance(rows, list) or len(rows) != EXPECTED_PARSED_ROWS:
        raise ValueError("unexpected parsed row count in completed cache")
    changed = [row for row in rows if row.get("kind") == "source" and row.get("phrases_equal") is False]
    if len(changed) != EXPECTED_CHANGED_FILES:
        raise ValueError("unexpected changed file count in completed cache")
    manifest_rows = _load_manifest(manifest)
    changed_paths = [row.get("case_id") for row in changed]
    if any(not isinstance(path, str) or path not in manifest_rows for path in changed_paths):
        raise ValueError("changed cache row is absent from strict source manifest")
    cohort = [{
        "kind": "changed_source",
        "source_path": path,
        "source_sha256": manifest_rows[path]["source_sha256"],
        "baseline_output_sha256": sha256(json.dumps(row["changed_phrases"]["baseline"], sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        "candidate_output_sha256": sha256(json.dumps(row["changed_phrases"]["candidate"], sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
    } for path, row in zip(changed_paths, changed)]
    required = [
        "scripts/audit_drum_cache_changes.py",
        "samuged/drum_oracle.py",
        "samuged/drums.py",
        "samuged/midi.py",
        "samuged/__init__.py",
        "samuged/experiment.py",
        "samuged/dataset.py",
        "pyproject.toml",
        "requirements-research.lock",
        "research_local/drum_cache_full_v02/raw_results.json",
        "research_local/drum_cache_full_v02/aggregate.json",
        "research_local/drum_cache_full_v02/experiment_receipt.json",
        "research_local/drum_cache_full_v02/completion_receipt.json",
        "research_local/lakh_phrases_v02/sources.jsonl",
    ]
    required.extend(f"datasets/Lakh MIDI Clean/{path}" for path in changed_paths)
    design = {
        "version": "drum-cache-change-audit-v1",
        "purpose": "independent source and oracle verification of changed baseline/candidate drum outputs",
        "cache_path": "research_local/drum_cache_full_v02",
        "cache_raw_sha256": file_digest(raw_path),
        "cache_aggregate_sha256": file_digest(aggregate_path),
        "cache_completion_sha256": file_digest(cache / "completion_receipt.json"),
        "manifest_path": "research_local/lakh_phrases_v02/sources.jsonl",
        "manifest_sha256": file_digest(manifest),
        "changed_files": EXPECTED_CHANGED_FILES,
        "parsed_rows": len(rows),
        "oracle_version": ORACLE_VERSION,
        "oracle_config": ORACLE_CONFIG,
        "claim_boundary": "edge and output semantics only; no musical quality, human relevance or promotion claim",
    }
    receipt = prepare_experiment(output, design=design, config={"oracle": ORACLE_CONFIG}, cases=cohort,
                                 required_files=required)
    links = receipt_links(receipt)
    audited = []
    errors = []
    for row in changed:
        source_path = row["case_id"]
        manifest_row = manifest_rows[source_path]
        source = _safe_source(source_root, source_path)
        if file_digest(source) != manifest_row.get("source_sha256"):
            raise ValueError(f"source differs from strict manifest: {source_path}")
        try:
            song = load_midi(source, recover_invalid_keys=bool(manifest_row.get("metadata_repairs")))
        except Exception as exc:
            errors.append({"source_path": source_path, "error_type": type(exc).__name__})
            continue
        if song.metadata_repairs != manifest_row.get("metadata_repairs", []):
            raise ValueError(f"metadata recovery differs from manifest: {source_path}")
        windows = {window.identity: window for window in enumerate_windows(song)}
        drum_parts = [part for part in song.parts if part.is_drum]
        source_metadata = (
            sorted({part.index for part in drum_parts}),
            sorted({part.track for part in drum_parts}),
            sorted({part.program for part in drum_parts}),
        )
        method_results = {}
        for method in ("baseline", "candidate"):
            phrases = row.get("changed_phrases", {}).get(method)
            if not isinstance(phrases, list):
                raise ValueError(f"missing {method} changed phrases: {source_path}")
            validations = [
                _validate_phrase(phrase, windows, song.ticks_per_beat, source_metadata)
                for phrase in phrases
            ]
            method_results[method] = {
                "phrase_count": len(phrases),
                "direct_edge_count": sum(item["direct_edge_count"] for item in validations),
                "validated_phrases": validations,
                "cache_stats": row["methods"][method],
            }
        difference = _semantic_difference(
            row["changed_phrases"]["baseline"], row["changed_phrases"]["candidate"]
        )
        audited.append({
            "source_path": source_path,
            "source_sha256": manifest_row["source_sha256"],
            "ticks_per_beat": song.ticks_per_beat,
            "oracle_window_count": len(windows),
            "baseline": method_results["baseline"],
            "candidate": method_results["candidate"],
            "semantic_difference": difference,
        })
    if errors:
        raise ValueError(f"changed source validation failed: {errors}")
    total_edges = {
        method: sum(item[method]["direct_edge_count"] for item in audited)
        for method in ("baseline", "candidate")
    }
    aggregate = {
        **links,
        "schema_version": "drum-cache-change-audit-v1",
        "changed_files": len(audited),
        "baseline_phrase_count": sum(item["baseline"]["phrase_count"] for item in audited),
        "candidate_phrase_count": sum(item["candidate"]["phrase_count"] for item in audited),
        "direct_edge_counts": total_edges,
        "files_with_top1_change": sum(item["semantic_difference"]["top1_changed"] for item in audited),
        "baseline_candidates_disappeared": sum(len(item["semantic_difference"]["baseline_disappeared"]) for item in audited),
        "candidate_families_new": sum(len(item["semantic_difference"]["candidate_new"]) for item in audited),
        "occurrences_gained": sum(len(change["gained_occurrences"])
                                   for item in audited for change in item["semantic_difference"]["occurrence_support"]),
        "occurrences_lost": sum(len(change["lost_occurrences"])
                                 for item in audited for change in item["semantic_difference"]["occurrence_support"]),
        "files": audited,
        "claim_boundary": design["claim_boundary"],
    }
    atomic_json(output / "raw_results.json", {**links, "rows": audited, "errors": errors})
    atomic_json(output / "aggregate.json", aggregate)
    complete_experiment(output)
    return aggregate


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(**vars(args)), indent=2, sort_keys=True))
