from __future__ import annotations

from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import shutil

import pytest

import scripts.audit_certified_drums as audit


def _metadata_fixture() -> tuple[dict, dict, dict, dict, dict, list[dict], Counter]:
    """Build frozen metadata without depending on ignored study artifacts."""
    config = audit._expected_study_config()
    source_hash = "source-snapshot"
    cohort_hash = "case-cohort"
    receipt_file_hash = "receipt-file"
    cases = []
    for split in audit.EXPECTED_SPLITS:
        for kind, count, prefix in (
            ("certified_negative", 120, "negative"),
            ("planted_positive", 60, "positive"),
        ):
            for index in range(count):
                cases.append({
                    "case_id": f"{split}-{prefix}-{index:03d}",
                    "split": split,
                    "kind": kind,
                    "midi_path": f"midi/{split}/{prefix}-{index:03d}.mid",
                    "target_pair_keys": [],
                })
    counts = Counter((case["split"], case["kind"]) for case in cases)
    body = {
        "version": audit.STUDY_VERSION,
        "namespace": audit.STUDY_NAMESPACE,
        "case_counts": {
            "negative_per_split": 120,
            "negative_total": 240,
            "positive_per_split": 60,
            "positive_total": 120,
        },
        "splits": list(audit.EXPECTED_SPLITS),
        "bars": audit.EXPECTED_BARS,
        "meters": audit.EXPECTED_METER_LIST,
        "ticks_per_beat": audit.EXPECTED_PPQ_LIST,
        "negative_acceptance": {
            "oracle_pair_count": 0,
            "pair_budget_reached": False,
            "exhaustive_pair_enumeration": True,
            "all_eligible_pairs_compared_under_budget": True,
            "bar_counts": [1, 2, 4],
            "timing_tolerance_beats": [1, 12],
            "hit_error_fraction": [1, 10],
            "min_hits": 8,
            "min_pitches": 2,
            "pair_comparison_limit": audit.EXPECTED_PAIR_LIMIT,
        },
        "positive_acceptance": {
            "known_repeated_bar_regions": True,
            "target_pairs_must_be_oracle_admissible": True,
            "coverage_definition": audit.EXPECTED_POSITIVE_COVERAGE,
        },
        "uniqueness": {
            "reject_exact_arrangement_sha256_collision": True,
            "reject_beat_normalized_arrangement_sha256_collision": True,
            "scope": "all accepted controls",
        },
        "generation": {
            "max_attempts": 10000,
            "pattern_generator": "standard-library random.Random seeded by namespace, split, kind, index and attempt",
            "conditional_negative_bias": "negative cases are conditioned on zero admissible pairs under the stated symbolic oracle",
        },
        "claim_boundary": audit.EXPECTED_CLAIM_BOUNDARY,
        "result_artifacts": [
            "design.json", "labels.json", "raw_results.json", "aggregate.json",
            *[case["midi_path"] for case in cases],
        ],
    }
    receipt = {
        "design": body,
        "design_sha256": audit._json_sha256(body),
        "config": config,
        "config_sha256": audit._json_sha256(config),
        "case_cohort_sha256": cohort_hash,
        "source_snapshot": {"snapshot_sha256": source_hash},
    }
    design = {
        "version": audit.STUDY_VERSION,
        "case_count": len(cases),
        "case_cohort_sha256": cohort_hash,
        "receipt_sha256": receipt_file_hash,
        "snapshot_sha256": source_hash,
        "source_snapshot_sha256": source_hash,
        "design": deepcopy(body),
        "design_sha256": receipt["design_sha256"],
        "config": deepcopy(config),
        "config_sha256": receipt["config_sha256"],
    }
    links = {
        "version": audit.STUDY_VERSION,
        "receipt_sha256": receipt_file_hash,
        "config_sha256": receipt["config_sha256"],
        "case_cohort_sha256": cohort_hash,
        "snapshot_sha256": source_hash,
        "source_snapshot_sha256": source_hash,
    }
    labels = dict(links)
    raw = dict(links, design_sha256=receipt["design_sha256"])
    aggregate = dict(links, design_sha256=receipt["design_sha256"])
    return receipt, design, labels, raw, aggregate, cases, counts


def test_wilson_zero_rate_has_finite_upper_bound() -> None:
    interval = audit._wilson(0, 120)

    assert interval is not None
    assert interval[0] == 0.0
    assert 0.03 < interval[1] < 0.032


def test_direct_edges_and_family_recovery_are_distinct() -> None:
    phrase = {
        "bar_count": 1,
        "meter_numerator": 4,
        "meter_denominator": 4,
        "start_tick": 0,
        "end_tick": 96,
        "occurrences": [
            {"start_tick": 0, "end_tick": 96},
            {"start_tick": 192, "end_tick": 288},
            {"start_tick": 384, "end_tick": 480},
        ],
    }
    targets = [[0, 96], [192, 288], [384, 480]]

    assert len(audit._direct_edges([phrase])) == 2
    assert audit._family_covers_targets([phrase], targets)


def test_replay_stats_allow_metadata_track_shift_and_tuple_config() -> None:
    saved = {
        "source_tracks": [0],
        "config": {"bar_counts": [1, 2, 4]},
        "candidate_count": 1,
    }
    replayed = {
        "source_tracks": [1],
        "config": {"bar_counts": (1, 2, 4)},
        "candidate_count": 1,
    }

    assert audit._compare_replay_stats(saved, replayed) == (True, [])
    replayed["candidate_count"] = 2
    assert audit._compare_replay_stats(saved, replayed)[0] is False
    with pytest.raises(ValueError, match="replay detector stats mismatch"):
        audit._require_replay_stats_match(saved, replayed, mode="exact", case_id="case-1")


