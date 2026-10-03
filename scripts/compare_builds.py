"""Compare two complete SaMuGeD builds without loading their manifests at once."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Iterable

from samuged.dataset import atomic_json
from samuged.experiment import (
    complete_experiment,
    prepare_experiment,
    receipt_links,
    sha256_json,
)


VERSION = "reference-build-comparison-v1"
KINDS = ("melodic", "percussion")
PHRASE_EXCLUSIONS = frozenset({"phrase_id", "midi_path", "split", "split_group"})
MANIFEST_ONLY_FIELDS = frozenset({"split", "split_group"})
PART_TELEMETRY_FIELDS = frozenset({"comparisons", "exact_cache_hits"})
REQUIRED_FILES = (
    "scripts/compare_builds.py",
    "samuged/dataset.py",
    "samuged/experiment.py",
    "pyproject.toml",
    "requirements-research.lock",
)
PRINCIPAL_FILES = ("sources.jsonl", "phrases.jsonl", "summary.json", "build_config.json")


def semantic_phrase(phrase: dict[str, Any]) -> dict[str, Any]:
    """Remove only build-derived artifact identifiers from a phrase payload."""
    return {key: value for key, value in phrase.items() if key not in PHRASE_EXCLUSIONS}


def semantic_phrases(record: dict[str, Any], kind: str) -> list[dict[str, Any]]:
    return [semantic_phrase(row) for row in record.get("phrases", []) if row.get("kind") == kind]


def _record_manifest_payload(row: dict[str, Any]) -> dict[str, Any]:
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


def _hash_file(path: Path) -> dict[str, Any]:
    digest = sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return {"path": path.name, "bytes": size, "sha256": digest.hexdigest()}


def _record_inventory(dataset: Path, label: str) -> list[dict[str, Any]]:
    records = dataset / "records"
    if not records.is_dir():
        raise FileNotFoundError(f"missing records directory: {records}")
    entries = []
    for path in sorted(records.glob("*.json"), key=lambda item: item.name):
        entry = _hash_file(path)
        entries.append({"dataset": label, "name": path.name, **{k: entry[k] for k in ("bytes", "sha256")}})
    return entries


def _principal_inventory(dataset: Path, label: str) -> list[dict[str, Any]]:
    entries = []
    for name in PRINCIPAL_FILES:
        path = dataset / name
        if not path.is_file():
            raise FileNotFoundError(f"missing build artifact: {path}")
        item = _hash_file(path)
        entries.append({"dataset": label, **item})
    audit = dataset / "audit.json"
    if audit.is_file():
        item = _hash_file(audit)
        entries.append({"dataset": label, **item})
    return entries


def _read_manifest(path: Path, expected_sha256: str) -> dict[str, dict[str, Any]]:
    digest = sha256()
    rows: dict[str, dict[str, Any]] = {}
    with path.open("rb") as stream:
        for line_number, line in enumerate(stream, 1):
            digest.update(line)
            if not line.strip():
                continue
            row = json.loads(line)
            source_id = row.get("source_id")
            if not isinstance(source_id, str) or source_id in rows:
                raise ValueError(f"invalid or duplicate source_id at {path}:{line_number}")
            rows[source_id] = {
                "source_id": source_id,
                "source_path": row.get("source_path"),
                "source_sha256": row.get("source_sha256"),
                "status": row.get("status"),
                "outcome": row.get("outcome"),
                "split": row.get("split"),
                "split_group": row.get("split_group"),
                "metadata_repairs": row.get("metadata_repairs", []),
                "record_payload_sha256": sha256_json(_record_manifest_payload(row)),
            }
    if digest.hexdigest() != expected_sha256:
        raise ValueError(f"manifest changed while reading: {path}")
    return rows


def _read_phrase_index(path: Path, expected_sha256: str) -> dict[str, Any]:
    digest = sha256()
    memberships = {kind: defaultdict(set) for kind in KINDS}
    splits = {kind: defaultdict(set) for kind in KINDS}
    counts: Counter[str] = Counter()
    split_counts: Counter[str] = Counter()
    with path.open("rb") as stream:
        for line_number, line in enumerate(stream, 1):
            digest.update(line)
            if not line.strip():
                continue
            row = json.loads(line)
            kind = row.get("kind")
            family = row.get("family_id")
            source_id = row.get("source_id")
            split = row.get("split")
            if kind not in KINDS or not all(
                isinstance(value, str) for value in (family, source_id, split)
            ):
                raise ValueError(f"invalid phrase index row at {path}:{line_number}")
            memberships[kind][family].add(source_id)
            splits[kind][family].add(split)
            counts[kind] += 1
            split_counts[split] += 1
    if digest.hexdigest() != expected_sha256:
        raise ValueError(f"phrase manifest changed while reading: {path}")
    return {
        "memberships": memberships,
        "splits": splits,
        "counts": counts,
        "split_counts": split_counts,
    }


def _read_bound_record(path: Path, expected_sha256: str) -> dict[str, Any]:
    payload = path.read_bytes()
    if sha256(payload).hexdigest() != expected_sha256:
        raise ValueError(f"record changed after input freeze: {path}")
    value = json.loads(payload)
    if not isinstance(value, dict):
        raise ValueError(f"record is not an object: {path}")
    return value


def _normal_part_stats(record: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {key: value for key, value in row.items() if key not in PART_TELEMETRY_FIELDS}
        for row in record.get("part_stats", [])
    ]


def _phrase_descriptor(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "count": len(rows),
        "semantic_sha256": sha256_json(rows),
        "family_ids": [row.get("family_id") for row in rows],
        "midi_sha256": [row.get("midi_sha256") for row in rows],
    }


def _record_source_semantics(record: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "source_id", "source_path", "source_sha256", "source_bytes", "artist_from_path",
        "artist_key", "title_from_path", "song_key", "status", "outcome", "musical_sha256",
        "ticks_per_beat", "part_count", "note_count", "warnings", "metadata_repairs",
    )
    return {key: record.get(key) for key in keys if key in record}


def _family_summary(
    memberships: dict[str, dict[str, set[str]]],
    splits: dict[str, dict[str, set[str]]],
    left_label: str,
    right_label: str,
) -> dict[str, Any]:
    result = {}
    for kind in KINDS:
        left = memberships[left_label][kind]
        right = memberships[right_label][kind]
        common = set(left) & set(right)
        changed_membership = sorted(family for family in common if left[family] != right[family])
        result[kind] = {
            "left_family_count": len(left),
            "right_family_count": len(right),
            "common_family_count": len(common),
            "left_only_family_count": len(set(left) - set(right)),
            "right_only_family_count": len(set(right) - set(left)),
            "left_only_family_ids": sorted(set(left) - set(right)),
            "right_only_family_ids": sorted(set(right) - set(left)),
            "common_families_with_membership_changes": len(changed_membership),
            "membership_changed_family_ids": changed_membership,
            "left_active_multi_split_families": sum(
                len(values - {"overlap_excluded"}) > 1 for values in splits[left_label][kind].values()
            ),
            "right_active_multi_split_families": sum(
                len(values - {"overlap_excluded"}) > 1 for values in splits[right_label][kind].values()
            ),
            "left_families_with_excluded_members": sum(
                "overlap_excluded" in values for values in splits[left_label][kind].values()
            ),
            "right_families_with_excluded_members": sum(
                "overlap_excluded" in values for values in splits[right_label][kind].values()
            ),
        }
    return result


def _recheck_inputs(entries: Iterable[dict[str, Any]], datasets: dict[str, Path]) -> None:
    for entry in entries:
        base = datasets[entry["dataset"]]
        path = base / ("records" if "name" in entry else "") / entry.get("name", entry.get("path"))
        current = _hash_file(path)
        if current["bytes"] != entry["bytes"] or current["sha256"] != entry["sha256"]:
            raise ValueError(f"frozen comparison input changed: {path}")


def compare_builds(left: Path, right: Path, output: Path) -> dict[str, Any]:
    labels = ("v02", "v03")
    datasets = {"v02": left.resolve(), "v03": right.resolve()}
    principal = [
        entry for label in labels for entry in _principal_inventory(datasets[label], label)
    ]
    records = [entry for label in labels for entry in _record_inventory(datasets[label], label)]
    input_inventory = {
        "version": VERSION,
        "principal_files": principal,
        "record_files": records,
    }
    inventory_sha256 = sha256_json(input_inventory)
    record_names = {
        label: {entry["name"] for entry in records if entry["dataset"] == label}
        for label in labels
    }
    if record_names["v02"] != record_names["v03"]:
        raise ValueError("build record filename sets differ")

    design = {
        "version": VERSION,
        "purpose": "semantic differential of two complete local reference builds",
        "left": str(datasets["v02"]),
        "right": str(datasets["v03"]),
        "record_count": len(record_names["v02"]),
        "input_inventory_sha256": inventory_sha256,
        "phrase_exclusions": sorted(PHRASE_EXCLUSIONS),
        "manifest_only_fields": sorted(MANIFEST_ONLY_FIELDS),
        "result_artifacts": [
            "aggregate.json", "input_inventory.json", "raw_results.json", "run_log.json"
        ],
        "claim_boundary": (
            "artifact differential only; build audits and musical quality require separate evidence"
        ),
    }
    config = {
        "semantic_phrase_exclusions": sorted(PHRASE_EXCLUSIONS),
        "part_telemetry_fields": sorted(PART_TELEMETRY_FIELDS),
        "compare_phrase_order": True,
        "compare_export_midi_sha256": True,
    }
    receipt = prepare_experiment(
        output,
        design=design,
        config=config,
        cases=[
            {
                "dataset": label,
                "path": str(datasets[label]),
                "record_count": len(record_names[label]),
                "principal_files": [row for row in principal if row["dataset"] == label],
            }
            for label in labels
        ],
        required_files=REQUIRED_FILES,
    )
    links = receipt_links(receipt)
    atomic_json(output / "input_inventory.json", {**links, **input_inventory, "input_inventory_sha256": inventory_sha256})
    log = [{"event": "comparison_started", "record_count": len(record_names["v02"])}]

    principal_lookup = {(row["dataset"], row["path"]): row for row in principal}
    manifests = {
        label: _read_manifest(
            datasets[label] / "sources.jsonl",
            principal_lookup[(label, "sources.jsonl")]["sha256"],
        )
        for label in labels
    }
    phrase_indexes = {
        label: _read_phrase_index(
            datasets[label] / "phrases.jsonl",
            principal_lookup[(label, "phrases.jsonl")]["sha256"],
        )
        for label in labels
    }
    if set(manifests["v02"]) != set(manifests["v03"]):
        raise ValueError("source manifest source_id sets differ")
    record_hashes = {
        (entry["dataset"], entry["name"]): entry["sha256"] for entry in records
    }

    changes = []
    outcomes: Counter[str] = Counter()
    phrase_changes = {kind: [] for kind in KINDS}
    repaired = []
    split_changes, group_changes = [], []
    identity_mismatches = []
    source_semantic_changes = []
    drum_stat_changes = []
    nontelemetry_part_stat_changes = []
    source_split_counts = {label: Counter() for label in labels}
    search_limited = {label: 0 for label in labels}

    for index, name in enumerate(sorted(record_names["v02"])):
        source_id = name.removesuffix(".json")
        pair = {}
        for label in labels:
            record = _read_bound_record(
                datasets[label] / "records" / name, record_hashes[(label, name)]
            )
            if record.get("source_id") != source_id:
                raise ValueError(f"record filename/source_id mismatch: {label}/{name}")
            if sha256_json(record) != manifests[label][source_id]["record_payload_sha256"]:
                raise ValueError(f"record differs from frozen source manifest: {label}/{name}")
            pair[label] = record
            source_split_counts[label][manifests[label][source_id]["split"]] += 1
            search_limited[label] += bool(record.get("search_limited"))
            for phrase in record.get("phrases", []):
                kind = phrase.get("kind")
                if kind not in KINDS:
                    raise ValueError(f"unsupported phrase kind in {label}/{name}: {kind}")

        before, after = pair["v02"], pair["v03"]
        left_manifest, right_manifest = manifests["v02"][source_id], manifests["v03"][source_id]
        identity_keys = ("source_id", "source_path", "source_sha256", "source_bytes", "song_key")
        different_identity = [key for key in identity_keys if before.get(key) != after.get(key)]
        if different_identity:
            identity_mismatches.append({"source_id": source_id, "fields": different_identity})
        outcomes[f"{before.get('status')}:{before.get('outcome')}->{after.get('status')}:{after.get('outcome')}"] += 1
        if left_manifest["split"] != right_manifest["split"]:
            split_changes.append({
                "source_id": source_id, "source_path": before.get("source_path"),
                "before": left_manifest["split"], "after": right_manifest["split"],
            })
        if left_manifest["split_group"] != right_manifest["split_group"]:
            group_changes.append({
                "source_id": source_id, "source_path": before.get("source_path"),
                "before": left_manifest["split_group"], "after": right_manifest["split_group"],
            })
        if right_manifest["metadata_repairs"]:
            repaired.append({
                "source_id": source_id,
                "source_path": after.get("source_path"),
                "before_status": before.get("status"),
                "before_outcome": before.get("outcome"),
                "after_status": after.get("status"),
                "after_outcome": after.get("outcome"),
                "repair_events": len(right_manifest["metadata_repairs"]),
                "melodic_phrases": len(semantic_phrases(after, "melodic")),
                "percussion_phrases": len(semantic_phrases(after, "percussion")),
            })

        source_before = _record_source_semantics(before)
        source_after = _record_source_semantics(after)
        if source_before != source_after:
            source_semantic_changes.append({
                "source_id": source_id,
                "source_path": after.get("source_path", before.get("source_path")),
                "difference_paths": _bounded_difference_paths(source_before, source_after),
            })
        if before.get("drum_stats") != after.get("drum_stats"):
            drum_stat_changes.append(source_id)
        if _normal_part_stats(before) != _normal_part_stats(after):
            nontelemetry_part_stat_changes.append(source_id)

        source_change = {
            "source_id": source_id,
            "source_path": after.get("source_path", before.get("source_path")),
            "baseline_search_limited": bool(before.get("search_limited")),
            "updated_search_limited": bool(after.get("search_limited")),
            "repaired": bool(right_manifest["metadata_repairs"]),
            "kinds": {},
        }
        any_phrase_change = False
        for kind in KINDS:
            left_phrases = semantic_phrases(before, kind)
            right_phrases = semantic_phrases(after, kind)
            if left_phrases != right_phrases:
                any_phrase_change = True
                phrase_changes[kind].append(source_id)
                source_change["kinds"][kind] = {
                    "before": _phrase_descriptor(left_phrases),
                    "after": _phrase_descriptor(right_phrases),
                    "difference_paths": _bounded_difference_paths(left_phrases, right_phrases),
                }
        if any_phrase_change:
            if source_change["repaired"]:
                source_change["cause_class"] = "invalid_key_metadata_recovery"
            elif source_change["baseline_search_limited"]:
                source_change["cause_class"] = "cache_change_with_baseline_search_limit"
            else:
                source_change["cause_class"] = "cache_change_without_baseline_search_limit"
            changes.append(source_change)
        if (index + 1) % 1000 == 0:
            print(json.dumps({"records_compared": index + 1, "total": len(record_names["v02"])}), flush=True)

    memberships = {label: phrase_indexes[label]["memberships"] for label in labels}
    family_splits = {label: phrase_indexes[label]["splits"] for label in labels}
    family = _family_summary(memberships, family_splits, "v02", "v03")
    raw = {
        **links,
        "version": VERSION,
        "phrase_exclusions": sorted(PHRASE_EXCLUSIONS),
        "changed_sources": changes,
        "repaired_sources": repaired,
        "split_changes": split_changes,
        "split_group_changes": group_changes,
        "identity_mismatches": identity_mismatches,
        "source_semantic_changes": source_semantic_changes,
        "drum_stat_changed_source_ids": drum_stat_changes,
        "nontelemetry_part_stat_changed_source_ids": nontelemetry_part_stat_changes,
    }
    aggregate = {
        **links,
        "version": VERSION,
        "inputs": {
            "record_count_each": len(record_names["v02"]),
            "inventory_sha256": inventory_sha256,
            "principal_files": principal,
        },
        "source_outcome_transitions": dict(sorted(outcomes.items())),
        "metadata_recovery": {
            "repaired_sources": len(repaired),
            "repair_events": sum(row["repair_events"] for row in repaired),
            "repaired_source_ids": [row["source_id"] for row in repaired],
        },
        "semantic_phrase_changes": {
            kind: {
                "changed_sources": len(phrase_changes[kind]),
                "changed_source_ids": phrase_changes[kind],
                "changed_without_recovery": sum(
                    source_id not in {row["source_id"] for row in repaired}
                    for source_id in phrase_changes[kind]
                ),
                "changed_without_recovery_and_without_baseline_search_limit": sum(
                    row["cause_class"] == "cache_change_without_baseline_search_limit"
                    and kind in row["kinds"] for row in changes
                ),
            }
            for kind in KINDS
        },
        "phrase_counts": {label: dict(phrase_indexes[label]["counts"]) for label in labels},
        "search_limited_sources": search_limited,
        "split_changes": len(split_changes),
        "split_group_changes": len(group_changes),
        "source_split_counts": {label: dict(source_split_counts[label]) for label in labels},
        "phrase_split_counts": {
            label: dict(phrase_indexes[label]["split_counts"]) for label in labels
        },
        "family_comparison": family,
        "identity_mismatches": len(identity_mismatches),
        "source_semantic_changes": len(source_semantic_changes),
        "drum_stat_changes": len(drum_stat_changes),
        "nontelemetry_part_stat_changes": len(nontelemetry_part_stat_changes),
        "excluded_fields": {
            "phrase": sorted(PHRASE_EXCLUSIONS),
            "manifest_only": sorted(MANIFEST_ONLY_FIELDS),
            "part_telemetry": sorted(PART_TELEMETRY_FIELDS),
        },
    }
    log.append({
        "event": "comparison_finished",
        "records_compared": len(record_names["v02"]),
        "changed_sources": len(changes),
    })

    _recheck_inputs(principal, datasets)
    _recheck_inputs(records, datasets)
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
    print(json.dumps(compare_builds(args.left, args.right, args.output), indent=2))


if __name__ == "__main__":
    main()
