"""Validate and summarize offline paired-review ratings.

The packet artifacts and rating exports are copied byte for byte into a new
receipt-backed output directory. Missing preferences remain missing. The
analysis only reports descriptive choices and inter-annotator agreement.
"""
from __future__ import annotations

import argparse
from collections import Counter
from hashlib import sha256
from html.parser import HTMLParser
import itertools
import json
from pathlib import Path
import re
import sys
from typing import Any, Iterable

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from samuged.dataset import atomic_json
from samuged.experiment import complete_experiment, prepare_experiment, receipt_links, sha256_json
from scripts.make_paired_review import PACKET_VERSION, RATINGS_VERSION, validate_ratings


ANALYSIS_VERSION = "samuged-paired-ratings-analysis-v1"
INPUT_SNAPSHOT_VERSION = "samuged-paired-ratings-input-snapshot-v1"
PACKET_FILES = ("review.html", "packet_receipt.json", "input_manifest.json", "blind_mapping.json")
RECEIPT_ARTIFACTS = ("review.html", "blind_mapping.json", "input_manifest.json")
DATASET_ARTIFACTS = ("sources.jsonl", "phrases.jsonl", "summary.json", "build_config.json", "audit.json")
OUTCOMES = ("left", "right", "tie", "uncertain", "missing")
RATED_OUTCOMES = OUTCOMES[:-1]
TOP_LEVEL_RATING_FIELDS = frozenset(("schema_version", "annotator_id", "packet_sha256", "ratings"))
RATING_FIELDS = frozenset(("review_id", "preference", "notes", "candidate_ids"))
MAPPING_FIELDS = frozenset(
    (
        "review_id",
        "source_id",
        "source_path",
        "source_sha256",
        "split_group",
        "left_candidate_id",
        "right_candidate_id",
        "metadata_repairs",
        "identical",
        "side_order",
    )
)
HASH_RE = re.compile(r"^[0-9a-f]{64}$")


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def _sha256(data: bytes) -> str:
    return sha256(data).hexdigest()


def _read_json_bytes(path: Path) -> tuple[bytes, dict[str, Any]]:
    try:
        data = path.read_bytes()
        value = json.loads(data.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data, value


def _required_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} must be a nonempty string")
    return value


def _required_hash(value: Any, field: str) -> str:
    if not isinstance(value, str) or HASH_RE.fullmatch(value) is None:
        raise ValueError(f"{field} must be a lowercase SHA256 string")
    return value


class _PairedDataParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.capture = False
        self.parts: list[str] = []
        self.blocks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "script" and dict(attrs).get("id") == "paired-data":
            if self.capture:
                raise ValueError("nested paired-data script")
            self.capture = True
            self.parts = []

    def handle_data(self, data: str) -> None:
        if self.capture:
            self.parts.append(data)

    def handle_entityref(self, name: str) -> None:
        if self.capture:
            self.parts.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        if self.capture:
            self.parts.append(f"&#{name};")

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "script" and self.capture:
            self.blocks.append("".join(self.parts))
            self.capture = False


def _packet_from_html(data: bytes) -> dict[str, Any]:
    parser = _PairedDataParser()
    try:
        parser.feed(data.decode("utf-8"))
        parser.close()
    except (UnicodeError, ValueError) as exc:
        raise ValueError(f"invalid paired review HTML: {exc}") from exc
    if len(parser.blocks) != 1:
        raise ValueError("review HTML must contain exactly one paired-data script")
    try:
        packet = json.loads(parser.blocks[0])
    except json.JSONDecodeError as exc:
        raise ValueError(f"paired-data is not valid JSON: {exc.msg}") from exc
    if not isinstance(packet, dict):
        raise ValueError("paired-data must contain an object")
    return packet


def _packet_hash(packet: dict[str, Any]) -> str:
    body = dict(packet)
    declared = body.pop("packet_sha256", None)
    actual = _sha256(_canonical(body))
    if declared != actual:
        raise ValueError("packet_sha256 does not match embedded packet")
    return actual


