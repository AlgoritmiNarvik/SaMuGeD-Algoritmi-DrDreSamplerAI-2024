"""Make a supplementary split view from heuristic duplicate candidates.

Original source and phrase manifests stay unchanged. Whole original split
groups in later splits are quarantined when linked to an earlier split.
This is a sensitivity view, not a claim that all duplicate songs are known.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
import math
from pathlib import Path
import re
import shutil

from samuged.dataset import _Union, atomic_json, canonical_json, file_digest


SPLITS = ("train", "validation", "test")
BASE_PHRASE_SPLITS = (*SPLITS, "overlap_excluded")
SCREENING_ARTIFACTS = (
    "source_splits.jsonl",
    "phrase_splits.jsonl",
    "candidate_edges.jsonl",
    "duplicate_report.json",
)
SCREENING_POLICY = "quarantine whole original groups in later splits; train before validation before test"
SCREENING_CLAIM = "supplementary leakage sensitivity view based on heuristic melodic duplicate candidates"
HEX64 = re.compile(r"^[0-9a-f]{64}$")


def _rows(path: Path):
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                yield json.loads(line)


def _read_rows(path: Path, label: str) -> list[dict]:
    if not path.is_file():
        raise ValueError(f"missing screening artifact: {label}")
    rows = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").split("\n"), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSON in {label} line {line_number}") from exc
        if not isinstance(row, dict):
            raise ValueError(f"screening artifact row is not an object: {label} line {line_number}")
        rows.append(row)
    return rows


def _screening_artifact(screening: Path, name: str) -> Path:
    """Resolve a fixed artifact name without following an escape or symlink."""
    path = screening / name
    if path.is_symlink():
        raise ValueError(f"screening artifact must be a regular file: {name}")
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise ValueError(f"missing screening artifact: {name}") from exc
    if not resolved.is_file() or not resolved.is_relative_to(screening):
        raise ValueError(f"screening artifact escapes output: {name}")
    return resolved


def _require_hex64(value: object, label: str) -> None:
    if not isinstance(value, str) or not HEX64.fullmatch(value):
        raise ValueError(f"invalid {label}")


def _require_counter(value: object, expected: Counter, label: str) -> None:
    if (not isinstance(value, dict)
            or set(value) != set(expected)
            or any(type(item) is not int or item < 0 for item in value.values())
            or any(value[key] != expected[key] for key in expected)):
        raise ValueError(f"{label} does not match reconstructed counts")


def _validate_candidate_edges(rows: list[dict], sources: dict[str, dict], groups: dict[str, str]):
    required = {
        "left_source_id", "right_source_id", "left_split_group", "right_split_group",
        "symbolic_near_duplicate", "exact_arrangement", "exact_bytes",
        "shared_rare_shingles", "jaccard", "containment",
    }
    seen = set()
    edges = []
    for index, row in enumerate(rows, 1):
        if set(row) != required:
            raise ValueError(f"candidate edge {index} has an unexpected field set")
        left_id, right_id = row["left_source_id"], row["right_source_id"]
        if not isinstance(left_id, str) or not isinstance(right_id, str) or left_id == right_id:
            raise ValueError(f"candidate edge {index} has invalid source endpoints")
        if left_id not in sources or right_id not in sources:
            raise ValueError(f"candidate edge {index} references an unknown source")
        left_group, right_group = row["left_split_group"], row["right_split_group"]
        if (left_group != sources[left_id]["split_group"]
                or right_group != sources[right_id]["split_group"]):
            raise ValueError(f"candidate edge {index} has a source group mismatch")
        pair = tuple(sorted((left_id, right_id)))
        if pair in seen:
            raise ValueError("candidate edge endpoints are not one-to-one")
        seen.add(pair)
        flags = [row[name] for name in
                 ("symbolic_near_duplicate", "exact_arrangement", "exact_bytes")]
        if any(type(flag) is not bool for flag in flags) or not any(flags):
            raise ValueError(f"candidate edge {index} is not a strong edge")
        shared = row["shared_rare_shingles"]
        if type(shared) is not int or shared < 0:
            raise ValueError(f"candidate edge {index} has invalid shared shingle count")
        for name in ("jaccard", "containment"):
            value = row[name]
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"candidate edge {index} has invalid {name}")
            if not math.isfinite(value) or not 0 <= value <= 1:
                raise ValueError(f"candidate edge {index} has invalid {name}")
        edges.append(row)
    return edges


def _report_edges(report: dict, sources: dict[str, dict], groups: dict[str, str],
                  source_count: int) -> list[dict]:
    """Rebuild the screening edge projection from the copied report evidence."""
    if not isinstance(report, dict):
        raise ValueError("duplicate report must be an object")
    if report.get("manifest_sha256") is None:
        raise ValueError("duplicate report is missing its manifest hash")
    method_key = report.get("method_key")
    if not isinstance(method_key, str) or not method_key:
        raise ValueError("duplicate report is missing its method key")
    if report.get("fingerprint_method_key_counts") != {method_key: source_count}:
        raise ValueError("duplicate fingerprints must use one recorded method for every source")
    generation = report.get("generation")
    if not isinstance(generation, dict):
        raise ValueError("duplicate report is missing generation metadata")
    limit_fields = (
        "pair_generation_limit_reached",
        "pair_verification_limit_reached",
        "candidate_report_limit_reached",
    )
    if any(generation.get(key) is not False for key in limit_fields):
        raise ValueError("duplicate candidate audit reached a global pair or report limit")
    candidates = report.get("candidates")
    if not isinstance(candidates, list):
        raise ValueError("duplicate report candidates must be a list")
    source_by_path = {source["source_path"]: source for source in sources.values()}
    edges = []
    for index, candidate in enumerate(candidates, 1):
        if not isinstance(candidate, dict):
            raise ValueError(f"duplicate candidate {index} is not an object")
        flags = []
        for name in ("symbolic_near_duplicate", "exact_arrangement", "exact_bytes"):
            value = candidate.get(name)
            if type(value) is not bool:
                raise ValueError(f"duplicate candidate {index} has invalid {name}")
            flags.append(value)
        if not any(flags):
            continue
        sides = []
        for side in ("left", "right"):
            path = candidate.get(f"{side}_source_path")
            digest = candidate.get(f"{side}_source_sha256")
            split = candidate.get(f"{side}_split")
            source = source_by_path.get(path) if isinstance(path, str) else None
            if source is None or source["source_sha256"] != digest:
                raise ValueError(f"duplicate candidate {index} source hash or path mismatch")
            if source["split"] != split:
                raise ValueError(f"duplicate candidate {index} split differs from source manifest")
            sides.append(source)
        if sides[0]["source_id"] == sides[1]["source_id"]:
            raise ValueError(f"duplicate candidate {index} has identical endpoints")
        edges.append({
            "left_source_id": sides[0]["source_id"],
            "right_source_id": sides[1]["source_id"],
            "left_split_group": sides[0]["split_group"],
            "right_split_group": sides[1]["split_group"],
            "symbolic_near_duplicate": flags[0],
            "exact_arrangement": flags[1],
            "exact_bytes": flags[2],
            "shared_rare_shingles": candidate.get("shared_rare_shingles"),
            "jaccard": candidate.get("jaccard"),
            "containment": candidate.get("containment"),
        })
    return _validate_candidate_edges(edges, sources, groups)


def verify_screening(dataset: Path, screening: Path) -> dict:
    """Validate a derived screening view against its immutable base dataset.

    The verifier reconstructs strong edges from the copied duplicate report,
    checks the edge projection against that reconstruction and then checks
    both mapping artifacts against the original manifests. It returns the
    validated summary object and raises ``ValueError`` on any mismatch.
    """
    try:
        dataset = Path(dataset).resolve(strict=True)
        screening = Path(screening).resolve(strict=True)
    except OSError as exc:
        raise ValueError("dataset and screening paths must exist") from exc
    if not dataset.is_dir() or not screening.is_dir():
        raise ValueError("dataset and screening must be directories")
    try:
        dataset_summary = json.loads((dataset / "summary.json").read_text(encoding="utf-8"))
        summary = json.loads((screening / "summary.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("invalid dataset or screening summary") from exc
    if not isinstance(dataset_summary, dict) or not isinstance(summary, dict):
        raise ValueError("dataset and screening summaries must be objects")
    if summary.get("schema_version") != "samuged-split-screening-v1":
        raise ValueError("unsupported screening schema version")
    if summary.get("run_key") != dataset_summary.get("run_key"):
        raise ValueError("screening belongs to a different extraction run")
    if summary.get("policy") != SCREENING_POLICY or summary.get("claim_boundary") != SCREENING_CLAIM:
        raise ValueError("screening policy or claim boundary mismatch")

    source_manifest = dataset / "sources.jsonl"
    phrase_manifest = dataset / "phrases.jsonl"
    source_hash = file_digest(source_manifest)
    phrase_hash = file_digest(phrase_manifest)
    if (source_hash != dataset_summary.get("source_manifest_sha256")
            or phrase_hash != dataset_summary.get("phrase_manifest_sha256")):
        raise ValueError("base manifest hash does not match dataset summary")
    if summary.get("source_manifest_sha256") != source_hash:
        raise ValueError("screening source manifest hash mismatch")
    if summary.get("phrase_manifest_sha256") != phrase_hash:
        raise ValueError("screening phrase manifest hash mismatch")
    for field in ("duplicate_report_sha256", "duplicate_method_key"):
        if not isinstance(summary.get(field), str) or not summary[field]:
            raise ValueError(f"missing screening provenance field: {field}")
    _require_hex64(summary["duplicate_report_sha256"], "duplicate report hash")
    script_provenance = summary.get("script_provenance")
    if (not isinstance(script_provenance, dict)
            or script_provenance.get("status") != "unverified_creation_metadata"
            or script_provenance.get("path") != "scripts/screen_splits.py"):
        raise ValueError("invalid screening script provenance")
    _require_hex64(script_provenance.get("sha256"), "screening script creation hash")

    base_sources = _read_rows(source_manifest, "sources.jsonl")
    if len(base_sources) != dataset_summary.get("source_files"):
        raise ValueError("source count differs from dataset summary")
    sources = {}
    source_paths = set()
    groups = {}
    for row in base_sources:
        required = ("source_id", "source_path", "source_sha256", "split_group", "split")
        if any(key not in row for key in required):
            raise ValueError("source manifest row is missing screening identity fields")
        source_id = row["source_id"]
        if not isinstance(source_id, str) or not source_id or source_id in sources:
            raise ValueError("source manifest has duplicate or invalid source_id")
        if not isinstance(row["source_path"], str) or row["source_path"] in source_paths:
            raise ValueError("source manifest has duplicate or invalid source_path")
        if row["split"] not in SPLITS or not isinstance(row["split_group"], str):
            raise ValueError("source manifest has invalid split or split_group")
        if row["split_group"] in groups and groups[row["split_group"]] != row["split"]:
            raise ValueError("one original group has multiple splits")
        sources[source_id] = row
        source_paths.add(row["source_path"])
        groups[row["split_group"]] = row["split"]

    base_phrases = _read_rows(phrase_manifest, "phrases.jsonl")
    phrase_by_id = {}
    for row in base_phrases:
        phrase_id = row.get("phrase_id")
        source_id = row.get("source_id")
        if not isinstance(phrase_id, str) or not phrase_id or phrase_id in phrase_by_id:
            raise ValueError("phrase manifest has duplicate or invalid phrase_id")
        if not isinstance(source_id, str) or source_id not in sources:
            raise ValueError("phrase manifest references an unknown source")
        source = sources[source_id]
        split = row.get("split")
        if split not in BASE_PHRASE_SPLITS or split not in (source["split"], "overlap_excluded"):
            raise ValueError("phrase split does not match its source split")
        if row.get("split_group") != source["split_group"]:
            raise ValueError("phrase and source split groups differ")
        for key in ("source_sha256", "source_path"):
            if key in row and row[key] != source[key]:
                raise ValueError(f"phrase source {key} mismatch")
        if "source_split" in row and row["source_split"] != source["split"]:
            raise ValueError("phrase source_split does not match source split")
        phrase_by_id[phrase_id] = row

    report_path = _screening_artifact(screening, "duplicate_report.json")
    if file_digest(report_path) != summary["duplicate_report_sha256"]:
        raise ValueError("duplicate report artifact hash mismatch")
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("invalid duplicate report artifact") from exc
    if report.get("manifest_sha256") != source_hash:
        raise ValueError("duplicate report manifest hash mismatch")
    if report.get("method_key") != summary["duplicate_method_key"]:
        raise ValueError("duplicate report method key mismatch")
    report_edges = _report_edges(report, sources, groups, len(sources))
    edge_rows = _read_rows(_screening_artifact(screening, "candidate_edges.jsonl"),
                           "candidate_edges.jsonl")
    edges = _validate_candidate_edges(edge_rows, sources, groups)
    if edges != report_edges:
        raise ValueError("candidate edge artifact does not match duplicate report")
    union = _Union(groups)
    for edge in edges:
        union.join(edge["left_split_group"], edge["right_split_group"])
    preferred = {}
    for group, split in groups.items():
        component = union.find(group)
        preferred[component] = min(preferred.get(component, len(SPLITS)), SPLITS.index(split))
    excluded = {group for group, split in groups.items()
                if SPLITS.index(split) != preferred[union.find(group)]}

    source_rows = _read_rows(_screening_artifact(screening, "source_splits.jsonl"),
                             "source_splits.jsonl")
    if len(source_rows) != len(sources):
        raise ValueError("screening source row count mismatch")
    seen_source_ids = set()
    source_counts = Counter()
    for row in source_rows:
        expected_keys = {"source_id", "source_path", "source_sha256", "split_group",
                         "split", "original_split", "screened_split", "screening_component"}
        if set(row) != expected_keys:
            raise ValueError("screening source row has an unexpected field set")
        source_id = row["source_id"]
        if source_id in seen_source_ids or source_id not in sources:
            raise ValueError("screening source rows are not one-to-one with sources")
        seen_source_ids.add(source_id)
        source = sources[source_id]
        expected = {
            "source_id": source_id,
            "source_path": source["source_path"],
            "source_sha256": source["source_sha256"],
            "split_group": source["split_group"],
            "split": source["split"],
            "original_split": source["split"],
            "screened_split": "duplicate_excluded" if source["split_group"] in excluded else source["split"],
            "screening_component": union.find(source["split_group"]),
        }
        if row != expected:
            raise ValueError(f"screening source mapping mismatch: {source_id}")
        source_counts[row["screened_split"]] += 1
    if seen_source_ids != set(sources):
        raise ValueError("screening source rows omit a source")

    phrase_rows = _read_rows(_screening_artifact(screening, "phrase_splits.jsonl"),
                             "phrase_splits.jsonl")
    if len(phrase_rows) != len(phrase_by_id):
        raise ValueError("screening phrase row count mismatch")
    seen_phrase_ids = set()
    phrase_counts = Counter()
    newly_excluded = Counter()
    already_excluded = 0
    for row in phrase_rows:
        expected_keys = {"phrase_id", "source_id", "kind", "original_split",
                         "screened_split", "split_group", "screening_component"}
        if set(row) != expected_keys:
            raise ValueError("screening phrase row has an unexpected field set")
        phrase_id = row["phrase_id"]
        if phrase_id in seen_phrase_ids or phrase_id not in phrase_by_id:
            raise ValueError("screening phrase rows are not one-to-one with phrases")
        seen_phrase_ids.add(phrase_id)
        phrase = phrase_by_id[phrase_id]
        source = sources[phrase["source_id"]]
        group = source["split_group"]
        expected_screen = phrase["split"]
        if group in excluded and phrase["split"] != "overlap_excluded":
            expected_screen = "duplicate_excluded"
            newly_excluded[phrase["split"]] += 1
        elif group in excluded:
            already_excluded += 1
        expected = {
            "phrase_id": phrase_id,
            "source_id": phrase["source_id"],
            "kind": phrase["kind"],
            "original_split": phrase["split"],
            "screened_split": expected_screen,
            "split_group": group,
            "screening_component": union.find(group),
        }
        if row != expected:
            raise ValueError(f"screening phrase mapping mismatch: {phrase_id}")
        phrase_counts[row["screened_split"]] += 1
    if seen_phrase_ids != set(phrase_by_id):
        raise ValueError("screening phrase rows omit a phrase")

    retained_cross_split = 0
    for edge in edges:
        left, right = edge["left_split_group"], edge["right_split_group"]
        if groups[left] != groups[right] and left not in excluded and right not in excluded:
            retained_cross_split += 1
    if retained_cross_split:
        raise ValueError("screening retains a cross-split candidate edge")

    _require_counter(summary.get("source_split_counts"), source_counts, "source split counts")
    _require_counter(summary.get("phrase_split_counts"), phrase_counts, "phrase split counts")
    _require_counter(summary.get("newly_excluded_phrase_counts"), newly_excluded,
                     "newly excluded phrase counts")
    if summary.get("candidate_edges") != len(edges):
        raise ValueError("screening candidate edge count mismatch")
    if summary.get("excluded_source_groups") != len(excluded):
        raise ValueError("screening excluded group count mismatch")
    if summary.get("already_family_excluded_phrases_in_quarantined_groups") != already_excluded:
        raise ValueError("screening pre-existing exclusion count mismatch")
    if summary.get("retained_cross_split_candidate_edges") != retained_cross_split:
        raise ValueError("screening retained edge count mismatch")
    artifacts = summary.get("artifacts")
    if not isinstance(artifacts, dict) or set(artifacts) != set(SCREENING_ARTIFACTS):
        raise ValueError("screening artifact inventory mismatch")
    for name in SCREENING_ARTIFACTS:
        _require_hex64(artifacts[name], f"{name} hash")
        if file_digest(_screening_artifact(screening, name)) != artifacts[name]:
            raise ValueError(f"screening artifact hash mismatch: {name}")
    return summary


def screen(dataset: Path, duplicate_report: Path, output: Path) -> dict:
    dataset = dataset.resolve(strict=True)
    duplicate_report = duplicate_report.resolve(strict=True)
    if not duplicate_report.is_file():
        raise ValueError("duplicate report must be a file")
    output = output.resolve()
    if output == dataset or output.is_relative_to(dataset):
        raise ValueError("screening output must be outside the extraction directory")
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError("screening output must be new or empty")
    summary = json.loads((dataset/"summary.json").read_text())
    report = json.loads(duplicate_report.read_text())
    source_hash = file_digest(dataset/"sources.jsonl")
    phrase_hash = file_digest(dataset/"phrases.jsonl")
    if (source_hash != summary["source_manifest_sha256"]
            or phrase_hash != summary["phrase_manifest_sha256"]
            or report.get("manifest_sha256") != source_hash):
        raise ValueError("input manifest hashes do not agree")
    generation = report.get("generation")
    if (not isinstance(generation, dict)
            or any(generation.get(key) is not False for key in (
                "pair_generation_limit_reached",
                "pair_verification_limit_reached",
                "candidate_report_limit_reached",
            ))):
        raise ValueError("duplicate candidate audit reached a global pair or report limit")
    keys = report.get("fingerprint_method_key_counts", {})
    if keys != {report.get("method_key"): summary["source_files"]}:
        raise ValueError("duplicate fingerprints must use one recorded method for every source")
    sources = {}
    source_by_id = {}
    for row in _rows(dataset/"sources.jsonl"):
        selected = {key: row[key] for key in
                    ("source_id", "source_path", "source_sha256", "split_group", "split")}
        if (selected["source_path"] in sources or selected["source_id"] in source_by_id
                or selected["split"] not in SPLITS):
            raise ValueError("duplicate path or invalid source split")
        sources[selected["source_path"]] = selected
        source_by_id[selected["source_id"]] = selected
    if len(sources) != summary["source_files"]:
        raise ValueError("source count differs from summary")
    groups = {}
    for source in sources.values():
        group, split = source["split_group"], source["split"]
        if group in groups and groups[group] != split:
            raise ValueError("one original group has multiple splits")
        groups[group] = split
    union = _Union(groups)
    edges = _report_edges(report, source_by_id, groups, len(sources))
    for edge in edges:
        union.join(edge["left_split_group"], edge["right_split_group"])
    preferred = {}
    for group, split in groups.items():
        component = union.find(group)
        preferred[component] = min(preferred.get(component, 3), SPLITS.index(split))
    excluded = {group for group, split in groups.items()
                if SPLITS.index(split) != preferred[union.find(group)]}
    for edge in edges:
        left, right = edge["left_split_group"], edge["right_split_group"]
        if left not in excluded and right not in excluded and groups[left] != groups[right]:
            raise AssertionError("retained duplicate edge crosses splits")
    output.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(duplicate_report, output / "duplicate_report.json")
    source_counts = Counter()
    with (output/"source_splits.jsonl").open("w", encoding="utf-8") as stream:
        for source in sorted(sources.values(), key=lambda row: row["source_path"]):
            split = "duplicate_excluded" if source["split_group"] in excluded else source["split"]
            source_counts[split] += 1
            stream.write(canonical_json({**source, "original_split": source["split"],
                "screened_split": split, "screening_component": union.find(source["split_group"])})+"\n")
    phrase_counts, newly_excluded, already_excluded = Counter(), Counter(), 0
    with (output/"phrase_splits.jsonl").open("w", encoding="utf-8") as stream:
        for phrase in _rows(dataset/"phrases.jsonl"):
            source = source_by_id[phrase["source_id"]]
            split = phrase["split"]
            if phrase["split_group"] != source["split_group"]:
                raise ValueError("phrase and source split groups differ")
            if source["split_group"] in excluded:
                if split == "overlap_excluded":
                    already_excluded += 1
                else:
                    newly_excluded[split] += 1
                    split = "duplicate_excluded"
            phrase_counts[split] += 1
            stream.write(canonical_json({"phrase_id": phrase["phrase_id"],
                "source_id": phrase["source_id"], "kind": phrase["kind"],
                "original_split": phrase["split"], "screened_split": split,
                "split_group": source["split_group"],
                "screening_component": union.find(source["split_group"])})+"\n")
    with (output/"candidate_edges.jsonl").open("w", encoding="utf-8") as stream:
        for edge in edges:
            stream.write(canonical_json(edge)+"\n")
    result = {"schema_version": "samuged-split-screening-v1", "run_key": summary["run_key"],
        "policy": SCREENING_POLICY,
        "claim_boundary": SCREENING_CLAIM,
        "source_manifest_sha256": source_hash, "phrase_manifest_sha256": phrase_hash,
        "duplicate_report_sha256": file_digest(duplicate_report), "duplicate_method_key": report["method_key"],
        "script_provenance": {
            "status": "unverified_creation_metadata",
            "path": "scripts/screen_splits.py",
            "sha256": file_digest(Path(__file__)),
        },
        "candidate_edges": len(edges),
        "excluded_source_groups": len(excluded), "source_split_counts": dict(source_counts),
        "phrase_split_counts": dict(phrase_counts), "newly_excluded_phrase_counts": dict(newly_excluded),
        "already_family_excluded_phrases_in_quarantined_groups": already_excluded,
        "retained_cross_split_candidate_edges": 0,
        "artifacts": {name: file_digest(output/name) for name in SCREENING_ARTIFACTS}}
    atomic_json(output/"summary.json", result)
    return verify_screening(dataset, output)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--duplicate-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(screen(args.dataset, args.duplicate_report, args.output), indent=2))
