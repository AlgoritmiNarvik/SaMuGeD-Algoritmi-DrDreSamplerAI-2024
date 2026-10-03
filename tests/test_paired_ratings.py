from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

import pytest

from samuged.experiment import verify_completed_experiment
from scripts.analyze_paired_ratings import analyze_paired_ratings
from scripts.make_paired_review import PACKET_VERSION, RATINGS_VERSION


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _hash(data: bytes) -> str:
    return sha256(data).hexdigest()


def _write_json(path: Path, value: object) -> None:
    path.write_bytes(_canonical(value) + b"\n")


def _packet_fixture(root: Path) -> tuple[Path, dict]:
    root.mkdir()
    specs = [
        ("P001", "left-1", "right-1", "AB", False),
        ("P002", "left-2", "right-2", "BA", False),
        ("P003", "left-3", "right-3", "AB", True),
    ]
    pairs = []
    mapping = []
    selected_sources = []
    for index, (review_id, left, right, order, identical) in enumerate(specs, start=1):
        candidate_ids = {"A": left, "B": right} if order == "AB" else {"A": right, "B": left}
        left_view = {"kind": "melodic", "snippets": [{"pitches": [60, index]}], "tempo_map": [{"tick": 0, "microseconds_per_beat": 500000}]}
        right_view = deepcopy(left_view) if identical else {"kind": "melodic", "snippets": [{"pitches": [61, index]}], "tempo_map": [{"tick": 0, "microseconds_per_beat": 500000}]}
        alternatives = {"A": left_view, "B": right_view} if order == "AB" else {"A": right_view, "B": left_view}
        pairs.append(
            {
                "review_id": review_id,
                "candidate_ids": candidate_ids,
                "alternatives": alternatives,
            }
        )
        source_id = f"source-{index}"
        source_path = f"Artist/Song-{index}.mid"
        source_hash = sha256(source_id.encode()).hexdigest()
        mapping.append(
            {
                "review_id": review_id,
                "source_id": source_id,
                "source_path": source_path,
                "source_sha256": source_hash,
                "split_group": source_id,
                "left_candidate_id": left,
                "right_candidate_id": right,
                "metadata_repairs": [],
                "identical": identical,
                "side_order": order,
            }
        )
        selected_sources.append(
            {
                "source_id": source_id,
                "source_path": source_path,
                "source_sha256": source_hash,
                "source_bytes": 100 + index,
                "metadata_repairs": [],
            }
        )
    config = {
        "requested_count": 3,
        "selected_count": 3,
        "kind": "melodic",
        "seed": "unit-test",
        "scope": {"left": "pilot", "right": "pilot"},
        "selection": "fixed unit fixture",
        "top_one_ranking": "fixed unit fixture",
        "identical_pair_count": 1,
        "identical_pair_definition": "fixture equality",
        "source_context": "not included",
        "playback_synthesis": "fixture",
    }
    body = {"schema_version": PACKET_VERSION, "config": config, "pairs": pairs}
    packet_hash = _hash(_canonical(body))
    packet = {**body, "packet_sha256": packet_hash}
    html = (
        "<!doctype html><html><body><script id=\"paired-data\" type=\"application/json\">"
        + _canonical(packet).decode()
        + "</script></body></html>"
    ).encode()
    (root / "review.html").write_bytes(html)
    mapping_doc = {"schema_version": PACKET_VERSION, "packet_sha256": packet_hash, "pairs": mapping}
    manifest = {
        "schema_version": PACKET_VERSION,
        "packet_sha256": packet_hash,
        "script_sha256": "1" * 64,
        "code_sha256": {"scripts/make_paired_review.py": "1" * 64},
        "source_root": "/not/read/by-analysis",
        "variants": {
            "left": {
                "algorithm": "aligned_closed",
                "dataset": "/left",
                "scope": "pilot",
                "artifacts": {name: "2" * 64 for name in ("sources.jsonl", "phrases.jsonl", "summary.json", "build_config.json", "audit.json")},
            },
            "right": {
                "algorithm": "aligned_melody",
                "dataset": "/right",
                "scope": "pilot",
                "artifacts": {name: "3" * 64 for name in ("sources.jsonl", "phrases.jsonl", "summary.json", "build_config.json", "audit.json")},
            },
        },
        "selected_sources": selected_sources,
    }
    _write_json(root / "blind_mapping.json", mapping_doc)
    _write_json(root / "input_manifest.json", manifest)
    receipt = {
        "schema_version": PACKET_VERSION,
        "ratings_schema_version": RATINGS_VERSION,
        "status": "complete",
        "packet_sha256": packet_hash,
        "config": config,
        "artifacts": {
            name: _hash((root / name).read_bytes())
            for name in ("review.html", "blind_mapping.json", "input_manifest.json")
        },
    }
    _write_json(root / "packet_receipt.json", receipt)
    return root, packet


