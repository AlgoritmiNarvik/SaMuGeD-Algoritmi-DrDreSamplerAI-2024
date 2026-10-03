"""Compare two audited SaMuGeD algorithm builds over identical sources."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from hashlib import sha256
import json
from pathlib import Path
import statistics
from typing import Any, Iterable

from samuged.dataset import atomic_json
from samuged.experiment import complete_experiment, prepare_experiment, receipt_links, sha256_json


VERSION = "algorithm-variant-comparison-v1"
KINDS = ("melodic", "percussion")
PHRASE_EXCLUSIONS = frozenset({"phrase_id", "midi_path", "rank_in_file"})
MANIFEST_ONLY_FIELDS = frozenset({"split", "split_group"})
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
SOURCE_IDENTITY_FIELDS = (
    "source_id",
    "source_path",
    "source_sha256",
    "source_bytes",
    "artist_from_path",
    "artist_key",
    "title_from_path",
    "song_key",
    "status",
    "outcome",
    "musical_sha256",
    "ticks_per_beat",
    "part_count",
    "note_count",
    "warnings",
    "metadata_repairs",
    "error_type",
    "error",
)
REQUIRED_FILES = (
    "scripts/compare_variants.py",
    "samuged/dataset.py",
    "samuged/experiment.py",
    "pyproject.toml",
    "requirements-research.lock",
)


def _hash_file(path: Path) -> dict[str, Any]:
    digest = sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return {"path": path.name, "bytes": size, "sha256": digest.hexdigest()}


def semantic_phrase(phrase: dict[str, Any]) -> dict[str, Any]:
    """Exclude build identifiers, artifact paths and the cross-kind global rank."""
    return {key: value for key, value in phrase.items() if key not in PHRASE_EXCLUSIONS}


def semantic_phrases(record: dict[str, Any], kind: str) -> list[dict[str, Any]]:
    return [semantic_phrase(row) for row in record.get("phrases", []) if row.get("kind") == kind]


def _source_identity(record: dict[str, Any]) -> dict[str, Any]:
    return {key: record.get(key) for key in SOURCE_IDENTITY_FIELDS}


def _manifest_record_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in row.items() if key not in MANIFEST_ONLY_FIELDS}


def _bounded_difference_paths(left: Any, right: Any, *, limit: int = 200) -> list[str]:
    paths: list[str] = []

    def walk(a: Any, b: Any, path: str) -> None:
        if len(paths) >= limit or a == b:
            return
        if isinstance(a, dict) and isinstance(b, dict):
            for key in sorted(set(a) | set(b)):
                child = f"{path}.{key}" if path else str(key)
                if key not in a or key not in b:
                    paths.append(child)
                else:
                    walk(a[key], b[key], child)
                if len(paths) >= limit:
                    return
            return
        if isinstance(a, list) and isinstance(b, list):
            if len(a) != len(b):
                paths.append(f"{path}.length")
            for index, (first, second) in enumerate(zip(a, b)):
                walk(first, second, f"{path}[{index}]")
                if len(paths) >= limit:
                    return
            return
        paths.append(path or "$")

    walk(left, right, "")
    return paths


def selection_trace(phrases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Retain the fields needed to inspect why a selected family changed."""
    keys = (
        "rank_in_file",
        "family_id",
        "part_index",
        "source_track",
        "start_tick",
        "end_tick",
        "note_count",
        "duration_beats",
        "occurrence_count",
        "raw_occurrence_count",
        "recurrence_score",
        "score_components",
        "pitches",
        "onsets_beats",
        "durations_beats",
        "occurrences",
    )
    return [{key: phrase.get(key) for key in keys if key in phrase} for phrase in phrases]


