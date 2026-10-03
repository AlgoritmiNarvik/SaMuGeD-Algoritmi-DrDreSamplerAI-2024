"""Validate offline phrase ratings and summarize agreement.

The input packet and rating exports are treated as immutable evidence.  This
module deliberately does not infer or create a judgement for a missing field.
"""
from __future__ import annotations

import argparse
from collections import Counter
from hashlib import sha256
from html.parser import HTMLParser
import itertools
import json
from pathlib import Path
from pathlib import PurePosixPath
import re
import sys
from typing import Any, Iterable

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from samuged.dataset import atomic_json
from samuged.experiment import (
    complete_experiment,
    prepare_experiment,
    receipt_links,
    sha256_bytes,
    sha256_json,
)


PACKET_VERSION = "samuged-review-v3"
ANALYSIS_VERSION = "samuged-ratings-analysis-v1"
INPUT_SNAPSHOT_VERSION = "samuged-ratings-input-snapshot-v1"
KINDS = ("melodic", "percussion")
DIMENSIONS = ("same_phrase", "boundary_quality", "role", "salience")
ENUMS = {
    "same_phrase": frozenset(("yes", "no", "uncertain")),
    "boundary_quality": frozenset(("good", "partial", "poor")),
    "role": frozenset(("melody", "accompaniment", "percussion", "uncertain")),
    "salience": frozenset(("high", "medium", "low", "uncertain")),
}
RATING_FIELDS = frozenset(
    {
        "review_id",
        "candidate_id",
        "kind",
        "source_id",
        "source_sha256",
        "source_path",
        "split_group",
        "family_id",
        "metadata_repairs",
        *DIMENSIONS,
        "notes",
    }
)
HASH_RE = re.compile(r"^[0-9a-f]{64}$")
REPAIR_FIELDS = frozenset(
    {
        "kind",
        "track_index",
        "event_index",
        "tick",
        "offset_basis",
        "event_offset",
        "status_offset",
        "meta_type_offset",
        "payload_offset",
        "original_meta_type",
        "replacement_meta_type",
        "original_payload_hex",
        "reason",
        "original_smf_sha256",
        "recovered_smf_sha256",
    }
)