def _export(path: Path, packet: dict, annotator: str | None, preferences: list[str | None]) -> Path:
    rows = []
    for pair, preference in zip(packet["pairs"], preferences, strict=True):
        rows.append(
            {
                "review_id": pair["review_id"],
                "preference": preference,
                "notes": None,
                "candidate_ids": pair["candidate_ids"],
            }
        )
    payload = {
        "schema_version": RATINGS_VERSION,
        "annotator_id": annotator,
        "packet_sha256": packet["packet_sha256"],
        "ratings": rows,
    }
    _write_json(path, payload)
    return path


def test_unblinds_counts_strata_and_agreement(tmp_path: Path) -> None:
    packet_dir, packet = _packet_fixture(tmp_path / "packet")
    first = _export(tmp_path / "first.json", packet, "ann-1", ["A", "A", "tie"])
    second = _export(tmp_path / "second.json", packet, "ann-2", ["A", "B", "tie"])

    result = analyze_paired_ratings(packet_dir, [first, second], tmp_path / "out")

    assert result["status"] == "rated"
    assert result["packet"]["informative_pair_count"] == 2
    assert result["packet"]["identical_rendered_pair_count"] == 1
    ann1 = result["annotators"][0]
    assert ann1["counts"] == {"left": 1, "right": 1, "tie": 1, "uncertain": 0, "missing": 0}
    assert ann1["informative_pairs"]["counts"]["right"] == 1
    assert ann1["identical_rendered_pairs"]["counts"]["tie"] == 1
    agreement = result["pairwise"][0]
    assert agreement["annotator_ids"] == ["ann-1", "ann-2"]
    assert agreement["all_pairs"]["raw_agreement"] == pytest.approx(2 / 3)
    assert agreement["all_pairs"]["cohen_kappa"] == pytest.approx(0.5)
    assert agreement["informative_pairs"]["raw_agreement"] == pytest.approx(0.5)
    assert agreement["informative_pairs"]["cohen_kappa"] == pytest.approx(0.0)
    assert verify_completed_experiment(tmp_path / "out")["status"] == "completed"

    raw = json.loads((tmp_path / "out" / "raw_results.json").read_text())
    assert [row["preference"] for row in raw["exports"][0]["ratings"]] == ["A", "A", "tie"]
    assert [row["outcome"] for row in raw["exports"][0]["ratings"]] == ["left", "right", "tie"]


def test_all_null_is_no_ratings_and_preserves_nulls(tmp_path: Path) -> None:
    packet_dir, packet = _packet_fixture(tmp_path / "packet")
    ratings = _export(tmp_path / "ratings.json", packet, None, [None, None, None])
    before = ratings.read_bytes()

    result = analyze_paired_ratings(packet_dir, [ratings], tmp_path / "out", machine_ui_test=True)

    assert result["status"] == "no_ratings"
    assert result["machine_ui_test"] is True
    assert result["annotators"][0]["annotator_id"] is None
    assert result["annotators"][0]["counts"]["missing"] == 3
    assert result["pairwise"] == []
    assert result["validation_scope"] == {
        "packet_internal_bindings_verified": True,
        "generator_code_hash_declarations_syntax_checked": True,
        "generator_code_bytes_independently_checked": False,
        "original_source_note_reconstruction_repeated": False,
        "analyzer_executable_source_closure_snapshotted": True,
    }
    assert ratings.read_bytes() == before
    raw = json.loads((tmp_path / "out" / "raw_results.json").read_text())
    assert all(row["preference"] is None and row["notes"] is None for row in raw["exports"][0]["ratings"])


@pytest.mark.parametrize("missing", ["packet_sha256", "annotator_id", "ratings"])
def test_rejects_missing_export_fields(tmp_path: Path, missing: str) -> None:
    packet_dir, packet = _packet_fixture(tmp_path / "packet")
    ratings = _export(tmp_path / "ratings.json", packet, "ann", ["A", None, None])
    payload = json.loads(ratings.read_text())
    del payload[missing]
    _write_json(ratings, payload)
    with pytest.raises(ValueError, match="fields are invalid"):
        analyze_paired_ratings(packet_dir, [ratings], tmp_path / "out")


def test_rejects_missing_row_field_and_altered_binding(tmp_path: Path) -> None:
    packet_dir, packet = _packet_fixture(tmp_path / "packet")
    ratings = _export(tmp_path / "ratings.json", packet, "ann", ["A", None, None])
    payload = json.loads(ratings.read_text())
    del payload["ratings"][0]["notes"]
    _write_json(ratings, payload)
    with pytest.raises(ValueError, match="row 0 fields are invalid"):
        analyze_paired_ratings(packet_dir, [ratings], tmp_path / "out-a")

    ratings = _export(tmp_path / "ratings.json", packet, "ann", ["A", None, None])
    payload = json.loads(ratings.read_text())
    payload["ratings"][0]["candidate_ids"]["A"] = "other"
    _write_json(ratings, payload)
    with pytest.raises(ValueError, match="candidate binding mismatch"):
        analyze_paired_ratings(packet_dir, [ratings], tmp_path / "out-b")

    ratings = _export(tmp_path / "ratings.json", packet, "ann", ["A", None, None])
    payload = json.loads(ratings.read_text())
    payload["ratings"][1] = deepcopy(payload["ratings"][0])
    _write_json(ratings, payload)
    with pytest.raises(ValueError, match="unknown or duplicate review_id"):
        analyze_paired_ratings(packet_dir, [ratings], tmp_path / "out-c")