def global_rank_shifts(
    left_phrases: list[dict[str, Any]], right_phrases: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Match exact within-kind payloads and report only their global rank movement."""
    right_by_payload: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for phrase in right_phrases:
        right_by_payload[sha256_json(semantic_phrase(phrase))].append(phrase)
    shifts = []
    for phrase in left_phrases:
        matches = right_by_payload.get(sha256_json(semantic_phrase(phrase)), [])
        if not matches:
            continue
        other = matches.pop(0)
        if phrase.get("rank_in_file") != other.get("rank_in_file"):
            shifts.append({
                "family_id": phrase.get("family_id"),
                "left_rank_in_file": phrase.get("rank_in_file"),
                "right_rank_in_file": other.get("rank_in_file"),
            })
    return shifts


def _principal_inventory(dataset: Path, side: str) -> list[dict[str, Any]]:
    entries = []
    for name in PRINCIPAL_FILES:
        path = dataset / name
        if not path.is_file():
            raise FileNotFoundError(f"missing required build artifact: {path}")
        entries.append({"side": side, **_hash_file(path)})
    return entries


def _record_inventory(dataset: Path, side: str) -> list[dict[str, Any]]:
    root = dataset / "records"
    if not root.is_dir():
        raise FileNotFoundError(f"missing records directory: {root}")
    return [
        {"side": side, "name": path.name, "bytes": item["bytes"], "sha256": item["sha256"]}
        for path in sorted(root.glob("*.json"), key=lambda value: value.name)
        for item in [_hash_file(path)]
    ]


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _verify_audit(dataset: Path, hashes: dict[str, str]) -> dict[str, Any]:
    audit = _load_json(dataset / "audit.json")
    if audit.get("passed") is not True or audit.get("failure_count") != 0 or audit.get("failures") != []:
        raise ValueError(f"build audit did not pass cleanly: {dataset}")
    if audit.get("full_source_coverage_required") is not True:
        raise ValueError(f"build audit lacks full source coverage: {dataset}")
    for field, filename in AUDIT_BINDINGS.items():
        if audit.get(field) != hashes[filename]:
            raise ValueError(f"build audit binding mismatch for {filename}: {dataset}")
    summary = _load_json(dataset / "summary.json")
    for field, filename in (
        ("source_manifest_sha256", "sources.jsonl"),
        ("phrase_manifest_sha256", "phrases.jsonl"),
    ):
        if summary.get(field) != hashes[filename]:
            raise ValueError(f"build summary binding mismatch for {filename}: {dataset}")
    return audit


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
                raise ValueError(f"invalid or duplicate source ID at {path}:{line_number}")
            rows[source_id] = {
                "source_id": source_id,
                "split": row.get("split"),
                "split_group": row.get("split_group"),
                "identity": _source_identity(row),
                "record_payload_sha256": sha256_json(_manifest_record_payload(row)),
            }
    if digest.hexdigest() != expected_hash:
        raise ValueError(f"source manifest changed while reading: {path}")
    return rows


def _read_phrase_index(
    path: Path,
    expected_hash: str,
    sources: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    digest = sha256()
    family_sources = {kind: defaultdict(set) for kind in KINDS}
    family_splits = {kind: defaultdict(set) for kind in KINDS}
    excluded_members: set[tuple[str, str, str, int | None, int | None]] = set()
    counts: Counter[str] = Counter()
    split_counts: Counter[str] = Counter()
    for_line = 0
    with path.open("rb") as stream:
        for line_number, line in enumerate(stream, 1):
            digest.update(line)
            if not line.strip():
                continue
            for_line += 1
            row = json.loads(line)
            source_id = row.get("source_id")
            kind = row.get("kind")
            family_id = row.get("family_id")
            start_tick = row.get("start_tick")
            end_tick = row.get("end_tick")
            if (
                source_id not in sources
                or kind not in KINDS
                or not isinstance(family_id, str)
                or isinstance(start_tick, bool)
                or not isinstance(start_tick, int)
                or isinstance(end_tick, bool)
                or not isinstance(end_tick, int)
            ):
                raise ValueError(f"invalid phrase row at {path}:{line_number}")
            source = sources[source_id]
            if (
                row.get("split") not in {source["split"], "overlap_excluded"}
                or row.get("split_group") != source["split_group"]
            ):
                raise ValueError(f"phrase split differs from source manifest at {path}:{line_number}")
            family_sources[kind][family_id].add(source_id)
            family_splits[kind][family_id].add(row["split"])
            if row["split"] == "overlap_excluded":
                excluded_members.add(
                    (source_id, kind, family_id, start_tick, end_tick)
                )
            counts[kind] += 1
            split_counts[row["split"]] += 1
    if digest.hexdigest() != expected_hash:
        raise ValueError(f"phrase manifest changed while reading: {path}")
    return {
        "row_count": for_line,
        "counts": counts,
        "split_counts": split_counts,
        "family_sources": family_sources,
        "family_splits": family_splits,
        "excluded_members": excluded_members,
    }


def _read_record(path: Path, expected_hash: str) -> dict[str, Any]:
    payload = path.read_bytes()
    if sha256(payload).hexdigest() != expected_hash:
        raise ValueError(f"record changed after input freeze: {path}")
    value = json.loads(payload)
    if not isinstance(value, dict):
        raise ValueError(f"record is not an object: {path}")
    return value


def _metric_summary(values: list[float | int]) -> dict[str, Any]:
    if not values:
        return {
            "count": 0,
            "sum": 0.0,
            "mean": None,
            "median": None,
            "minimum": None,
            "maximum": None,
        }
    return {
        "count": len(values),
        "sum": round(float(sum(values)), 8),
        "mean": round(float(statistics.mean(values)), 8),
        "median": round(float(statistics.median(values)), 8),
        "minimum": min(values),
        "maximum": max(values),
    }


def _collect_metrics(
    target: dict[str, list[float | int]], phrases: list[dict[str, Any]]
) -> None:
    for phrase in phrases:
        for field in (
            "note_count",
            "duration_beats",
            "occurrence_count",
            "raw_occurrence_count",
            "recurrence_score",
        ):
            value = phrase.get(field)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                target[field].append(value)
        support = phrase.get("score_components", {}).get("support")
        if isinstance(support, (int, float)) and not isinstance(support, bool):
            target["support_score"].append(support)


def _summarize_metrics(metrics: dict[str, dict[str, list[float | int]]]) -> dict[str, Any]:
    result = {}
    for kind in KINDS:
        result[kind] = {}
        for field in sorted(set(metrics["left"][kind]) | set(metrics["right"][kind])):
            left = _metric_summary(metrics["left"][kind][field])
            right = _metric_summary(metrics["right"][kind][field])
            result[kind][field] = {
                "left": left,
                "right": right,
                "count_delta": right["count"] - left["count"],
                "sum_delta": round(right["sum"] - left["sum"], 8),
                "mean_delta": (
                    None if left["mean"] is None or right["mean"] is None
                    else round(right["mean"] - left["mean"], 8)
                ),
            }
    return result


def _family_comparison(indexes: dict[str, dict[str, Any]]) -> dict[str, Any]:
    result = {}
    for kind in KINDS:
        left = indexes["left"]["family_sources"][kind]
        right = indexes["right"]["family_sources"][kind]
        common = set(left) & set(right)
        changed = sorted(family for family in common if left[family] != right[family])
        result[kind] = {
            "left_family_count": len(left),
            "right_family_count": len(right),
            "family_count_delta": len(right) - len(left),
            "common_family_count": len(common),
            "left_only_family_ids": sorted(set(left) - set(right)),
            "right_only_family_ids": sorted(set(right) - set(left)),
            "common_membership_changed_family_ids": changed,
            "left_families_with_excluded_members": sum(
                "overlap_excluded" in values
                for values in indexes["left"]["family_splits"][kind].values()
            ),
            "right_families_with_excluded_members": sum(
                "overlap_excluded" in values
                for values in indexes["right"]["family_splits"][kind].values()
            ),
            "left_active_multi_split_family_count": sum(
                len(values - {"overlap_excluded"}) > 1
                for values in indexes["left"]["family_splits"][kind].values()
            ),
            "right_active_multi_split_family_count": sum(
                len(values - {"overlap_excluded"}) > 1
                for values in indexes["right"]["family_splits"][kind].values()
            ),
        }
    return result


def _exclusion_comparison(indexes: dict[str, dict[str, Any]]) -> dict[str, Any]:
    left = indexes["left"]["excluded_members"]
    right = indexes["right"]["excluded_members"]

    def rows(values: set[tuple[str, str, str, int | None, int | None]]) -> list[dict[str, Any]]:
        return [
            {
                "source_id": source_id,
                "kind": kind,
                "family_id": family_id,
                "start_tick": start_tick,
                "end_tick": end_tick,
            }
            for source_id, kind, family_id, start_tick, end_tick in sorted(values)
        ]

    return {
        "left_excluded_phrase_count": len(left),
        "right_excluded_phrase_count": len(right),
        "excluded_phrase_count_delta": len(right) - len(left),
        "left_only_exclusions": rows(left - right),
        "right_only_exclusions": rows(right - left),
    }


def _recheck(entries: Iterable[dict[str, Any]], datasets: dict[str, Path]) -> None:
    for entry in entries:
        root = datasets[entry["side"]]
        path = (
            root
            / ("records" if "name" in entry else "")
            / entry.get("name", entry.get("path"))
        )
        current = _hash_file(path)
        if current["bytes"] != entry["bytes"] or current["sha256"] != entry["sha256"]:
            raise ValueError(f"frozen comparison input changed: {path}")


def compare_variants(left: Path, right: Path, output: Path) -> dict[str, Any]:
    datasets = {"left": left.resolve(), "right": right.resolve()}
    principal = [
        entry
        for side in ("left", "right")
        for entry in _principal_inventory(datasets[side], side)
    ]
    records = [
        entry
        for side in ("left", "right")
        for entry in _record_inventory(datasets[side], side)
    ]
    principal_hashes = {
        side: {
            row["path"]: row["sha256"]
            for row in principal
            if row["side"] == side
        }
        for side in ("left", "right")
    }
    audits = {
        side: _verify_audit(datasets[side], principal_hashes[side])
        for side in ("left", "right")
    }
    configs = {side: _load_json(datasets[side] / "build_config.json") for side in ("left", "right")}
    record_names = {
        side: {row["name"] for row in records if row["side"] == side}
        for side in ("left", "right")
    }
    if record_names["left"] != record_names["right"]:
        raise ValueError("build record filename sets differ")
    inventory = {
        "version": VERSION,
        "principal_files": principal,
        "record_files": records,
    }
    inventory_sha256 = sha256_json(inventory)
    design = {
        "version": VERSION,
        "purpose": "semantic differential of two audited algorithm variants",
        "left": str(datasets["left"]),
        "right": str(datasets["right"]),
        "algorithms": {side: configs[side].get("algorithm") for side in ("left", "right")},
        "record_count": len(record_names["left"]),
        "input_inventory_sha256": inventory_sha256,
        "phrase_exclusions": sorted(PHRASE_EXCLUSIONS),
        "result_artifacts": [
            "aggregate.json",
            "input_inventory.json",
            "raw_results.json",
            "run_log.json",
        ],
        "claim_boundary": "algorithm output differential only; no accuracy or musical-quality claim",
    }
    config = {
        "require_clean_bound_audits": True,
        "require_identical_source_identity": True,
        "require_identical_source_splits": True,
        "compare_rank_order": True,
        "compare_rank_order_within_kind": True,
        "report_cross_kind_global_rank_separately": True,
        "semantic_phrase_exclusions": sorted(PHRASE_EXCLUSIONS),
    }
    receipt = prepare_experiment(
        output,
        design=design,
        config=config,
        cases=[
            {
                "side": side,
                "path": str(datasets[side]),
                "algorithm": configs[side].get("algorithm"),
                "audit_sha256": principal_hashes[side]["audit.json"],
                "record_count": len(record_names[side]),
            }
            for side in ("left", "right")
        ],
        required_files=REQUIRED_FILES,
    )
    links = receipt_links(receipt)
    atomic_json(
        output / "input_inventory.json",
        {**links, **inventory, "input_inventory_sha256": inventory_sha256},
    )
    log = [{"event": "comparison_started", "record_count": len(record_names["left"])}]

    sources = {
        side: _read_sources(
            datasets[side] / "sources.jsonl",
            principal_hashes[side]["sources.jsonl"],
        )
        for side in ("left", "right")
    }
    if set(sources["left"]) != set(sources["right"]):
        raise ValueError("source manifest source ID sets differ")
    if set(sources["left"]) != {name.removesuffix(".json") for name in record_names["left"]}:
        raise ValueError("record filenames do not exactly cover the source manifest")
    for source_id in sorted(sources["left"]):
        left_source, right_source = sources["left"][source_id], sources["right"][source_id]
        if left_source["identity"] != right_source["identity"]:
            fields = _bounded_difference_paths(left_source["identity"], right_source["identity"])
            raise ValueError(f"source identity differs for {source_id}: {', '.join(fields)}")
        if (left_source["split"], left_source["split_group"]) != (
            right_source["split"], right_source["split_group"]
        ):
            raise ValueError(f"source split assignment differs for {source_id}")

    indexes = {
        side: _read_phrase_index(
            datasets[side] / "phrases.jsonl",
            principal_hashes[side]["phrases.jsonl"],
            sources[side],
        )
        for side in ("left", "right")
    }
    for side in ("left", "right"):
        audit = audits[side]
        if audit.get("source_files") != len(sources[side]):
            raise ValueError(f"audit source count mismatch: {side}")
        if audit.get("phrase_rows") != indexes[side]["row_count"]:
            raise ValueError(f"audit phrase count mismatch: {side}")
        for kind in KINDS:
            if audit.get("counts", {}).get(kind) != indexes[side]["counts"][kind]:
                raise ValueError(f"audit {kind} count mismatch: {side}")

    record_hashes = {(row["side"], row["name"]): row["sha256"] for row in records}
    changed: list[dict[str, Any]] = []
    changed_by_kind = {kind: [] for kind in KINDS}
    selected_counts = {side: Counter() for side in ("left", "right")}
    metrics = {
        side: {kind: defaultdict(list) for kind in KINDS}
        for side in ("left", "right")
    }
    outcome_counts: Counter[str] = Counter()
    rank_shifts = {kind: [] for kind in KINDS}

    for index, name in enumerate(sorted(record_names["left"])):
        source_id = name.removesuffix(".json")
        pair = {}
        for side in ("left", "right"):
            record = _read_record(
                datasets[side] / "records" / name,
                record_hashes[(side, name)],
            )
            if record.get("source_id") != source_id:
                raise ValueError(f"record filename/source ID mismatch: {side}/{name}")
            if sha256_json(record) != sources[side][source_id]["record_payload_sha256"]:
                raise ValueError(f"record differs from source manifest: {side}/{name}")
            if _source_identity(record) != sources[side][source_id]["identity"]:
                raise ValueError(f"record source identity differs from manifest: {side}/{name}")
            invalid_kinds = sorted(
                {
                    phrase.get("kind")
                    for phrase in record.get("phrases", [])
                    if phrase.get("kind") not in KINDS
                },
                key=repr,
            )
            if invalid_kinds:
                raise ValueError(f"record contains unsupported phrase kind: {side}/{name}")
            pair[side] = record
        outcome_counts[f"{pair['left'].get('status')}:{pair['left'].get('outcome')}"] += 1

        source_change = {
            "source_id": source_id,
            "source_path": pair["left"].get("source_path"),
            "kinds": {},
        }
        for kind in KINDS:
            left_raw = [row for row in pair["left"].get("phrases", []) if row.get("kind") == kind]
            right_raw = [row for row in pair["right"].get("phrases", []) if row.get("kind") == kind]
            left_phrases = semantic_phrases(pair["left"], kind)
            right_phrases = semantic_phrases(pair["right"], kind)
            for shift in global_rank_shifts(left_raw, right_raw):
                rank_shifts[kind].append({"source_id": source_id, **shift})
            selected_counts["left"][kind] += len(left_phrases)
            selected_counts["right"][kind] += len(right_phrases)
            _collect_metrics(metrics["left"][kind], left_phrases)
            _collect_metrics(metrics["right"][kind], right_phrases)
            if left_phrases != right_phrases:
                changed_by_kind[kind].append(source_id)
                left_families = [row.get("family_id") for row in left_phrases]
                right_families = [row.get("family_id") for row in right_phrases]
                source_change["kinds"][kind] = {
                    "left_semantic_sha256": sha256_json(left_phrases),
                    "right_semantic_sha256": sha256_json(right_phrases),
                    "difference_paths": _bounded_difference_paths(left_phrases, right_phrases),
                    "left_selection_trace": selection_trace(left_phrases),
                    "right_selection_trace": selection_trace(right_phrases),
                    "left_only_family_ids": sorted(set(left_families) - set(right_families)),
                    "right_only_family_ids": sorted(set(right_families) - set(left_families)),
                    "family_order_equal": left_families == right_families,
                }
        if source_change["kinds"]:
            changed.append(source_change)
        if (index + 1) % 1000 == 0:
            print(json.dumps({"records_compared": index + 1, "total": len(record_names["left"])}), flush=True)

    for side in ("left", "right"):
        for kind in KINDS:
            if selected_counts[side][kind] != indexes[side]["counts"][kind]:
                raise ValueError(f"record and phrase manifest {kind} counts differ: {side}")

    raw = {
        **links,
        "version": VERSION,
        "algorithms": design["algorithms"],
        "phrase_exclusions": sorted(PHRASE_EXCLUSIONS),
        "changed_sources": changed,
        "global_rank_shifts": rank_shifts,
    }
    aggregate = {
        **links,
        "version": VERSION,
        "algorithms": design["algorithms"],
        "inputs": {
            "record_count_each": len(record_names["left"]),
            "input_inventory_sha256": inventory_sha256,
            "audits": {
                side: {
                    "audit_sha256": principal_hashes[side]["audit.json"],
                    "reextraction_required": audits[side].get("reextraction_required"),
                    **{field: audits[side][field] for field in AUDIT_BINDINGS},
                }
                for side in ("left", "right")
            },
        },
        "source_outcomes": dict(sorted(outcome_counts.items())),
        "changed_sources_any_kind": len(changed),
        "semantic_phrase_changes": {
            kind: {
                "changed_source_count": len(changed_by_kind[kind]),
                "changed_source_ids": changed_by_kind[kind],
                "left_selected_phrase_count": selected_counts["left"][kind],
                "right_selected_phrase_count": selected_counts["right"][kind],
                "selected_phrase_count_delta": (
                    selected_counts["right"][kind] - selected_counts["left"][kind]
                ),
            }
            for kind in KINDS
        },
        "selection_metric_deltas": _summarize_metrics(metrics),
        "family_comparison": _family_comparison(indexes),
        "phrase_family_exclusions": _exclusion_comparison(indexes),
        "global_rank_shifts": {
            kind: {"count": len(rank_shifts[kind])}
            for kind in KINDS
        },
        "source_split_counts": dict(Counter(row["split"] for row in sources["left"].values())),
        "phrase_split_counts": {
            side: dict(indexes[side]["split_counts"])
            for side in ("left", "right")
        },
        "excluded_fields": sorted(PHRASE_EXCLUSIONS),
        "claim_boundary": "output selection differential only; no accuracy or perceptual claim",
    }
    log.append({
        "event": "comparison_finished",
        "records_compared": len(record_names["left"]),
        "changed_sources": len(changed),
    })

    _recheck(principal, datasets)
    _recheck(records, datasets)
    atomic_json(output / "raw_results.json", raw)
    atomic_json(output / "aggregate.json", aggregate)
    atomic_json(output / "run_log.json", {**links, "version": VERSION, "events": log})
    complete_experiment(output)
    return aggregate


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--left", type=Path, required=True)
    parser.add_argument("--right", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(compare_variants(args.left, args.right, args.output), indent=2))


if __name__ == "__main__":
    main()