def _rendered_core(alternative: Any, field: str) -> dict[str, Any]:
    if not isinstance(alternative, dict):
        raise ValueError(f"{field} must be an object")
    for key in ("kind", "snippets", "tempo_map"):
        if key not in alternative:
            raise ValueError(f"{field} is missing {key}")
    return {key: alternative[key] for key in ("kind", "snippets", "tempo_map")}


def _verify_packet(packet_dir: Path) -> dict[str, Any]:
    packet_dir = packet_dir.resolve(strict=True)
    if not packet_dir.is_dir():
        raise ValueError(f"packet is not a directory: {packet_dir}")
    paths = {name: packet_dir / name for name in PACKET_FILES}
    missing = [name for name, path in paths.items() if not path.is_file()]
    if missing:
        raise ValueError(f"packet is missing artifacts: {', '.join(missing)}")
    file_bytes = {name: path.read_bytes() for name, path in paths.items()}
    packet = _packet_from_html(file_bytes["review.html"])
    packet_hash = _packet_hash(packet)
    parsed: dict[str, dict[str, Any]] = {}
    for name in PACKET_FILES[1:]:
        try:
            value = json.loads(file_bytes[name].decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid packet artifact {name}: {exc}") from exc
        if not isinstance(value, dict):
            raise ValueError(f"packet artifact {name} must contain an object")
        parsed[name] = value

    receipt = parsed["packet_receipt.json"]
    manifest = parsed["input_manifest.json"]
    mapping_doc = parsed["blind_mapping.json"]
    if receipt.get("schema_version") != PACKET_VERSION or receipt.get("ratings_schema_version") != RATINGS_VERSION:
        raise ValueError("packet receipt schema is unsupported")
    if receipt.get("status") != "complete" or receipt.get("packet_sha256") != packet_hash:
        raise ValueError("packet receipt is incomplete or bound to another packet")
    if receipt.get("config") != packet.get("config"):
        raise ValueError("packet receipt config differs from embedded packet")
    artifact_hashes = receipt.get("artifacts")
    if not isinstance(artifact_hashes, dict) or set(artifact_hashes) != set(RECEIPT_ARTIFACTS):
        raise ValueError("packet receipt artifact set is invalid")
    for name in RECEIPT_ARTIFACTS:
        if artifact_hashes.get(name) != _sha256(file_bytes[name]):
            raise ValueError(f"packet receipt hash is stale for {name}")

    if manifest.get("schema_version") != PACKET_VERSION or manifest.get("packet_sha256") != packet_hash:
        raise ValueError("input manifest is bound to another packet")
    code_hashes = manifest.get("code_sha256")
    if not isinstance(code_hashes, dict) or manifest.get("script_sha256") != code_hashes.get("scripts/make_paired_review.py"):
        raise ValueError("input manifest script hash is inconsistent")
    if not code_hashes:
        raise ValueError("input manifest code hash set is empty")
    for path, digest in code_hashes.items():
        _required_text(path, "input manifest code path")
        _required_hash(digest, f"input manifest code hash {path}")
    _required_text(manifest.get("source_root"), "input manifest source_root")
    variants = manifest.get("variants")
    if not isinstance(variants, dict) or set(variants) != {"left", "right"}:
        raise ValueError("input manifest must define left and right variants")
    for side in ("left", "right"):
        variant = variants[side]
        if not isinstance(variant, dict):
            raise ValueError(f"input manifest variant {side} must be an object")
        _required_text(variant.get("algorithm"), f"input manifest {side}.algorithm")
        _required_text(variant.get("dataset"), f"input manifest {side}.dataset")
        _required_text(variant.get("scope"), f"input manifest {side}.scope")
        artifacts = variant.get("artifacts")
        if not isinstance(artifacts, dict) or set(artifacts) != set(DATASET_ARTIFACTS):
            raise ValueError(f"input manifest {side}.artifacts set is invalid")
        for name in DATASET_ARTIFACTS:
            _required_hash(artifacts[name], f"input manifest {side}.artifacts.{name}")
    packet_scope = packet.get("config", {}).get("scope")
    if packet_scope != {side: variants[side]["scope"] for side in ("left", "right")}:
        raise ValueError("packet scope differs from input manifest variants")

    if mapping_doc.get("schema_version") != PACKET_VERSION or mapping_doc.get("packet_sha256") != packet_hash:
        raise ValueError("blind mapping is bound to another packet")
    pairs = packet.get("pairs")
    mapping_rows = mapping_doc.get("pairs")
    if not isinstance(pairs, list) or not pairs or not isinstance(mapping_rows, list):
        raise ValueError("packet and blind mapping must contain nonempty pair lists")
    pair_by_id: dict[str, dict[str, Any]] = {}
    for index, pair in enumerate(pairs):
        if not isinstance(pair, dict):
            raise ValueError(f"packet pair {index} must be an object")
        review_id = _required_text(pair.get("review_id"), f"packet pair {index}.review_id")
        if review_id in pair_by_id:
            raise ValueError(f"duplicate packet review_id: {review_id}")
        candidate_ids = pair.get("candidate_ids")
        if not isinstance(candidate_ids, dict) or set(candidate_ids) != {"A", "B"}:
            raise ValueError(f"packet pair {review_id} candidate_ids are invalid")
        _required_text(candidate_ids["A"], f"packet pair {review_id}.candidate_ids.A")
        _required_text(candidate_ids["B"], f"packet pair {review_id}.candidate_ids.B")
        alternatives = pair.get("alternatives")
        if not isinstance(alternatives, dict) or set(alternatives) != {"A", "B"}:
            raise ValueError(f"packet pair {review_id} alternatives are invalid")
        _rendered_core(alternatives["A"], f"packet pair {review_id}.alternatives.A")
        _rendered_core(alternatives["B"], f"packet pair {review_id}.alternatives.B")
        pair_by_id[review_id] = pair

    mapping_by_id: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(mapping_rows):
        if not isinstance(row, dict) or frozenset(row) != MAPPING_FIELDS:
            raise ValueError(f"blind mapping row {index} fields are invalid")
        review_id = _required_text(row.get("review_id"), f"blind mapping row {index}.review_id")
        if review_id in mapping_by_id or review_id not in pair_by_id:
            raise ValueError(f"unknown or duplicate blind mapping review_id: {review_id}")
        for field in ("source_id", "source_path", "split_group", "left_candidate_id", "right_candidate_id"):
            _required_text(row.get(field), f"blind mapping {review_id}.{field}")
        _required_hash(row.get("source_sha256"), f"blind mapping {review_id}.source_sha256")
        if not isinstance(row.get("metadata_repairs"), list):
            raise ValueError(f"blind mapping {review_id}.metadata_repairs must be a list")
        if not isinstance(row.get("identical"), bool) or row.get("side_order") not in {"AB", "BA"}:
            raise ValueError(f"blind mapping {review_id} classification is invalid")
        expected = (
            {"A": row["left_candidate_id"], "B": row["right_candidate_id"]}
            if row["side_order"] == "AB"
            else {"A": row["right_candidate_id"], "B": row["left_candidate_id"]}
        )
        if pair_by_id[review_id]["candidate_ids"] != expected:
            raise ValueError(f"blind mapping candidate orientation differs for {review_id}")
        alternatives = pair_by_id[review_id]["alternatives"]
        left_key, right_key = ("A", "B") if row["side_order"] == "AB" else ("B", "A")
        rendered_identical = _canonical(
            _rendered_core(alternatives[left_key], f"packet pair {review_id}.{left_key}")
        ) == _canonical(_rendered_core(alternatives[right_key], f"packet pair {review_id}.{right_key}"))
        if row["identical"] is not rendered_identical:
            raise ValueError(f"blind mapping identical classification differs for {review_id}")
        mapping_by_id[review_id] = row
    if set(mapping_by_id) != set(pair_by_id):
        raise ValueError("blind mapping does not cover exactly the packet pairs")

    selected_sources = manifest.get("selected_sources")
    if not isinstance(selected_sources, list):
        raise ValueError("input manifest selected_sources must be a list")
    source_by_id: dict[str, dict[str, Any]] = {}
    for index, source in enumerate(selected_sources):
        if not isinstance(source, dict):
            raise ValueError(f"selected source {index} must be an object")
        source_id = _required_text(source.get("source_id"), f"selected source {index}.source_id")
        if source_id in source_by_id:
            raise ValueError(f"duplicate selected source_id: {source_id}")
        _required_text(source.get("source_path"), f"selected source {index}.source_path")
        _required_hash(source.get("source_sha256"), f"selected source {index}.source_sha256")
        if isinstance(source.get("source_bytes"), bool) or not isinstance(source.get("source_bytes"), int) or source["source_bytes"] < 0:
            raise ValueError(f"selected source {index}.source_bytes must be a nonnegative integer")
        if not isinstance(source.get("metadata_repairs"), list):
            raise ValueError(f"selected source {index}.metadata_repairs must be a list")
        source_by_id[source_id] = source
    for review_id, row in mapping_by_id.items():
        source = source_by_id.get(row["source_id"])
        if source is None:
            raise ValueError(f"blind mapping {review_id} source is absent from input manifest")
        for field in ("source_path", "source_sha256", "metadata_repairs"):
            if source.get(field) != row[field]:
                raise ValueError(f"blind mapping {review_id}.{field} differs from input manifest")
    if set(source_by_id) != {row["source_id"] for row in mapping_rows}:
        raise ValueError("input manifest selected_sources do not exactly cover blind mapping")
    config = packet.get("config")
    if not isinstance(config, dict) or config.get("selected_count") != len(pairs):
        raise ValueError("packet selected_count differs from pair count")
    identical_count = sum(bool(row["identical"]) for row in mapping_rows)
    if config.get("identical_pair_count") != identical_count:
        raise ValueError("packet identical_pair_count differs from blind mapping")

    return {
        "directory": packet_dir,
        "paths": paths,
        "bytes": file_bytes,
        "packet": packet,
        "packet_sha256": packet_hash,
        "receipt": receipt,
        "manifest": manifest,
        "mapping": mapping_by_id,
    }


def _validate_export(path: Path, packet: dict[str, Any]) -> dict[str, Any]:
    data, payload = _read_json_bytes(path)
    if frozenset(payload) != TOP_LEVEL_RATING_FIELDS:
        raise ValueError(f"ratings export {path} fields are invalid")
    ratings = payload.get("ratings")
    if not isinstance(ratings, list):
        raise ValueError(f"ratings export {path}.ratings must be a list")
    for index, row in enumerate(ratings):
        if not isinstance(row, dict) or frozenset(row) != RATING_FIELDS:
            raise ValueError(f"ratings export {path} row {index} fields are invalid")
    validated = validate_ratings(payload, packet)
    rated = validated["rated_count"] > 0
    annotator = payload.get("annotator_id")
    if rated:
        if not isinstance(annotator, str) or not annotator.strip():
            raise ValueError(f"rated export {path} requires a nonempty annotator_id")
        if annotator != annotator.strip():
            raise ValueError(f"ratings export {path} annotator_id has surrounding whitespace")
    elif isinstance(annotator, str) and annotator != annotator.strip():
        raise ValueError(f"ratings export {path} annotator_id has surrounding whitespace")
    return {
        "path": path,
        "bytes": data,
        "sha256": _sha256(data),
        "payload": payload,
        "annotator_id": annotator,
        "rated_count": validated["rated_count"],
    }


def _unblind(preference: str | None, side_order: str) -> str:
    if preference is None:
        return "missing"
    if preference in {"tie", "uncertain"}:
        return preference
    if preference == "A":
        return "left" if side_order == "AB" else "right"
    if preference == "B":
        return "right" if side_order == "AB" else "left"
    raise ValueError(f"unsupported preference: {preference}")


def _counts(rows: Iterable[dict[str, Any]]) -> dict[str, int]:
    counts = Counter(row["outcome"] for row in rows)
    return {outcome: counts[outcome] for outcome in OUTCOMES}


def _annotator_summary(export: dict[str, Any], rows: list[dict[str, Any]], label: str) -> dict[str, Any]:
    informative = [row for row in rows if not row["identical"]]
    identical = [row for row in rows if row["identical"]]
    return {
        "annotator_id": export["annotator_id"],
        "export_label": label,
        "input_sha256": export["sha256"],
        "pair_count": len(rows),
        "rated_count": sum(row["outcome"] != "missing" for row in rows),
        "counts": _counts(rows),
        "informative_pairs": {"pair_count": len(informative), "counts": _counts(informative)},
        "identical_rendered_pairs": {"pair_count": len(identical), "counts": _counts(identical)},
    }


def _kappa(first: list[str], second: list[str]) -> float | None:
    if len(first) != len(second):
        raise ValueError("pairwise rating lengths differ")
    if len(first) < 2:
        return None
    observed = sum(a == b for a, b in zip(first, second)) / len(first)
    expected = sum(
        (first.count(category) / len(first)) * (second.count(category) / len(second))
        for category in RATED_OUTCOMES
    )
    if expected == 1.0:
        return None
    return (observed - expected) / (1.0 - expected)


def _agreement(first: dict[str, dict[str, Any]], second: dict[str, dict[str, Any]], *, identical: bool | None) -> dict[str, Any]:
    review_ids = sorted(set(first) & set(second))
    if identical is not None:
        review_ids = [review_id for review_id in review_ids if first[review_id]["identical"] is identical]
    joint = [
        (first[review_id]["outcome"], second[review_id]["outcome"])
        for review_id in review_ids
        if first[review_id]["outcome"] != "missing" and second[review_id]["outcome"] != "missing"
    ]
    agreements = sum(left == right for left, right in joint)
    return {
        "available_pairs": len(review_ids),
        "jointly_rated": len(joint),
        "agreement_count": agreements,
        "raw_agreement": agreements / len(joint) if joint else None,
        "cohen_kappa": _kappa([left for left, _ in joint], [right for _, right in joint]),
    }


def _pairwise(
    rows_by_export: dict[str, list[dict[str, Any]]], annotators: dict[str, str | None]
) -> list[dict[str, Any]]:
    indexed = {
        label: {row["review_id"]: row for row in rows}
        for label, rows in rows_by_export.items()
    }
    results = []
    for first_label, second_label in itertools.combinations(sorted(indexed), 2):
        first, second = indexed[first_label], indexed[second_label]
        results.append(
            {
                "exports": [first_label, second_label],
                "annotator_ids": [annotators[first_label], annotators[second_label]],
                "all_pairs": _agreement(first, second, identical=None),
                "informative_pairs": _agreement(first, second, identical=False),
                "identical_rendered_pairs": _agreement(first, second, identical=True),
            }
        )
    return results


def _snapshot_entries(packet: dict[str, Any], exports: list[dict[str, Any]]) -> list[dict[str, Any]]:
    entries = []
    for name in PACKET_FILES:
        data = packet["bytes"][name]
        entries.append({"path": f"packet/{name}.bytes", "role": name, "bytes": len(data), "sha256": _sha256(data)})
    for index, export in enumerate(exports, start=1):
        data = export["bytes"]
        entries.append(
            {
                "path": f"ratings/{index:03d}.json.bytes",
                "role": "ratings_export",
                "original_name": export["path"].name,
                "bytes": len(data),
                "sha256": export["sha256"],
            }
        )
    return entries


def _copy_snapshot(output: Path, packet: dict[str, Any], exports: list[dict[str, Any]], entries: list[dict[str, Any]], links: dict[str, str]) -> None:
    source_data = [packet["bytes"][name] for name in PACKET_FILES] + [export["bytes"] for export in exports]
    for entry, data in zip(entries, source_data, strict=True):
        target = output / "input_snapshot" / entry["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    payload = {"schema_version": INPUT_SNAPSHOT_VERSION, "files": entries}
    atomic_json(output / "input_snapshot.json", {**payload, "snapshot_sha256": sha256_json(payload), **links})


def analyze_paired_ratings(
    packet_dir: Path,
    rating_paths: list[Path],
    output: Path,
    *,
    machine_ui_test: bool = False,
) -> dict[str, Any]:
    """Validate, freeze and descriptively summarize paired rating exports."""
    if not rating_paths:
        raise ValueError("at least one ratings export is required")
    packet = _verify_packet(Path(packet_dir))
    resolved_paths = [Path(path).resolve(strict=True) for path in rating_paths]
    if len(set(resolved_paths)) != len(resolved_paths):
        raise ValueError("the same ratings export was supplied more than once")
    exports = [_validate_export(path, packet["packet"]) for path in resolved_paths]
    rated_ids: set[str] = set()
    for export in exports:
        if export["rated_count"]:
            annotator = export["annotator_id"]
            if annotator in rated_ids:
                raise ValueError(f"duplicate annotator_id among rated exports: {annotator}")
            rated_ids.add(annotator)

    labels = [f"export-{index:03d}" for index in range(1, len(exports) + 1)]
    rows_by_export: dict[str, list[dict[str, Any]]] = {}
    for label, export in zip(labels, exports, strict=True):
        rows = []
        for rating in export["payload"]["ratings"]:
            mapping = packet["mapping"][rating["review_id"]]
            rows.append(
                {
                    "review_id": rating["review_id"],
                    "preference": rating["preference"],
                    "notes": rating["notes"],
                    "candidate_ids": rating["candidate_ids"],
                    "outcome": _unblind(rating["preference"], mapping["side_order"]),
                    "identical": mapping["identical"],
                }
            )
        rows_by_export[label] = rows

    snapshot_entries = _snapshot_entries(packet, exports)
    snapshot_payload = {"schema_version": INPUT_SNAPSHOT_VERSION, "files": snapshot_entries}
    design = {
        "analysis_version": ANALYSIS_VERSION,
        "packet_sha256": packet["packet_sha256"],
        "packet_artifacts": packet["receipt"]["artifacts"],
        "ratings_exports": [
            {"label": label, "sha256": export["sha256"], "bytes": len(export["bytes"]), "original_name": export["path"].name}
            for label, export in zip(labels, exports, strict=True)
        ],
        "input_snapshot_sha256": sha256_json(snapshot_payload),
        "result_artifacts": [
            "raw_results.json",
            "aggregate.json",
            "input_snapshot.json",
            *(f"input_snapshot/{entry['path']}" for entry in snapshot_entries),
        ],
    }
    config = {
        "machine_ui_test": bool(machine_ui_test),
        "missing_value_policy": "null remains missing and is excluded from jointly rated agreement",
        "unblinding_policy": "A/B is mapped through the receipt-bound blind_mapping.json side_order",
        "identical_pair_policy": "reported separately from informative rendered pairs",
        "inference_policy": "descriptive per-annotator counts only; votes are not pooled as independent samples",
    }
    cases = [
        {
            "review_id": review_id,
            "source_id": row["source_id"],
            "source_sha256": row["source_sha256"],
            "left_candidate_id": row["left_candidate_id"],
            "right_candidate_id": row["right_candidate_id"],
            "side_order": row["side_order"],
            "identical": row["identical"],
        }
        for review_id, row in sorted(packet["mapping"].items())
    ]
    receipt = prepare_experiment(
        Path(output),
        design=design,
        config=config,
        cases=cases,
        required_files=[
            "scripts/analyze_paired_ratings.py",
            "scripts/make_paired_review.py",
            "samuged/experiment.py",
            "samuged/dataset.py",
            "pyproject.toml",
            "requirements-research.lock",
        ],
    )
    output = Path(output).resolve()
    links = receipt_links(receipt)

    def verify_inputs_unchanged() -> None:
        for name, path in packet["paths"].items():
            if path.read_bytes() != packet["bytes"][name]:
                raise ValueError(f"packet artifact changed during analysis: {name}")
        for export in exports:
            if export["path"].read_bytes() != export["bytes"]:
                raise ValueError(f"ratings export changed during analysis: {export['path'].name}")

    verify_inputs_unchanged()
    _copy_snapshot(output, packet, exports, snapshot_entries, links)
    status = "rated" if any(export["rated_count"] for export in exports) else "no_ratings"
    summaries = [
        _annotator_summary(export, rows_by_export[label], label)
        for label, export in zip(labels, exports, strict=True)
    ]
    pairwise = _pairwise(
        rows_by_export,
        {label: export["annotator_id"] for label, export in zip(labels, exports, strict=True)},
    )
    raw = {
        "schema_version": ANALYSIS_VERSION,
        "status": status,
        **links,
        "input_snapshot_sha256": sha256_json(snapshot_payload),
        "packet_sha256": packet["packet_sha256"],
        "machine_ui_test": bool(machine_ui_test),
        "exports": [
            {
                "export_label": label,
                "annotator_id": export["annotator_id"],
                "input_sha256": export["sha256"],
                "ratings": rows_by_export[label],
            }
            for label, export in zip(labels, exports, strict=True)
        ],
        "pairwise": pairwise,
    }
    aggregate = {
        "schema_version": ANALYSIS_VERSION,
        "status": status,
        **links,
        "input_snapshot_sha256": sha256_json(snapshot_payload),
        "packet": {
            "sha256": packet["packet_sha256"],
            "pair_count": len(packet["mapping"]),
            "informative_pair_count": sum(not row["identical"] for row in packet["mapping"].values()),
            "identical_rendered_pair_count": sum(row["identical"] for row in packet["mapping"].values()),
            "left_algorithm": packet["manifest"]["variants"]["left"]["algorithm"],
            "right_algorithm": packet["manifest"]["variants"]["right"]["algorithm"],
            "artifact_sha256": packet["receipt"]["artifacts"],
        },
        "machine_ui_test": bool(machine_ui_test),
        "annotators": summaries,
        "pairwise": pairwise,
        "validation_scope": {
            "packet_internal_bindings_verified": True,
            "generator_code_hash_declarations_syntax_checked": True,
            "generator_code_bytes_independently_checked": False,
            "original_source_note_reconstruction_repeated": False,
            "analyzer_executable_source_closure_snapshotted": True,
        },
        "claim_boundary": "descriptive offline ratings only; no inferential superiority, corpus quality or perceptual quality claim",
    }
    atomic_json(output / "raw_results.json", raw)
    atomic_json(output / "aggregate.json", aggregate)
    verify_inputs_unchanged()
    completion = complete_experiment(output)
    return {**aggregate, "completion": completion}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packet", type=Path, required=True, help="paired review packet directory")
    parser.add_argument("--ratings", type=Path, nargs="+", required=True, help="one or more exported ratings JSON files")
    parser.add_argument("--output", type=Path, required=True, help="new or empty output directory")
    parser.add_argument("--machine-ui-test", action="store_true", help="label this run as a machine UI smoke test")
    args = parser.parse_args(argv)
    try:
        result = analyze_paired_ratings(
            args.packet, args.ratings, args.output, machine_ui_test=args.machine_ui_test
        )
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.error(str(exc))
    print(
        json.dumps(
            {
                "status": result["status"],
                "output": str(args.output.resolve()),
                "packet_sha256": result["packet"]["sha256"],
                "annotator_count": len(result["annotators"]),
                "machine_ui_test": result["machine_ui_test"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
