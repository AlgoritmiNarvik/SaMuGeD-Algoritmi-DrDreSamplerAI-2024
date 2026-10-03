"""Measure descriptive curation properties of an audited SaMuGeD dataset."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from decimal import Decimal
from fractions import Fraction
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Iterable

from samuged.dataset import atomic_json
from samuged.experiment import (
    complete_experiment,
    prepare_experiment,
    receipt_links,
    verify_completed_experiment,
)


VERSION = "curation-diagnostics-v1"
KINDS = ("melodic", "percussion")
PRINCIPAL_FILES = (
    "sources.jsonl",
    "phrases.jsonl",
    "summary.json",
    "build_config.json",
    "audit.json",
)
AUDIT_BINDINGS = {
    "source_manifest_sha256": "sources.jsonl",
    "phrase_manifest_sha256": "phrases.jsonl",
    "summary_sha256": "summary.json",
    "build_config_sha256": "build_config.json",
}
REQUIRED_FILES = (
    "scripts/audit_curation.py",
    "samuged/dataset.py",
    "samuged/experiment.py",
    "pyproject.toml",
    "requirements-research.lock",
)
QUANTILES = (("p10", 1, 10), ("p25", 1, 4), ("median", 1, 2),
             ("p75", 3, 4), ("p90", 9, 10), ("p95", 19, 20),
             ("p99", 99, 100))


def _hash_file(path: Path) -> dict[str, Any]:
    digest = sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return {"path": path.name, "bytes": size, "sha256": digest.hexdigest()}


def _load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _principal_inventory(dataset: Path) -> list[dict[str, Any]]:
    entries = []
    for name in PRINCIPAL_FILES:
        path = dataset / name
        if not path.is_file():
            raise FileNotFoundError(f"missing dataset artifact: {path}")
        entries.append(_hash_file(path))
    return entries


def _inventory_map(entries: Iterable[dict[str, Any]]) -> dict[str, str]:
    return {entry["path"]: entry["sha256"] for entry in entries}


def _verify_dataset_audit(dataset: Path, hashes: dict[str, str]) -> dict[str, Any]:
    audit = _load_object(dataset / "audit.json")
    if audit.get("passed") is not True or audit.get("failure_count") != 0 or audit.get("failures") != []:
        raise ValueError("dataset audit did not pass cleanly")
    if audit.get("full_source_coverage_required") is not True:
        raise ValueError("dataset audit does not require full source coverage")
    for field, filename in AUDIT_BINDINGS.items():
        if audit.get(field) != hashes[filename]:
            raise ValueError(f"dataset audit binding mismatch: {filename}")
    summary = _load_object(dataset / "summary.json")
    for field, filename in (
        ("source_manifest_sha256", "sources.jsonl"),
        ("phrase_manifest_sha256", "phrases.jsonl"),
    ):
        if summary.get(field) != hashes[filename]:
            raise ValueError(f"dataset summary binding mismatch: {filename}")
    return audit


def _fraction_payload(value: Fraction) -> dict[str, Any]:
    return {
        "numerator": value.numerator,
        "denominator": value.denominator,
        "decimal": round(float(value), 8),
    }


def _rank_index(length: int, numerator: int, denominator: int) -> int:
    return ((length - 1) * numerator + denominator // 2) // denominator


def distribution(values: Iterable[int | Fraction], *, rational: bool = False) -> dict[str, Any]:
    ordered = sorted(values)
    if not ordered:
        return {"count": 0}
    render = _fraction_payload if rational else lambda value: value
    result = {
        "count": len(ordered),
        "min": render(ordered[0]),
        "max": render(ordered[-1]),
    }
    for label, numerator, denominator in QUANTILES:
        result[label] = render(ordered[_rank_index(len(ordered), numerator, denominator)])
    return result


def _union_length(intervals: Iterable[tuple[int, int]]) -> int:
    ordered = sorted(intervals)
    if not ordered:
        return 0
    start, end = ordered[0]
    if start < 0 or end <= start:
        raise ValueError("invalid temporal interval")
    total = 0
    for next_start, next_end in ordered[1:]:
        if next_start < 0 or next_end <= next_start:
            raise ValueError("invalid temporal interval")
        if next_start <= end:
            end = max(end, next_end)
        else:
            total += end - start
            start, end = next_start, next_end
    return total + end - start


def _nearest_tick(value: Any, ticks_per_beat: int) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("onset beat must be numeric")
    exact = Fraction(Decimal(str(value))) * ticks_per_beat
    quotient, remainder = divmod(exact.numerator, exact.denominator)
    tick = quotient + int(2 * remainder >= exact.denominator)
    if abs(exact - tick) > Fraction(1, 100):
        raise ValueError("serialized onset cannot be reconstructed within 0.01 tick")
    return tick


def phrase_diagnostic(row: dict[str, Any]) -> dict[str, Any]:
    kind = row.get("kind")
    if kind not in KINDS:
        raise ValueError("unsupported phrase kind")
    ppq = row.get("ticks_per_beat")
    start, end = row.get("start_tick"), row.get("end_tick")
    note_count = row.get("note_count")
    if (isinstance(ppq, bool) or not isinstance(ppq, int) or ppq <= 0
            or isinstance(start, bool) or not isinstance(start, int) or start < 0
            or isinstance(end, bool) or not isinstance(end, int) or end <= start
            or isinstance(note_count, bool) or not isinstance(note_count, int) or note_count <= 0):
        raise ValueError("invalid phrase timing or count")
    pitches = row.get("pitches")
    onsets = row.get("onsets_beats")
    occurrences = row.get("occurrences")
    if (not isinstance(pitches, list) or not isinstance(onsets, list)
            or len(pitches) != note_count or len(onsets) != note_count
            or not isinstance(occurrences, list)
            or row.get("occurrence_count") != len(occurrences)):
        raise ValueError("phrase arrays or occurrence count do not match note_count")
    onset_ticks = [_nearest_tick(value, ppq) for value in onsets]
    if onset_ticks != sorted(onset_ticks) or any(tick < 0 or tick >= end - start for tick in onset_ticks):
        raise ValueError("invalid prototype onset sequence")
    distinct_onsets = sorted(set(onset_ticks))
    positive_iois = {
        right - left for left, right in zip(distinct_onsets, distinct_onsets[1:]) if right > left
    }
    occurrence_intervals = []
    for occurrence in occurrences:
        if not isinstance(occurrence, dict):
            raise ValueError("occurrence must be an object")
        occurrence_intervals.append((occurrence.get("start_tick"), occurrence.get("end_tick")))
    # Validate every occurrence even when no interval union is requested later.
    _union_length(occurrence_intervals)
    return {
        "kind": kind,
        "source_id": row.get("source_id"),
        "family_id": row.get("family_id"),
        "phrase_id": row.get("phrase_id"),
        "rank_in_file": row.get("rank_in_file"),
        "part_index": row.get("part_index"),
        "source_part_indices": row.get("source_part_indices", []),
        "ticks_per_beat": ppq,
        "prototype_interval": (start, end),
        "occurrence_intervals": occurrence_intervals,
        "duration_ticks": end - start,
        "note_count": note_count,
        "occurrence_count": len(occurrences),
        "single_pitch": len(set(pitches)) == 1,
        "rhythmic_vocabulary_size": len(positive_iois),
        "tiny_rhythmic_vocabulary": len(positive_iois) <= 2,
        "distinct_onset_count": len(distinct_onsets),
        "simultaneous_extra_notes": note_count - len(distinct_onsets),
    }


def _read_sources(path: Path, expected_hash: str) -> dict[str, dict[str, Any]]:
    digest = sha256()
    rows: dict[str, dict[str, Any]] = {}
    with path.open("rb") as stream:
        for line_number, line in enumerate(stream, 1):
            digest.update(line)
            if not line.strip():
                continue
            row = json.loads(line)
            source_id = row.get("source_id")
            if not isinstance(source_id, str) or not source_id or source_id in rows:
                raise ValueError(f"invalid or duplicate source ID at line {line_number}")
            ppq = row.get("ticks_per_beat")
            if row.get("status") == "ok" and (isinstance(ppq, bool) or not isinstance(ppq, int) or ppq <= 0):
                raise ValueError(f"parsed source lacks valid PPQ at line {line_number}")
            rows[source_id] = {
                "status": row.get("status"),
                "ticks_per_beat": ppq,
                "phrase_count": len(row.get("phrases", [])),
            }
    if digest.hexdigest() != expected_hash:
        raise ValueError("source manifest changed while reading")
    return rows


def _read_phrases(
    path: Path,
    expected_hash: str,
    sources: dict[str, dict[str, Any]],
) -> tuple[dict[tuple[str, str], list[dict[str, Any]]], dict[str, list[dict[str, Any]]]]:
    digest = sha256()
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    by_kind: dict[str, list[dict[str, Any]]] = defaultdict(list)
    phrase_ids: set[str] = set()
    source_phrase_counts: Counter[str] = Counter()
    with path.open("rb") as stream:
        for line_number, line in enumerate(stream, 1):
            digest.update(line)
            if not line.strip():
                continue
            row = json.loads(line)
            diagnostic = phrase_diagnostic(row)
            source_id = diagnostic["source_id"]
            phrase_id = diagnostic["phrase_id"]
            if source_id not in sources or sources[source_id]["status"] != "ok":
                raise ValueError(f"phrase references unavailable source at line {line_number}")
            if diagnostic["ticks_per_beat"] != sources[source_id]["ticks_per_beat"]:
                raise ValueError(f"phrase PPQ differs from source at line {line_number}")
            if not isinstance(phrase_id, str) or not phrase_id or phrase_id in phrase_ids:
                raise ValueError(f"invalid or duplicate phrase ID at line {line_number}")
            if (isinstance(diagnostic["rank_in_file"], bool)
                    or not isinstance(diagnostic["rank_in_file"], int)
                    or diagnostic["rank_in_file"] <= 0):
                raise ValueError(f"invalid phrase rank at line {line_number}")
            phrase_ids.add(phrase_id)
            source_phrase_counts[source_id] += 1
            groups[(source_id, diagnostic["kind"])].append(diagnostic)
            by_kind[diagnostic["kind"]].append(diagnostic)
    if digest.hexdigest() != expected_hash:
        raise ValueError("phrase manifest changed while reading")
    for source_id, source in sources.items():
        if source_phrase_counts[source_id] != source["phrase_count"]:
            raise ValueError(f"source and phrase manifest counts differ: {source_id}")
    return groups, by_kind


def _coverage(intervals: list[tuple[int, int]]) -> dict[str, int | Fraction]:
    summed = sum(end - start for start, end in intervals)
    union = _union_length(intervals)
    overlap = summed - union
    return {
        "sum_ticks": summed,
        "union_ticks": union,
        "overlap_ticks": overlap,
        "union_over_sum": Fraction(union, summed) if summed else Fraction(0),
        "overlap_over_sum": Fraction(overlap, summed) if summed else Fraction(0),
    }


def source_group_diagnostic(source_id: str, kind: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(rows, key=lambda row: (row["rank_in_file"], row["phrase_id"]))
    selected = ordered[:3]
    ppqs = {row["ticks_per_beat"] for row in selected}
    if len(ppqs) != 1:
        raise ValueError("source group has inconsistent PPQ")
    prototype = _coverage([row["prototype_interval"] for row in selected])
    occurrence = _coverage([
        interval for row in selected for interval in row["occurrence_intervals"]
    ])
    family_counts = Counter(row["family_id"] for row in selected)
    result: dict[str, Any] = {
        "source_id": source_id,
        "kind": kind,
        "ticks_per_beat": next(iter(ppqs)),
        "available_phrase_count": len(ordered),
        "selected_phrase_count": len(selected),
        "selected_family_count": len(family_counts),
        "duplicate_family_slots": len(selected) - len(family_counts),
        "prototype": prototype,
        "occurrences": occurrence,
    }
    if kind == "melodic":
        parts = Counter(row["part_index"] for row in selected)
        result.update({
            "selected_part_count": len(parts),
            "dominant_part_share": Fraction(max(parts.values()), len(selected)),
            "all_selected_from_one_part": len(parts) == 1,
        })
    else:
        source_parts = set().union(*(set(row["source_part_indices"]) for row in selected))
        result.update({
            "ensemble_source_part_count": len(source_parts),
            "uses_multiple_source_drum_parts": len(source_parts) > 1,
        })
    return result


def _coverage_summary(groups: list[dict[str, Any]], field: str) -> dict[str, Any]:
    total_sum_beats = sum(
        Fraction(group[field]["sum_ticks"], group["ticks_per_beat"]) for group in groups
    )
    total_union_beats = sum(
        Fraction(group[field]["union_ticks"], group["ticks_per_beat"]) for group in groups
    )
    total_overlap_beats = total_sum_beats - total_union_beats
    return {
        "source_kind_groups": len(groups),
        "definition": (
            "prototype intervals of the lowest three within-kind ranks"
            if field == "prototype"
            else "all saved occurrence intervals of the lowest three within-kind ranks"
        ),
        "sum_beats": _fraction_payload(total_sum_beats),
        "union_beats": _fraction_payload(total_union_beats),
        "overlap_beats": _fraction_payload(total_overlap_beats),
        "union_over_sum": _fraction_payload(
            total_union_beats / total_sum_beats if total_sum_beats else Fraction(0)
        ),
        "overlap_over_sum": _fraction_payload(
            total_overlap_beats / total_sum_beats if total_sum_beats else Fraction(0)
        ),
        "groups_with_any_overlap": sum(group[field]["overlap_ticks"] > 0 for group in groups),
        "source_sum_beats": distribution(
            (Fraction(group[field]["sum_ticks"], group["ticks_per_beat"]) for group in groups),
            rational=True,
        ),
        "source_union_beats": distribution(
            (Fraction(group[field]["union_ticks"], group["ticks_per_beat"]) for group in groups),
            rational=True,
        ),
        "source_overlap_fraction": distribution(
            (group[field]["overlap_over_sum"] for group in groups), rational=True
        ),
    }


def _frequency(values: Iterable[int]) -> dict[str, int]:
    return {str(key): count for key, count in sorted(Counter(values).items())}


def analyze(
    sources: dict[str, dict[str, Any]],
    groups: dict[tuple[str, str], list[dict[str, Any]]],
    by_kind: dict[str, list[dict[str, Any]]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    raw_groups = [
        source_group_diagnostic(source_id, kind, rows)
        for (source_id, kind), rows in sorted(groups.items())
    ]
    result: dict[str, Any] = {
        "version": VERSION,
        "validated_source_rows": len(sources),
        "validated_phrase_rows": sum(len(rows) for rows in by_kind.values()),
        "claim_boundary": (
            "descriptive curation diagnostics only; no human quality, false-positive, "
            "memorability or exhaustive-search claim"
        ),
        "source_duration_boundary": (
            "manifests do not contain total song duration, so temporal measures compare "
            "summed and unioned selected intervals rather than percent of each song"
        ),
        "kinds": {},
    }
    for kind in KINDS:
        phrases = by_kind.get(kind, [])
        kind_groups = [group for group in raw_groups if group["kind"] == kind]
        family_sources: dict[str, set[str]] = defaultdict(set)
        family_rows: Counter[str] = Counter()
        for row in phrases:
            family_sources[row["family_id"]].add(row["source_id"])
            family_rows[row["family_id"]] += 1
        families_across_sources = {
            family for family, source_ids in family_sources.items() if len(source_ids) > 1
        }
        duration_beats = [Fraction(row["duration_ticks"], row["ticks_per_beat"]) for row in phrases]
        kind_result: dict[str, Any] = {
            "phrase_count": len(phrases),
            "source_count": len({row["source_id"] for row in phrases}),
            "selected_phrase_count_per_source": {
                "distribution": distribution(
                    group["selected_phrase_count"] for group in kind_groups
                ),
                "frequency": _frequency(
                    group["selected_phrase_count"] for group in kind_groups
                ),
            },
            "temporal_coverage": {
                "prototype": _coverage_summary(kind_groups, "prototype"),
                "occurrences": _coverage_summary(kind_groups, "occurrences"),
            },
            "selected_family_duplicates": {
                "unique_family_count": len(family_rows),
                "duplicate_family_slots_corpus": len(phrases) - len(family_rows),
                "source_kind_groups_with_duplicate_family": sum(
                    group["duplicate_family_slots"] > 0 for group in kind_groups
                ),
                "duplicate_family_slots_within_source_top3": sum(
                    group["duplicate_family_slots"] for group in kind_groups
                ),
                "families_in_multiple_sources": len(families_across_sources),
                "rows_in_families_spanning_multiple_sources": sum(
                    family_rows[family] for family in families_across_sources
                ),
                "source_multiplicity": distribution(len(value) for value in family_sources.values()),
                "row_multiplicity": distribution(family_rows.values()),
            },
            "phrase_distributions": {
                "duration_beats_exact": distribution(duration_beats, rational=True),
                "note_count": distribution(row["note_count"] for row in phrases),
                "occurrence_count": distribution(row["occurrence_count"] for row in phrases),
            },
            "repetitive_structure": {
                "single_pitch_phrases": sum(row["single_pitch"] for row in phrases),
                "single_pitch_fraction": _fraction_payload(Fraction(
                    sum(row["single_pitch"] for row in phrases), len(phrases) or 1
                )),
                "tiny_rhythmic_vocabulary_definition": (
                    "at most two distinct positive inter-onset intervals after simultaneous "
                    "notes are collapsed; stored beat onsets are mapped to nearest source tick"
                ),
                "tiny_rhythmic_vocabulary_phrases": sum(
                    row["tiny_rhythmic_vocabulary"] for row in phrases
                ),
                "tiny_rhythmic_vocabulary_fraction": _fraction_payload(Fraction(
                    sum(row["tiny_rhythmic_vocabulary"] for row in phrases), len(phrases) or 1
                )),
                "rhythmic_vocabulary_size": distribution(
                    row["rhythmic_vocabulary_size"] for row in phrases
                ),
                "rhythmic_vocabulary_size_frequency": _frequency(
                    row["rhythmic_vocabulary_size"] for row in phrases
                ),
                "simultaneous_extra_notes": sum(row["simultaneous_extra_notes"] for row in phrases),
            },
        }
        if kind == "melodic":
            kind_result["part_concentration"] = {
                "definition": "part_index among the lowest three within-kind ranks in each source",
                "groups": len(kind_groups),
                "groups_all_selected_from_one_part": sum(
                    group["all_selected_from_one_part"] for group in kind_groups
                ),
                "all_selected_from_one_part_fraction": _fraction_payload(Fraction(
                    sum(group["all_selected_from_one_part"] for group in kind_groups),
                    len(kind_groups) or 1,
                )),
                "selected_part_count": distribution(
                    group["selected_part_count"] for group in kind_groups
                ),
                "dominant_part_share": distribution(
                    (group["dominant_part_share"] for group in kind_groups), rational=True
                ),
            }
        else:
            kind_result["part_concentration"] = {
                "definition": (
                    "percussion is an aggregate ensemble; this reports the union of "
                    "source_part_indices represented by selected rows"
                ),
                "groups": len(kind_groups),
                "groups_using_multiple_source_drum_parts": sum(
                    group["uses_multiple_source_drum_parts"] for group in kind_groups
                ),
                "ensemble_source_part_count": distribution(
                    group["ensemble_source_part_count"] for group in kind_groups
                ),
            }
        result["kinds"][kind] = kind_result
    return result, raw_groups


def _raw_group_payload(group: dict[str, Any]) -> dict[str, Any]:
    result = dict(group)
    for field in ("prototype", "occurrences"):
        result[field] = {
            key: (_fraction_payload(value) if isinstance(value, Fraction) else value)
            for key, value in group[field].items()
        }
    if isinstance(result.get("dominant_part_share"), Fraction):
        result["dominant_part_share"] = _fraction_payload(result["dominant_part_share"])
    return result


def run(dataset: Path, output: Path) -> dict[str, Any]:
    dataset = dataset.resolve(strict=True)
    inventory = _principal_inventory(dataset)
    hashes = _inventory_map(inventory)
    audit = _verify_dataset_audit(dataset, hashes)
    summary = _load_object(dataset / "summary.json")
    design = {
        "version": VERSION,
        "purpose": "descriptive phrase curation diagnostics for dataset packaging",
        "dataset": str(dataset),
        "dataset_run_key": summary.get("run_key"),
        "algorithm": summary.get("algorithm"),
        "input_inventory": inventory,
        "result_artifacts": ["aggregate.json", "raw_results.json"],
        "claim_boundary": (
            "descriptive curation diagnostics only; no human quality, false-positive, "
            "memorability or exhaustive-search claim"
        ),
    }
    config = {
        "top_k_per_kind": 3,
        "prototype_coverage": "union and sum of selected prototype [start_tick,end_tick) intervals",
        "occurrence_coverage": "union and sum of every saved selected occurrence [start_tick,end_tick) interval",
        "rhythmic_vocabulary": "distinct positive inter-onset tick intervals after collapsing simultaneous notes",
        "tiny_rhythmic_vocabulary_max_size": 2,
        "require_passed_bound_full_coverage_audit": True,
        "validate_all_source_and_phrase_rows": True,
    }
    receipt = prepare_experiment(
        output,
        design=design,
        config=config,
        cases=[{
            "dataset": str(dataset),
            "run_key": summary.get("run_key"),
            "source_files": summary.get("source_files"),
            "phrase_counts": summary.get("phrase_counts"),
            "audit_sha256": hashes["audit.json"],
            "source_manifest_sha256": hashes["sources.jsonl"],
            "phrase_manifest_sha256": hashes["phrases.jsonl"],
        }],
        required_files=REQUIRED_FILES,
    )
    links = receipt_links(receipt)
    sources = _read_sources(dataset / "sources.jsonl", hashes["sources.jsonl"])
    groups, by_kind = _read_phrases(dataset / "phrases.jsonl", hashes["phrases.jsonl"], sources)
    diagnostics, raw_groups = analyze(sources, groups, by_kind)
    if diagnostics["validated_source_rows"] != audit.get("source_files"):
        raise ValueError("validated source count differs from dataset audit")
    if diagnostics["validated_phrase_rows"] != audit.get("phrase_rows"):
        raise ValueError("validated phrase count differs from dataset audit")
    for kind in KINDS:
        if diagnostics["kinds"][kind]["phrase_count"] != audit.get("counts", {}).get(kind, 0):
            raise ValueError(f"validated {kind} count differs from dataset audit")
    final_inventory = _principal_inventory(dataset)
    if final_inventory != inventory:
        raise ValueError("dataset artifacts changed during curation audit")
    raw = {
        **links,
        "version": VERSION,
        "dataset": str(dataset),
        "dataset_audit_sha256": hashes["audit.json"],
        "source_groups": [_raw_group_payload(group) for group in raw_groups],
        "validated_source_rows": diagnostics["validated_source_rows"],
        "validated_phrase_rows": diagnostics["validated_phrase_rows"],
    }
    aggregate = {
        **links,
        **diagnostics,
        "dataset": str(dataset),
        "dataset_run_key": summary.get("run_key"),
        "dataset_audit_sha256": hashes["audit.json"],
        "dataset_bindings": {
            key: hashes[filename] for key, filename in AUDIT_BINDINGS.items()
        },
        "raw_source_group_count": len(raw_groups),
    }
    atomic_json(output / "raw_results.json", raw)
    atomic_json(output / "aggregate.json", aggregate)
    complete_experiment(output)
    verify_completed_experiment(output)
    return aggregate


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.dataset, args.output)
    print(json.dumps({
        "output": str(args.output),
        "validated_source_rows": result["validated_source_rows"],
        "validated_phrase_rows": result["validated_phrase_rows"],
    }, indent=2))


if __name__ == "__main__":
    main()
