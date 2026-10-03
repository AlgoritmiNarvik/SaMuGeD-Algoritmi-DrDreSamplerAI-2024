import json
from pathlib import Path

import pytest

from samuged.experiment import verify_completed_experiment
from scripts.analyze_ratings import (
    ANALYSIS_VERSION,
    DIMENSIONS,
    analyze_ratings,
)


def _packet() -> dict:
    return {
        "schema_version": "samuged-review-v3",
        "config": {
            "requested_count": 2,
            "selected_count": 2,
            "eligible_kind_counts": {"melodic": 1, "percussion": 1},
            "selected_kind_counts": {"melodic": 1, "percussion": 1},
            "seed": "fixture-seed",
            "seed_digest": __import__("hashlib").sha256(b"fixture-seed").hexdigest(),
            "selection": "deterministic hash rank, alternating melodic and percussion when available",
            "sampling_constraints": {
                "at_most_one_per": ["source_id", "split_group", "family_id"],
                "missing_split_group_or_family_fallback": "source_id",
                "kind_balance": "round_robin_preference_with_constraint_aware_fallback",
            },
            "metadata_repair_policy": "strict parsing unless the source manifest carries an exact metadata_repairs receipt",
            "source_manifest_sha256": "1" * 64,
            "phrase_manifest_sha256": "2" * 64,
            "excerpt_policy": "source MIDI prototype and up to two other distinct recorded intervals, exact melodic note indices, source tempo map",
        },
        "candidates": [
            {
                "review_id": "R001",
                "candidate_id": "C001",
                "kind": "melodic",
                "source_id": "S001",
                "source_sha256": "3" * 64,
                "source_path": "Artist/song.mid",
                "split_group": "split-a",
                "family_id": "family-a",
                "metadata_repairs": [],
                "snippets": [],
            },
            {
                "review_id": "R002",
                "candidate_id": "C002",
                "kind": "percussion",
                "source_id": "S002",
                "source_sha256": "4" * 64,
                "source_path": "Artist/other.mid",
                "split_group": "split-b",
                "family_id": "family-b",
                "metadata_repairs": [],
                "snippets": [],
            },
        ],
    }


def _write_packet(path: Path, packet: dict) -> None:
    encoded = json.dumps(packet, sort_keys=True, separators=(",", ":"))
    path.write_text(
        '<html><script id="review-data" type="application/json">'
        + encoded
        + "</script></html>",
        encoding="utf-8",
    )


def _export(packet: dict, annotator: str, *, values: dict[str, dict] | None = None) -> dict:
    values = values or {}
    reviews = []
    for candidate in packet["candidates"]:
        row = {key: candidate[key] for key in (
            "review_id", "candidate_id", "kind", "source_id", "source_sha256",
            "source_path", "split_group", "family_id", "metadata_repairs",
        )}
        row.update({
            "same_phrase": None,
            "boundary_quality": None,
            "role": None,
            "salience": None,
            "notes": "",
        })
        row.update(values.get(candidate["review_id"], {}))
        reviews.append(row)
    return {
        "schema_version": packet["schema_version"],
        "annotator_id": annotator,
        "packet_config": packet["config"],
        "reviews": reviews,
    }


def test_valid_two_raters_counts_missing_and_receipts(tmp_path: Path) -> None:
    packet = _packet()
    packet_path = tmp_path / "review.html"
    _write_packet(packet_path, packet)
    first = tmp_path / "a.json"
    second = tmp_path / "b.json"
    first.write_text(json.dumps(_export(packet, "alice", values={
        "R001": {"same_phrase": "yes", "boundary_quality": "good", "role": "melody", "salience": "high"},
        "R002": {"same_phrase": "uncertain", "role": "percussion", "salience": "low"},
    })))
    second.write_text(json.dumps(_export(packet, "bob", values={
        "R001": {"same_phrase": "no", "boundary_quality": "good", "role": "melody", "salience": "high"},
        "R002": {"same_phrase": "uncertain", "boundary_quality": "poor", "role": "uncertain", "salience": "low"},
    })))
    result = analyze_ratings(packet_path, [first, second], tmp_path / "result")
    assert result["schema_version"] == ANALYSIS_VERSION
    assert result["status"] == "rated"
    assert result["by_kind"]["melodic"]["review_rows"] == 2
    assert result["annotators"][0]["counts"]["boundary_quality"]["missing"] == 1
    pair = result["pairwise"][0]
    assert pair["joint_rows"] == 2
    assert pair["dimensions"]["same_phrase"]["jointly_rated"] == 2
    assert pair["dimensions"]["same_phrase"]["agreement_count"] == 1
    assert pair["dimensions"]["role"]["jointly_rated"] == 2
    assert verify_completed_experiment(tmp_path / "result")["status"] == "completed"


