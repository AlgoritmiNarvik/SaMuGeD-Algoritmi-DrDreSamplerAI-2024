from __future__ import annotations

from fractions import Fraction
from hashlib import sha256
import json
from pathlib import Path

import pytest

from samuged.experiment import verify_completed_experiment
from scripts.audit_curation import (
    _fraction_payload,
    analyze,
    phrase_diagnostic,
    run,
    source_group_diagnostic,
)


def _phrase(
    phrase_id: str,
    *,
    kind: str = "melodic",
    start: int = 0,
    end: int = 3,
    ppq: int = 3,
    pitches: list[int] | None = None,
    onsets: list[float] | None = None,
    occurrences: list[tuple[int, int]] | None = None,
    rank: int = 1,
    family: str | None = None,
    part: int = 0,
) -> dict:
    pitches = pitches or [60, 60, 60]
    onsets = onsets or [0.0, 1 / 3, 2 / 3]
    occurrences = occurrences or [(start, end), (start + 6, end + 6)]
    row = {
        "source_id": "source-a",
        "phrase_id": phrase_id,
        "family_id": family or f"family-{phrase_id}",
        "kind": kind,
        "rank_in_file": rank,
        "part_index": part if kind == "melodic" else -1,
        "start_tick": start,
        "end_tick": end,
        "ticks_per_beat": ppq,
        "note_count": len(pitches),
        "pitches": pitches,
        "onsets_beats": onsets,
        "occurrence_count": len(occurrences),
        "occurrences": [
            {"start_tick": left, "end_tick": right, "similarity": 1.0, "transpose_semitones": 0}
            for left, right in occurrences
        ],
    }
    if kind == "percussion":
        row["source_part_indices"] = [2, 5]
    return row


def _write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")


def _hash(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _dataset(path: Path) -> Path:
    path.mkdir()
    phrases = [
        _phrase("a", start=0, end=3, rank=1),
        _phrase("b", start=2, end=5, rank=2, part=1),
        _phrase(
            "d",
            kind="percussion",
            start=0,
            end=6,
            pitches=[36, 42, 38, 42],
            onsets=[0.0, 0.0, 1 / 3, 1 / 3],
            occurrences=[(0, 6), (6, 12)],
            rank=3,
        ),
    ]
    source = {
        "source_id": "source-a",
        "status": "ok",
        "ticks_per_beat": 3,
        "phrases": phrases,
    }
    (path / "sources.jsonl").write_text(json.dumps(source, sort_keys=True) + "\n", encoding="utf-8")
    (path / "phrases.jsonl").write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in phrases), encoding="utf-8"
    )
    _write_json(path / "build_config.json", {"algorithm": "reference"})
    summary = {
        "algorithm": "reference",
        "run_key": "fixture",
        "source_files": 1,
        "phrase_counts": {"melodic": 2, "percussion": 1},
        "source_manifest_sha256": _hash(path / "sources.jsonl"),
        "phrase_manifest_sha256": _hash(path / "phrases.jsonl"),
    }
    _write_json(path / "summary.json", summary)
    audit = {
        "passed": True,
        "failure_count": 0,
        "failures": [],
        "full_source_coverage_required": True,
        "source_files": 1,
        "phrase_rows": 3,
        "counts": {"melodic": 2, "percussion": 1},
        "source_manifest_sha256": _hash(path / "sources.jsonl"),
        "phrase_manifest_sha256": _hash(path / "phrases.jsonl"),
        "summary_sha256": _hash(path / "summary.json"),
        "build_config_sha256": _hash(path / "build_config.json"),
    }
    _write_json(path / "audit.json", audit)
    return path


def test_overlap_union_and_exact_rational_beat_conversion() -> None:
    rows = [
        phrase_diagnostic(_phrase(
            "a", start=0, end=1, ppq=3, rank=1, pitches=[60], onsets=[0.0]
        )),
        phrase_diagnostic(_phrase(
            "b", start=0, end=2, ppq=3, rank=2, pitches=[62], onsets=[0.0]
        )),
    ]
    group = source_group_diagnostic("source-a", "melodic", rows)
    assert group["prototype"]["sum_ticks"] == 3
    assert group["prototype"]["union_ticks"] == 2
    assert group["prototype"]["overlap_ticks"] == 1
    sources = {"source-a": {"status": "ok", "ticks_per_beat": 3, "phrase_count": 2}}
    result, _ = analyze(sources, {("source-a", "melodic"): rows}, {"melodic": rows})
    assert result["kinds"]["melodic"]["temporal_coverage"]["prototype"]["sum_beats"] == {
        "numerator": 1, "denominator": 1, "decimal": 1.0
    }
    assert result["kinds"]["melodic"]["temporal_coverage"]["prototype"]["union_beats"] == {
        "numerator": 2, "denominator": 3, "decimal": 0.66666667
    }