def test_rejects_stale_hash_duplicate_ids_and_blank_rated_annotator(tmp_path: Path) -> None:
    packet_dir, packet = _packet_fixture(tmp_path / "packet")
    stale = _export(tmp_path / "stale.json", packet, "ann", ["A", None, None])
    payload = json.loads(stale.read_text())
    payload["packet_sha256"] = "0" * 64
    _write_json(stale, payload)
    with pytest.raises(ValueError, match="ratings packet hash mismatch"):
        analyze_paired_ratings(packet_dir, [stale], tmp_path / "out-a")

    blank = _export(tmp_path / "blank.json", packet, " ", ["A", None, None])
    with pytest.raises(ValueError, match="nonempty annotator_id"):
        analyze_paired_ratings(packet_dir, [blank], tmp_path / "out-b")

    first = _export(tmp_path / "first.json", packet, "ann", ["A", None, None])
    second = _export(tmp_path / "second.json", packet, "ann", [None, "B", None])
    with pytest.raises(ValueError, match="duplicate annotator_id"):
        analyze_paired_ratings(packet_dir, [first, second], tmp_path / "out-c")


@pytest.mark.parametrize("artifact", ["review.html", "blind_mapping.json", "input_manifest.json"])
def test_rejects_packet_artifact_tampering(tmp_path: Path, artifact: str) -> None:
    packet_dir, packet = _packet_fixture(tmp_path / "packet")
    ratings = _export(tmp_path / "ratings.json", packet, None, [None, None, None])
    (packet_dir / artifact).write_bytes((packet_dir / artifact).read_bytes() + b" ")
    with pytest.raises(ValueError, match="stale"):
        analyze_paired_ratings(packet_dir, [ratings], tmp_path / "out")


def test_rejects_mapping_orientation_even_with_updated_receipt(tmp_path: Path) -> None:
    packet_dir, packet = _packet_fixture(tmp_path / "packet")
    ratings = _export(tmp_path / "ratings.json", packet, None, [None, None, None])
    mapping = json.loads((packet_dir / "blind_mapping.json").read_text())
    mapping["pairs"][0]["side_order"] = "BA"
    _write_json(packet_dir / "blind_mapping.json", mapping)
    receipt = json.loads((packet_dir / "packet_receipt.json").read_text())
    receipt["artifacts"]["blind_mapping.json"] = _hash((packet_dir / "blind_mapping.json").read_bytes())
    _write_json(packet_dir / "packet_receipt.json", receipt)
    with pytest.raises(ValueError, match="candidate orientation differs"):
        analyze_paired_ratings(packet_dir, [ratings], tmp_path / "out")


def test_rejects_false_identical_classification_even_with_updated_receipt(tmp_path: Path) -> None:
    packet_dir, packet = _packet_fixture(tmp_path / "packet")
    ratings = _export(tmp_path / "ratings.json", packet, None, [None, None, None])
    mapping = json.loads((packet_dir / "blind_mapping.json").read_text())
    mapping["pairs"][0]["identical"] = True
    _write_json(packet_dir / "blind_mapping.json", mapping)
    receipt = json.loads((packet_dir / "packet_receipt.json").read_text())
    receipt["artifacts"]["blind_mapping.json"] = _hash((packet_dir / "blind_mapping.json").read_bytes())
    _write_json(packet_dir / "packet_receipt.json", receipt)
    with pytest.raises(ValueError, match="identical classification differs"):
        analyze_paired_ratings(packet_dir, [ratings], tmp_path / "out")


def test_completion_detects_snapshot_tampering_and_output_is_immutable(tmp_path: Path) -> None:
    packet_dir, packet = _packet_fixture(tmp_path / "packet")
    ratings = _export(tmp_path / "ratings.json", packet, None, [None, None, None])
    output = tmp_path / "out"
    analyze_paired_ratings(packet_dir, [ratings], output)
    snapshot = output / "input_snapshot" / "ratings" / "001.json.bytes"
    snapshot.write_bytes(snapshot.read_bytes() + b"x")
    with pytest.raises(ValueError, match="completed result changed"):
        verify_completed_experiment(output)
    with pytest.raises(FileExistsError, match="must be empty"):
        analyze_paired_ratings(packet_dir, [ratings], output)


def test_kappa_is_null_when_joint_ratings_are_degenerate(tmp_path: Path) -> None:
    packet_dir, packet = _packet_fixture(tmp_path / "packet")
    first = _export(tmp_path / "first.json", packet, "ann-1", ["tie", "tie", None])
    second = _export(tmp_path / "second.json", packet, "ann-2", ["tie", "tie", None])
    result = analyze_paired_ratings(packet_dir, [first, second], tmp_path / "out")
    assert result["pairwise"][0]["all_pairs"]["raw_agreement"] == 1.0
    assert result["pairwise"][0]["all_pairs"]["cohen_kappa"] is None