class _ReviewDataParser(HTMLParser):
    """Extract the one JSON script used by make_review.py."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self._capture = False
        self._parts: list[str] = []
        self.blocks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "script":
            return
        attrs_map = dict(attrs)
        if attrs_map.get("id") == "review-data":
            if self._capture:
                raise ValueError("review packet contains duplicate review-data scripts")
            self._capture = True
            self._parts = []

    def handle_data(self, data: str) -> None:
        if self._capture:
            self._parts.append(data)

    def handle_entityref(self, name: str) -> None:
        if self._capture:
            self._parts.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        if self._capture:
            self._parts.append(f"&#{name};")

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "script" and self._capture:
            self.blocks.append("".join(self._parts))
            self._capture = False


def _read_json(path: Path) -> tuple[bytes, Any]:
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise ValueError(f"cannot read input {path}: {exc}") from exc
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid JSON input {path}: {exc}") from exc
    return data, value


def _hash_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not HASH_RE.fullmatch(value):
        raise ValueError(f"{field} must be a lowercase SHA256 hex string")
    return value


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} must be a nonempty string")
    return value


def _script_packet(data: bytes) -> dict[str, Any]:
    parser = _ReviewDataParser()
    try:
        parser.feed(data.decode("utf-8"))
        parser.close()
    except (UnicodeDecodeError, ValueError) as exc:
        raise ValueError(f"invalid review HTML: {exc}") from exc
    if len(parser.blocks) != 1:
        raise ValueError("review HTML must contain exactly one review-data script")
    try:
        packet = json.loads(parser.blocks[0])
    except json.JSONDecodeError as exc:
        raise ValueError(f"review-data is not valid JSON: {exc.msg}") from exc
    if not isinstance(packet, dict):
        raise ValueError("review-data must contain a JSON object")
    return packet


def _validate_config(config: Any, candidates: list[dict[str, Any]]) -> dict[str, Any]:
    if not isinstance(config, dict):
        raise ValueError("packet config must be an object")
    required = {
        "requested_count",
        "selected_count",
        "eligible_kind_counts",
        "selected_kind_counts",
        "seed",
        "seed_digest",
        "selection",
        "sampling_constraints",
        "metadata_repair_policy",
        "source_manifest_sha256",
        "phrase_manifest_sha256",
        "excerpt_policy",
    }
    missing = sorted(required - config.keys())
    if missing:
        raise ValueError(f"packet config is missing fields: {', '.join(missing)}")
    for field in ("source_manifest_sha256", "phrase_manifest_sha256", "seed_digest"):
        _hash_text(config[field], f"config.{field}")
    if not isinstance(config["seed"], str) or not config["seed"]:
        raise ValueError("config.seed must be a nonempty string")
    if config["seed_digest"] != sha256(config["seed"].encode()).hexdigest():
        raise ValueError("config.seed_digest does not match config.seed")
    expected_text = {
        "selection": "deterministic hash rank, alternating melodic and percussion when available",
        "metadata_repair_policy": "strict parsing unless the source manifest carries an exact metadata_repairs receipt",
        "excerpt_policy": "source MIDI prototype and up to two other distinct recorded intervals, exact melodic note indices, source tempo map",
    }
    for field, expected in expected_text.items():
        _text(config[field], f"config.{field}")
        if config[field] != expected:
            raise ValueError(f"config.{field} does not match make_review.py")
    for field in ("requested_count", "selected_count"):
        value = config[field]
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError(f"config.{field} must be a positive integer")
    if config["selected_count"] != len(candidates):
        raise ValueError("config.selected_count does not match packet candidates")
    for field in ("eligible_kind_counts", "selected_kind_counts"):
        counts = config[field]
        if not isinstance(counts, dict) or any(key not in KINDS for key in counts):
            raise ValueError(f"config.{field} must be a kind count object")
        if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in counts.values()):
            raise ValueError(f"config.{field} values must be nonnegative integers")
    selected = dict(Counter(candidate["kind"] for candidate in candidates))
    if config["selected_kind_counts"] != selected:
        raise ValueError("config.selected_kind_counts does not match packet candidates")
    constraints = config["sampling_constraints"]
    if not isinstance(constraints, dict):
        raise ValueError("config.sampling_constraints must be an object")
    if constraints.get("at_most_one_per") != ["source_id", "split_group", "family_id"]:
        raise ValueError("packet sampling constraints do not match make_review.py")
    if constraints.get("missing_split_group_or_family_fallback") != "source_id":
        raise ValueError("packet sampling fallback does not match make_review.py")
    return config


def _candidate_key(candidate: dict[str, Any]) -> dict[str, Any]:
    fields = (
        "review_id",
        "candidate_id",
        "kind",
        "source_id",
        "source_sha256",
        "source_path",
        "split_group",
        "family_id",
        "metadata_repairs",
    )
    return {field: candidate[field] for field in fields}


def _validate_repairs(value: Any, field: str) -> None:
    if not isinstance(value, list):
        raise ValueError(f"{field} must be a list")
    for index, repair in enumerate(value):
        if not isinstance(repair, dict) or frozenset(repair) != REPAIR_FIELDS:
            raise ValueError(f"{field}[{index}] is not an exact metadata repair receipt")
        if repair["kind"] != "invalid_key_signature_retyped_as_sequencer_specific":
            raise ValueError(f"{field}[{index}].kind is unsupported")
        if repair["offset_basis"] != "unwrapped_smf_bytes":
            raise ValueError(f"{field}[{index}].offset_basis is unsupported")
        for name in (
            "track_index", "event_index", "tick", "event_offset", "status_offset",
            "meta_type_offset", "payload_offset", "original_meta_type", "replacement_meta_type",
        ):
            if isinstance(repair[name], bool) or not isinstance(repair[name], int) or repair[name] < 0:
                raise ValueError(f"{field}[{index}].{name} must be a nonnegative integer")
        for name in ("original_payload_hex", "reason"):
            if not isinstance(repair[name], str) or not repair[name]:
                raise ValueError(f"{field}[{index}].{name} must be a nonempty string")
        if not re.fullmatch(r"[0-9a-f]*", repair["original_payload_hex"]):
            raise ValueError(f"{field}[{index}].original_payload_hex is invalid")
        for name in ("original_smf_sha256", "recovered_smf_sha256"):
            _hash_text(repair[name], f"{field}[{index}].{name}")


def _validate_packet(packet: Any) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    if not isinstance(packet, dict) or packet.get("schema_version") != PACKET_VERSION:
        raise ValueError(f"packet schema_version must be {PACKET_VERSION!r}")
    candidates = packet.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise ValueError("packet candidates must be a nonempty list")
    normalized: dict[str, dict[str, Any]] = {}
    candidate_ids: set[str] = set()
    source_keys: dict[str, set[str]] = {field: set() for field in ("source_id", "split_group", "family_id")}
    for index, candidate in enumerate(candidates):
        if not isinstance(candidate, dict):
            raise ValueError(f"packet candidate {index} must be an object")
        for field in ("review_id", "candidate_id", "source_id", "source_path", "split_group", "family_id"):
            _text(candidate.get(field), f"candidate[{index}].{field}")
        source_path = candidate["source_path"]
        path_parts = PurePosixPath(source_path)
        if (
            path_parts.is_absolute()
            or ".." in path_parts.parts
            or "\\" in source_path
            or path_parts.suffix.lower() not in {".mid", ".midi"}
        ):
            raise ValueError(f"candidate[{index}].source_path must be a relative MIDI path")
        if candidate["kind"] not in KINDS:
            raise ValueError(f"candidate[{index}].kind must be melodic or percussion")
        _hash_text(candidate.get("source_sha256"), f"candidate[{index}].source_sha256")
        _validate_repairs(candidate.get("metadata_repairs"), f"candidate[{index}].metadata_repairs")
        for identity in ("review_id", "candidate_id"):
            if candidate[identity] in candidate_ids:
                raise ValueError(f"duplicate candidate {identity}: {candidate[identity]}")
            candidate_ids.add(candidate[identity])
        for field in source_keys:
            if candidate[field] in source_keys[field]:
                raise ValueError(f"packet violates at_most_one_per {field}: {candidate[field]}")
            source_keys[field].add(candidate[field])
        normalized[candidate["review_id"]] = candidate
    config = _validate_config(packet.get("config"), candidates)
    return {"schema_version": packet["schema_version"], "config": config}, normalized


def _rating_provenance(row: dict[str, Any]) -> dict[str, Any]:
    return {field: row[field] for field in (
        "review_id", "candidate_id", "kind", "source_id", "source_sha256", "source_path",
        "split_group", "family_id", "metadata_repairs",
    )}


def _validate_rating_export(
    value: Any,
    packet: dict[str, Any],
    candidates: dict[str, dict[str, Any]],
    path: Path,
) -> tuple[str, list[dict[str, Any]]]:
    if not isinstance(value, dict):
        raise ValueError(f"ratings export {path} must be an object")
    if value.get("schema_version") != packet["schema_version"]:
        raise ValueError(f"ratings export {path} has a mismatched schema_version")
    annotator = value.get("annotator_id")
    if not isinstance(annotator, str) or not annotator.strip():
        raise ValueError(f"ratings export {path} requires a nonempty annotator_id")
    if annotator != annotator.strip():
        raise ValueError(f"ratings export {path} annotator_id must not have surrounding whitespace")
    if value.get("packet_config") != packet["config"]:
        raise ValueError(f"ratings export {path} packet_config differs from the review packet")
    reviews = value.get("reviews")
    if not isinstance(reviews, list):
        raise ValueError(f"ratings export {path}.reviews must be a list")
    if not reviews:
        return annotator.strip(), []
    seen: set[str] = set()
    for index, row in enumerate(reviews):
        if not isinstance(row, dict):
            raise ValueError(f"ratings export {path} row {index} must be an object")
        if frozenset(row) != RATING_FIELDS:
            missing = sorted(RATING_FIELDS - frozenset(row))
            extra = sorted(frozenset(row) - RATING_FIELDS)
            detail = []
            if missing:
                detail.append("missing " + ", ".join(missing))
            if extra:
                detail.append("unexpected " + ", ".join(extra))
            raise ValueError(f"ratings export {path} row {index} fields invalid ({'; '.join(detail)})")
        review_id = row["review_id"]
        if review_id in seen:
            raise ValueError(f"ratings export {path} has duplicate review_id {review_id}")
        seen.add(review_id)
        candidate = candidates.get(review_id)
        if candidate is None:
            raise ValueError(f"ratings export {path} has unknown review_id {review_id}")
        if _rating_provenance(row) != _candidate_key(candidate):
            raise ValueError(f"ratings export {path} row {review_id} provenance differs from packet")
        _validate_repairs(row["metadata_repairs"], f"ratings export {path} row {review_id}.metadata_repairs")
        for field, allowed in ENUMS.items():
            rating = row[field]
            if rating is not None and rating not in allowed:
                raise ValueError(f"ratings export {path} row {review_id} has invalid {field}")
        if not isinstance(row["notes"], str):
            raise ValueError(f"ratings export {path} row {review_id}.notes must be a string")
    missing = sorted(set(candidates) - seen)
    if missing:
        raise ValueError(f"ratings export {path} is missing review rows: {', '.join(missing[:10])}")
    return annotator, reviews


def _dimension_counts(rows: Iterable[dict[str, Any]]) -> dict[str, dict[str, int]]:
    result: dict[str, dict[str, int]] = {}
    for dimension in DIMENSIONS:
        counts = Counter()
        for row in rows:
            value = row[dimension]
            counts["missing" if value is None else value] += 1
        result[dimension] = dict(sorted(counts.items()))
    return result


def _empty_dimensions() -> dict[str, dict[str, int]]:
    return {dimension: {} for dimension in DIMENSIONS}


def _annotator_summary(annotator: str, rows: list[dict[str, Any]], input_sha256: str) -> dict[str, Any]:
    by_kind = {}
    for kind in KINDS:
        kind_rows = [row for row in rows if row["kind"] == kind]
        by_kind[kind] = {"review_rows": len(kind_rows), "dimensions": _dimension_counts(kind_rows)}
    counts = _dimension_counts(rows)
    return {
        "annotator_id": annotator,
        "input_sha256": input_sha256,
        "review_rows": len(rows),
        "rated_rows": {dimension: sum(v for key, v in counts[dimension].items() if key != "missing") for dimension in DIMENSIONS},
        "counts": counts,
        "by_kind": by_kind,
    }


def _kappa(first: list[str], second: list[str]) -> float | None:
    if not first:
        return None
    if len(first) != len(second):
        raise ValueError("pairwise rating lengths differ")
    observed = sum(a == b for a, b in zip(first, second)) / len(first)
    categories = set(first) | set(second)
    expected = sum(
        (first.count(category) / len(first)) * (second.count(category) / len(second))
        for category in categories
    )
    denominator = 1.0 - expected
    if denominator == 0.0:
        return None
    return (observed - expected) / denominator


def _pairwise(exports: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    rows_by_annotator = {annotator: {row["review_id"]: row for row in rows} for annotator, rows in exports.items()}
    pairs = []
    for first_id, second_id in itertools.combinations(sorted(rows_by_annotator), 2):
        first, second = rows_by_annotator[first_id], rows_by_annotator[second_id]
        shared = sorted(set(first) & set(second))
        dimensions = {}
        for dimension in DIMENSIONS:
            values = [(first[review_id][dimension], second[review_id][dimension]) for review_id in shared]
            values = [(a, b) for a, b in values if a is not None and b is not None]
            left = [a for a, _ in values]
            right = [b for _, b in values]
            dimensions[dimension] = {
                "jointly_rated": len(values),
                "agreement_count": sum(a == b for a, b in values),
                "exact_agreement": (sum(a == b for a, b in values) / len(values)) if values else None,
                "cohen_kappa": _kappa(left, right),
            }
        pairs.append({"annotators": [first_id, second_id], "joint_rows": len(shared), "dimensions": dimensions})
    return pairs


def _snapshot_entries(
    packet_path: Path,
    packet_bytes: bytes,
    ratings: list[tuple[Path, bytes]],
) -> list[dict[str, Any]]:
    entries = [{
        "path": "review.html",
        "original_name": packet_path.name,
        "media_type": "text/html",
        "bytes": len(packet_bytes),
        "sha256": sha256_bytes(packet_bytes),
    }]
    for index, (source, data) in enumerate(ratings):
        entries.append({
            "path": f"ratings/{index:03d}-{source.name or 'ratings.json'}.bytes",
            "original_name": source.name or "ratings.json",
            "media_type": "application/json",
            "bytes": len(data),
            "sha256": sha256_bytes(data),
        })
    return entries


def _input_snapshot(
    output: Path,
    packet_bytes: bytes,
    ratings: list[tuple[Path, bytes]],
    entries: list[dict[str, Any]],
    snapshot_sha256: str,
    links: dict[str, str],
) -> None:
    for entry, data in zip(entries, [packet_bytes, *(data for _, data in ratings)], strict=True):
        target = output / "input_snapshot" / entry["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    payload = {"snapshot_version": INPUT_SNAPSHOT_VERSION, "files": entries}
    if sha256_json(payload) != snapshot_sha256:
        raise ValueError("input snapshot metadata hash mismatch")
    atomic_json(
        output / "input_snapshot.json",
        {**payload, "snapshot_sha256": snapshot_sha256, **links},
    )


def analyze_ratings(packet_path: Path, rating_paths: list[Path], output: Path) -> dict[str, Any]:
    """Validate one review packet and exports, then write a receipt-backed report."""
    packet_path = Path(packet_path).resolve(strict=True)
    rating_paths = [Path(path).resolve(strict=True) for path in rating_paths]
    if not rating_paths:
        raise ValueError("at least one ratings export is required")
    packet_bytes = packet_path.read_bytes()
    packet, candidates = _validate_packet(_script_packet(packet_bytes))
    loaded_ratings: list[tuple[Path, bytes, str, list[dict[str, Any]]]] = []
    annotator_ids: set[str] = set()
    for path in rating_paths:
        data, value = _read_json(path)
        annotator, rows = _validate_rating_export(value, packet, candidates, path)
        if annotator in annotator_ids:
            raise ValueError(f"duplicate annotator_id: {annotator}")
        annotator_ids.add(annotator)
        loaded_ratings.append((path, data, annotator, rows))
    packet_hash = sha256_bytes(packet_bytes)
    rating_hashes = [{"index": index, "sha256": sha256_bytes(data), "bytes": len(data), "name": path.name}
                     for index, (path, data, _, _) in enumerate(loaded_ratings)]
    snapshot_entries = _snapshot_entries(
        packet_path,
        packet_bytes,
        [(path, data) for path, data, _, _ in loaded_ratings],
    )
    snapshot_payload = {
        "snapshot_version": INPUT_SNAPSHOT_VERSION,
        "files": snapshot_entries,
    }
    snapshot_hash = sha256_json(snapshot_payload)
    exports = {annotator: rows for _, _, annotator, rows in loaded_ratings}
    summaries = [_annotator_summary(annotator, rows, sha256_bytes(data))
                 for _, data, annotator, rows in loaded_ratings]
    all_rows = [row for rows in exports.values() for row in rows]
    by_kind = {}
    for kind in KINDS:
        kind_rows = [row for row in all_rows if row["kind"] == kind]
        by_kind[kind] = {"review_rows": len(kind_rows), "dimensions": _dimension_counts(kind_rows)}
    design = {
        "analysis_version": ANALYSIS_VERSION,
        "packet_path_name": packet_path.name,
        "packet_sha256": packet_hash,
        "ratings": rating_hashes,
        "input_snapshot_sha256": snapshot_hash,
        "packet_config_sha256": sha256_json(packet["config"]),
        "result_artifacts": [
            "raw_results.json",
            "aggregate.json",
            "input_snapshot.json",
            *(f"input_snapshot/{entry['path']}" for entry in snapshot_entries),
        ],
    }
    config = {
        "dimensions": list(DIMENSIONS),
        "kinds": list(KINDS),
        "annotator_ids": sorted(annotator_ids),
        "empty_export_policy": "valid input with status no_ratings and zero rated rows",
        "missing_value_policy": "null is missing and excluded from pairwise agreement",
    }
    cases = [_candidate_key(candidate) for candidate in candidates.values()]
    receipt = prepare_experiment(
        Path(output),
        design=design,
        config=config,
        cases=cases,
        required_files=["scripts/analyze_ratings.py", "samuged/experiment.py", "samuged/dataset.py", "pyproject.toml", "requirements-research.lock"],
    )
    output = Path(output).resolve()
    # Detect a changed input between validation and receipt creation. The
    # snapshot is copied from the bytes that were validated, never from a new
    # unverified read.
    if packet_path.read_bytes() != packet_bytes:
        raise ValueError("review packet changed before input snapshot was written")
    for path, data, _, _ in loaded_ratings:
        if path.read_bytes() != data:
            raise ValueError(f"ratings export changed before input snapshot was written: {path.name}")
    links = receipt_links(receipt)
    _input_snapshot(
        output,
        packet_bytes,
        [(path, data) for path, data, _, _ in loaded_ratings],
        snapshot_entries,
        snapshot_hash,
        links,
    )
    status = "rated" if any(row[dimension] is not None for row in all_rows for dimension in DIMENSIONS) else "no_ratings"
    aggregate = {
        "schema_version": ANALYSIS_VERSION,
        "status": status,
        **links,
        "input_snapshot_sha256": snapshot_hash,
        "packet": {
            "sha256": packet_hash,
            "schema_version": packet["schema_version"],
            "candidate_count": len(candidates),
            "config_sha256": sha256_json(packet["config"]),
            "source_manifest_sha256": packet["config"]["source_manifest_sha256"],
            "phrase_manifest_sha256": packet["config"]["phrase_manifest_sha256"],
        },
        "annotators": summaries,
        "by_kind": by_kind,
        "pairwise": _pairwise(exports),
        "claim_boundary": "convenience sample agreement only; no corpus estimate, automatic labels or catchiness acceptance",
    }
    raw = {
        "schema_version": ANALYSIS_VERSION,
        "status": status,
        **links,
        "input_snapshot_sha256": snapshot_hash,
        "packet_sha256": packet_hash,
        "annotator_ids": sorted(annotator_ids),
        "review_rows": {annotator: len(rows) for annotator, rows in sorted(exports.items())},
        "pairwise": aggregate["pairwise"],
    }
    atomic_json(output / "raw_results.json", raw)
    atomic_json(output / "aggregate.json", aggregate)
    completion = complete_experiment(output)
    return {**aggregate, "completion": completion}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packet", type=Path, required=True, help="generated review HTML packet")
    parser.add_argument("--ratings", type=Path, nargs="+", required=True, help="local ratings JSON exports")
    parser.add_argument("--output", type=Path, required=True, help="new or empty output directory")
    args = parser.parse_args(argv)
    try:
        result = analyze_ratings(args.packet, args.ratings, args.output)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.error(str(exc))
    print(json.dumps({"status": result["status"], "output": str(args.output.resolve()),
                      "review_rows": sum(item["review_rows"] for item in result["annotators"]),
                      "annotators": result["annotators"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