def test_target_pairs_are_derived_from_meter_aligned_intervals() -> None:
    case = {
        "case_id": "test-positive",
        "ticks_per_beat": 96,
        "meter": [4, 4],
        "target_intervals": [[384, 768], [1152, 1536], [1920, 2304]],
    }

    assert audit._derived_target_pairs(case) == (
        (1, 4, 4, 384, 768, 1152, 1536),
        (1, 4, 4, 384, 768, 1920, 2304),
        (1, 4, 4, 1152, 1536, 1920, 2304),
    )


@pytest.mark.parametrize("tamper", ("design_hash", "design_body", "config_body"))
def test_rebound_embedded_design_or_config_cannot_bypass_frozen_receipt(tamper: str) -> None:
    receipt, design, labels, raw, aggregate, cases, counts = _metadata_fixture()
    if tamper == "design_hash":
        design["design_sha256"] = "0" * 64
    elif tamper == "design_body":
        design["design"]["namespace"] = "rebound-namespace"
        design["design_sha256"] = audit._json_sha256(design["design"])
    else:
        design["config"]["detector_modes"] = ["tolerant"]
        design["config_sha256"] = audit._json_sha256(design["config"])

    with pytest.raises(ValueError, match="embedded (design|config)"):
        audit._validate_embedded_design(
            receipt=receipt,
            receipt_file_sha256="receipt-file",
            design=design,
            labels=labels,
            raw=raw,
            aggregate=aggregate,
            cases=cases,
            counts=counts,
        )


def test_rebound_receipt_with_semantically_invalid_design_is_rejected() -> None:
    receipt, design, labels, raw, aggregate, cases, counts = _metadata_fixture()
    receipt["design"]["namespace"] = "rebound-namespace"
    receipt["design_sha256"] = audit._json_sha256(receipt["design"])
    design["design"]["namespace"] = "rebound-namespace"
    design["design_sha256"] = receipt["design_sha256"]
    raw["design_sha256"] = receipt["design_sha256"]
    aggregate["design_sha256"] = receipt["design_sha256"]

    with pytest.raises(ValueError, match="design semantics namespace"):
        audit._validate_embedded_design(
            receipt=receipt,
            receipt_file_sha256="receipt-file",
            design=design,
            labels=labels,
            raw=raw,
            aggregate=aggregate,
            cases=cases,
            counts=counts,
        )


@pytest.mark.skipif(
    not Path("research_local/certified_drums_v01").is_dir(),
    reason="completed certified study is an ignored local integration fixture",
)
def test_rebound_completion_artifact_hash_does_not_accept_design_tamper(tmp_path: Path) -> None:
    """A changed result plus a rebound completion entry still fails semantics."""
    study = tmp_path / "study"
    shutil.copytree("research_local/certified_drums_v01", study)
    design_path = study / "design.json"
    design = json.loads(design_path.read_text())
    design["design"]["namespace"] = "rebound-namespace"
    design["design_sha256"] = audit._json_sha256(design["design"])
    design_bytes = json.dumps(
        design, indent=2, sort_keys=True, allow_nan=False
    ).encode() + b"\n"
    design_path.write_bytes(design_bytes)

    completion_path = study / "completion_receipt.json"
    completion = json.loads(completion_path.read_text())
    completion["artifacts"]["design.json"] = {
        "bytes": len(design_bytes),
        "sha256": audit._bytes_sha256(design_bytes),
    }
    completion_path.write_text(
        json.dumps(completion, indent=2, sort_keys=True, allow_nan=False) + "\n"
    )

    with pytest.raises(ValueError, match="embedded design differs"):
        audit.audit_study(study, tmp_path / "audit")


def test_verify_audit_output_detects_tampering(tmp_path: Path) -> None:
    input_manifest = {
        "version": audit.VERSION,
        "study_source_snapshot_sha256": "snapshot",
        "audit_script_sha256": "script",
        "artifacts": [],
    }
    manifest_bytes = json.dumps(
        input_manifest, indent=2, sort_keys=True, allow_nan=False
    ).encode() + b"\n"
    report = {
        "version": audit.VERSION,
        "input_manifest_sha256": audit._json_sha256(input_manifest),
        "study_source_snapshot_sha256": "snapshot",
        "audit_script_sha256": "script",
    }
    report_bytes = json.dumps(report, indent=2, sort_keys=True, allow_nan=False).encode() + b"\n"
    tmp_path.joinpath("input_manifest.json").write_bytes(manifest_bytes)
    tmp_path.joinpath("audit.json").write_bytes(report_bytes)
    receipt = {
        "schema_version": "samuged-certified-drum-audit-v1",
        "status": "completed",
        "input_manifest_sha256": audit._json_sha256(input_manifest),
        "audit_sha256": audit._bytes_sha256(report_bytes),
        "artifacts": {
            "audit.json": {"bytes": len(report_bytes), "sha256": audit._bytes_sha256(report_bytes)},
            "input_manifest.json": {"bytes": len(manifest_bytes), "sha256": audit._bytes_sha256(manifest_bytes)},
        },
    }
    tmp_path.joinpath("audit_receipt.json").write_text(json.dumps(receipt))

    assert audit.verify_audit_output(tmp_path)["version"] == audit.VERSION
    tmp_path.joinpath("audit.json").write_text("{}")
    with pytest.raises(ValueError, match="audit artifact changed"):
        audit.verify_audit_output(tmp_path)