def test_empty_export_is_explicitly_unrated(tmp_path: Path) -> None:
    packet = _packet()
    packet_path = tmp_path / "review.html"
    _write_packet(packet_path, packet)
    export = tmp_path / "empty.json"
    export.write_text(json.dumps({
        "schema_version": packet["schema_version"],
        "annotator_id": "blank-rater",
        "packet_config": packet["config"],
        "reviews": [],
    }))
    result = analyze_ratings(packet_path, [export], tmp_path / "empty-result")
    assert result["status"] == "no_ratings"
    assert result["annotators"][0]["review_rows"] == 0
    assert result["annotators"][0]["rated_rows"] == {dimension: 0 for dimension in DIMENSIONS}


def test_all_null_rows_are_unrated_even_when_export_has_cards(tmp_path: Path) -> None:
    packet = _packet()
    packet_path = tmp_path / "review.html"
    _write_packet(packet_path, packet)
    export = tmp_path / "blank-ui-export.json"
    export.write_text(json.dumps(_export(packet, "blank-ui-rater")))
    result = analyze_ratings(packet_path, [export], tmp_path / "blank-ui-result")
    assert result["status"] == "no_ratings"
    assert result["annotators"][0]["review_rows"] == 2
    assert result["annotators"][0]["rated_rows"] == {dimension: 0 for dimension in DIMENSIONS}
    assert all(
        result["annotators"][0]["counts"][dimension]["missing"] == 2
        for dimension in DIMENSIONS
    )


@pytest.mark.parametrize("tamper", ["missing", "unknown", "duplicate", "provenance", "enum"])
def test_invalid_rows_are_rejected(tmp_path: Path, tamper: str) -> None:
    packet = _packet()
    packet_path = tmp_path / "review.html"
    _write_packet(packet_path, packet)
    export = _export(packet, "alice")
    if tamper == "missing":
        export["reviews"] = export["reviews"][:1]
    elif tamper == "unknown":
        export["reviews"][0]["review_id"] = "R999"
    elif tamper == "duplicate":
        export["reviews"][1]["review_id"] = export["reviews"][0]["review_id"]
    elif tamper == "provenance":
        export["reviews"][0]["source_sha256"] = "f" * 64
    elif tamper == "enum":
        export["reviews"][0]["role"] = "maybe"
    export_path = tmp_path / "ratings.json"
    export_path.write_text(json.dumps(export))
    with pytest.raises(ValueError):
        analyze_ratings(packet_path, [export_path], tmp_path / f"result-{tamper}")


def test_duplicate_annotator_and_nonempty_output_are_rejected(tmp_path: Path) -> None:
    packet = _packet()
    packet_path = tmp_path / "review.html"
    _write_packet(packet_path, packet)
    first = tmp_path / "a.json"
    second = tmp_path / "b.json"
    first.write_text(json.dumps(_export(packet, "same")))
    second.write_text(json.dumps(_export(packet, "same")))
    with pytest.raises(ValueError, match="duplicate annotator"):
        analyze_ratings(packet_path, [first, second], tmp_path / "duplicate")
    output = tmp_path / "nonempty"
    output.mkdir()
    (output / "keep.txt").write_text("keep")
    with pytest.raises(FileExistsError):
        analyze_ratings(packet_path, [first], output)


def test_degenerate_kappa_is_null(tmp_path: Path) -> None:
    packet = _packet()
    packet_path = tmp_path / "review.html"
    _write_packet(packet_path, packet)
    exports = []
    for annotator in ("alice", "bob"):
        path = tmp_path / f"{annotator}.json"
        path.write_text(json.dumps(_export(packet, annotator, values={
            "R001": {"same_phrase": "yes"}, "R002": {"same_phrase": "yes"},
        })))
        exports.append(path)
    result = analyze_ratings(packet_path, exports, tmp_path / "degenerate")
    assert result["pairwise"][0]["dimensions"]["same_phrase"]["cohen_kappa"] is None


@pytest.mark.parametrize("tamper", ["packet", "rating", "manifest"])
def test_completion_binds_each_saved_input_artifact(tmp_path: Path, tamper: str) -> None:
    packet = _packet()
    packet_path = tmp_path / "review.html"
    _write_packet(packet_path, packet)
    export = tmp_path / "alice.json"
    export.write_text(json.dumps(_export(packet, "alice", values={
        "R001": {"same_phrase": "yes"},
    })))
    output = tmp_path / "result"
    analyze_ratings(packet_path, [export], output)
    if tamper == "packet":
        target = output / "input_snapshot" / "review.html"
        target.write_bytes(target.read_bytes() + b"\n")
    elif tamper == "rating":
        target = next((output / "input_snapshot" / "ratings").glob("*.bytes"))
        target.write_bytes(target.read_bytes() + b"\n")
    else:
        target = output / "input_snapshot.json"
        manifest = json.loads(target.read_text())
        manifest["files"][0]["sha256"] = "0" * 64
        target.write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        verify_completed_experiment(output)