def test_percussion_simultaneous_notes_are_hits_not_zero_ioi_vocabulary() -> None:
    row = phrase_diagnostic(_phrase(
        "d", kind="percussion", end=3, pitches=[36, 42, 38, 42],
        onsets=[0.0, 0.0, 1 / 3, 1 / 3], occurrences=[(0, 3), (3, 6)],
    ))
    assert row["note_count"] == 4
    assert row["distinct_onset_count"] == 2
    assert row["simultaneous_extra_notes"] == 2
    assert row["rhythmic_vocabulary_size"] == 1
    assert row["tiny_rhythmic_vocabulary"] is True


def test_run_binds_passed_audit_and_writes_completed_results(tmp_path: Path) -> None:
    dataset = _dataset(tmp_path / "dataset")
    result = run(dataset, tmp_path / "output")
    assert result["validated_source_rows"] == 1
    assert result["validated_phrase_rows"] == 3
    assert result["kinds"]["melodic"]["selected_phrase_count_per_source"]["frequency"] == {"2": 1}
    assert result["kinds"]["melodic"]["temporal_coverage"]["prototype"]["overlap_beats"] == _fraction_payload(Fraction(1, 3))
    assert result["kinds"]["percussion"]["repetitive_structure"]["simultaneous_extra_notes"] == 2
    assert verify_completed_experiment(tmp_path / "output")["status"] == "completed"


def test_manifest_change_after_audit_is_rejected_before_experiment(tmp_path: Path) -> None:
    dataset = _dataset(tmp_path / "dataset")
    with (dataset / "phrases.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(_phrase("tampered")) + "\n")
    with pytest.raises(ValueError, match="audit binding mismatch"):
        run(dataset, tmp_path / "output")
    assert not (tmp_path / "output").exists()


def test_invalid_occurrence_interval_is_rejected() -> None:
    row = _phrase("bad", occurrences=[(3, 3), (6, 9)])
    with pytest.raises(ValueError, match="invalid temporal interval"):
        phrase_diagnostic(row)


def test_completed_dataset_with_no_percussion_is_supported(tmp_path: Path) -> None:
    dataset = _dataset(tmp_path / "dataset")
    phrases = [json.loads(line) for line in (dataset / "phrases.jsonl").read_text().split("\n") if line]
    phrases = [row for row in phrases if row["kind"] == "melodic"]
    source = json.loads((dataset / "sources.jsonl").read_text())
    source["phrases"] = phrases
    (dataset / "sources.jsonl").write_text(json.dumps(source) + "\n")
    (dataset / "phrases.jsonl").write_text("".join(json.dumps(row) + "\n" for row in phrases))
    summary = json.loads((dataset / "summary.json").read_text())
    summary.update({"phrase_counts": {"melodic": 2},
                    "source_manifest_sha256": _hash(dataset / "sources.jsonl"),
                    "phrase_manifest_sha256": _hash(dataset / "phrases.jsonl")})
    _write_json(dataset / "summary.json", summary)
    audit = json.loads((dataset / "audit.json").read_text())
    audit.update({"phrase_rows": 2, "counts": {"melodic": 2},
                  "source_manifest_sha256": _hash(dataset / "sources.jsonl"),
                  "phrase_manifest_sha256": _hash(dataset / "phrases.jsonl"),
                  "summary_sha256": _hash(dataset / "summary.json")})
    _write_json(dataset / "audit.json", audit)
    result = run(dataset, tmp_path / "output")
    assert result["kinds"]["percussion"]["phrase_count"] == 0
    assert result["kinds"]["percussion"]["phrase_distributions"]["note_count"] == {"count": 0}
