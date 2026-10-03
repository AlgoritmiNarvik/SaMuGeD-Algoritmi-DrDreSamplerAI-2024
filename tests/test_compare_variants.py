from __future__ import annotations

import json
from pathlib import Path

import pytest

from samuged.dataset import file_digest
from samuged.experiment import verify_completed_experiment
from scripts.compare_variants import compare_variants, global_rank_shifts, semantic_phrase


def _phrase(
    kind: str,
    family: str,
    *,
    rank: int,
    note_count: int = 2,
    occurrences: int = 2,
    support: float = 0.5,
) -> dict:
    pitches = [60 + index for index in range(note_count)] if kind == "melodic" else [36, 42][:note_count]
    onsets = [float(index) for index in range(note_count)]
    return {
        "kind": kind,
        "family_id": family,
        "phrase_id": f"artifact-{family}",
        "midi_path": f"midi/{kind}/{family}.mid",
        "midi_sha256": family.encode().hex().ljust(64, "0")[:64],
        "rank_in_file": rank,
        "part_index": 0 if kind == "melodic" else -1,
        "source_track": 0,
        "start_tick": 0,
        "end_tick": note_count * 480,
        "note_count": note_count,
        "duration_beats": float(note_count),
        "pitches": pitches,
        "onsets_beats": onsets,
        "durations_beats": [0.5] * note_count,
        "velocities": [90] * note_count,
        "occurrence_count": occurrences,
        "raw_occurrence_count": occurrences,
        "occurrences": [
            {
                "start_tick": index * 1920,
                "end_tick": index * 1920 + note_count * 480,
                "similarity": 1.0,
                "transpose_semitones": 0,
            }
            for index in range(occurrences)
        ],
        "recurrence_score": 0.75,
        "score_components": {"support": support},
    }


def _record(source_id: str, phrases: list[dict], *, source_sha: str | None = None) -> dict:
    return {
        "source_id": source_id,
        "source_path": f"artist/{source_id}.mid",
        "source_sha256": source_sha or (source_id * 32)[:64],
        "source_bytes": 100,
        "artist_from_path": "artist",
        "artist_key": "artist-key",
        "title_from_path": source_id,
        "song_key": f"song-{source_id}",
        "status": "ok",
        "outcome": "matched",
        "musical_sha256": f"music-{source_id}",
        "ticks_per_beat": 480,
        "part_count": 2,
        "note_count": 24,
        "warnings": [],
        "metadata_repairs": [],
        "run_key": "build-specific-run",
        "elapsed_seconds": 0.1,
        "phrases": phrases,
    }


def _write_build(
    path: Path,
    algorithm: str,
    rows: list[tuple[dict, str, str]],
    *,
    excluded_families: set[str] | None = None,
) -> None:
    path.mkdir()
    (path / "records").mkdir()
    sources = []
    phrases = []
    for record, split, split_group in rows:
        source_id = record["source_id"]
        (path / "records" / f"{source_id}.json").write_text(
            json.dumps(record, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        sources.append({**record, "split": split, "split_group": split_group})
        for phrase in record["phrases"]:
            phrases.append({
                **phrase,
                "source_id": source_id,
                "source_path": record["source_path"],
                "source_sha256": record["source_sha256"],
                "split": (
                    "overlap_excluded"
                    if phrase["family_id"] in (excluded_families or set())
                    else split
                ),
                "split_group": split_group,
            })
    (path / "sources.jsonl").write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in sources),
        encoding="utf-8",
    )
    (path / "phrases.jsonl").write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in phrases),
        encoding="utf-8",
    )
    (path / "build_config.json").write_text(
        json.dumps({"algorithm": algorithm}, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    source_hash = file_digest(path / "sources.jsonl")
    phrase_hash = file_digest(path / "phrases.jsonl")
    summary = {
        "source_files": len(sources),
        "phrase_rows": len(phrases),
        "source_manifest_sha256": source_hash,
        "phrase_manifest_sha256": phrase_hash,
    }
    (path / "summary.json").write_text(
        json.dumps(summary, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    counts = {
        kind: sum(row["kind"] == kind for row in phrases)
        for kind in ("melodic", "percussion")
    }
    audit = {
        "passed": True,
        "failure_count": 0,
        "failures": [],
        "full_source_coverage_required": True,
        "reextraction_required": True,
        "source_files": len(sources),
        "phrase_rows": len(phrases),
        "counts": counts,
        "source_manifest_sha256": source_hash,
        "phrase_manifest_sha256": phrase_hash,
        "summary_sha256": file_digest(path / "summary.json"),
        "build_config_sha256": file_digest(path / "build_config.json"),
    }
    (path / "audit.json").write_text(
        json.dumps(audit, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def test_semantic_phrase_excludes_artifact_identity_and_global_rank_only() -> None:
    left = _phrase("melodic", "same", rank=1)
    right = {**left, "phrase_id": "new", "midi_path": "midi/new.mid", "rank_in_file": 3}

    assert semantic_phrase(left) == semantic_phrase(right)
    assert global_rank_shifts([left], [right]) == [
        {"family_id": "same", "left_rank_in_file": 1, "right_rank_in_file": 3}
    ]
    right["occurrences"] = [{**right["occurrences"][0], "end_tick": 481}]
    assert semantic_phrase(left) != semantic_phrase(right)


def test_comparison_separates_kinds_and_records_selection_deltas(tmp_path: Path) -> None:
    stable_m_left = _phrase("melodic", "stable-m", rank=1)
    stable_d_left = _phrase("percussion", "stable-d", rank=2)
    stable_m_right = {**stable_m_left, "rank_in_file": 2, "phrase_id": "right-m"}
    stable_d_right = {**stable_d_left, "rank_in_file": 1, "phrase_id": "right-d"}
    changed_left = _phrase("melodic", "old-family", rank=1, support=0.5)
    changed_right = _phrase(
        "melodic", "new-family", rank=1, note_count=3, occurrences=3, support=0.8
    )
    left_rows = [
        (_record("a1", [stable_m_left, stable_d_left]), "train", "g1"),
        (_record("b2", [changed_left]), "test", "g2"),
    ]
    right_rows = [
        (_record("a1", [stable_d_right, stable_m_right]), "train", "g1"),
        (_record("b2", [changed_right]), "test", "g2"),
    ]
    left, right = tmp_path / "left", tmp_path / "right"
    _write_build(left, "aligned_indexed", left_rows)
    _write_build(right, "aligned_closed", right_rows, excluded_families={"new-family"})

    output = tmp_path / "comparison"
    aggregate = compare_variants(left, right, output)

    assert aggregate["algorithms"] == {
        "left": "aligned_indexed",
        "right": "aligned_closed",
    }
    assert aggregate["changed_sources_any_kind"] == 1
    assert aggregate["semantic_phrase_changes"]["melodic"]["changed_source_ids"] == ["b2"]
    assert aggregate["semantic_phrase_changes"]["percussion"]["changed_source_count"] == 0
    assert aggregate["global_rank_shifts"]["melodic"]["count"] == 1
    assert aggregate["global_rank_shifts"]["percussion"]["count"] == 1
    assert aggregate["family_comparison"]["melodic"]["left_only_family_ids"] == ["old-family"]
    assert aggregate["family_comparison"]["melodic"]["right_only_family_ids"] == ["new-family"]
    exclusions = aggregate["phrase_family_exclusions"]
    assert exclusions["left_excluded_phrase_count"] == 0
    assert exclusions["right_excluded_phrase_count"] == 1
    assert exclusions["right_only_exclusions"][0]["family_id"] == "new-family"
    note_delta = aggregate["selection_metric_deltas"]["melodic"]["note_count"]
    assert note_delta["sum_delta"] == 1.0
    support_delta = aggregate["selection_metric_deltas"]["melodic"]["support_score"]
    assert support_delta["sum_delta"] == 0.3
    verify_completed_experiment(output)

    raw = json.loads((output / "raw_results.json").read_text())
    changed = raw["changed_sources"][0]["kinds"]["melodic"]
    assert changed["left_only_family_ids"] == ["old-family"]
    assert changed["right_only_family_ids"] == ["new-family"]
    assert changed["left_selection_trace"][0]["occurrence_count"] == 2
    assert changed["right_selection_trace"][0]["occurrence_count"] == 3
    assert any("occurrences" in path for path in changed["difference_paths"])
    assert aggregate["inputs"]["audits"]["left"]["reextraction_required"] is True


def test_stale_audit_binding_is_rejected_before_output(tmp_path: Path) -> None:
    record = _record("a1", [_phrase("melodic", "same", rank=1)])
    left, right = tmp_path / "left", tmp_path / "right"
    _write_build(left, "aligned_indexed", [(record, "train", "g1")])
    _write_build(right, "aligned_closed", [(record, "train", "g1")])
    audit = json.loads((right / "audit.json").read_text())
    audit["phrase_manifest_sha256"] = "0" * 64
    (right / "audit.json").write_text(json.dumps(audit) + "\n", encoding="utf-8")
    output = tmp_path / "comparison"

    with pytest.raises(ValueError, match="audit binding mismatch"):
        compare_variants(left, right, output)
    assert not output.exists()


@pytest.mark.parametrize("change", ["identity", "split"])
def test_source_identity_and_split_must_match(tmp_path: Path, change: str) -> None:
    phrase = _phrase("melodic", "same", rank=1)
    left_record = _record("a1", [phrase])
    right_record = _record("a1", [phrase], source_sha="f" * 64) if change == "identity" else _record("a1", [phrase])
    left, right = tmp_path / "left", tmp_path / "right"
    _write_build(left, "aligned_indexed", [(left_record, "train", "g1")])
    right_split = "test" if change == "split" else "train"
    _write_build(right, "aligned_closed", [(right_record, right_split, "g1")])

    message = "source identity differs" if change == "identity" else "source split assignment differs"
    with pytest.raises(ValueError, match=message):
        compare_variants(left, right, tmp_path / "comparison")


def test_record_payload_cannot_drift_from_audited_manifest(tmp_path: Path) -> None:
    record = _record("a1", [_phrase("melodic", "same", rank=1)])
    left, right = tmp_path / "left", tmp_path / "right"
    for target in (left, right):
        _write_build(target, "aligned_indexed", [(record, "train", "g1")])
    path = right / "records" / "a1.json"
    changed = json.loads(path.read_text())
    changed["phrases"][0]["occurrences"][0]["end_tick"] += 1
    path.write_text(json.dumps(changed) + "\n")

    with pytest.raises(ValueError, match="record differs from source manifest"):
        compare_variants(left, right, tmp_path / "comparison")


def test_mutation_during_comparison_prevents_completion(tmp_path: Path, monkeypatch) -> None:
    from scripts import compare_variants as comparison

    record = _record("a1", [_phrase("melodic", "same", rank=1)])
    left, right = tmp_path / "left", tmp_path / "right"
    for target in (left, right):
        _write_build(target, "aligned_indexed", [(record, "train", "g1")])
    original = comparison._exclusion_comparison

    def mutate_after_read(indexes):
        result = original(indexes)
        path = right / "records" / "a1.json"
        path.write_text(path.read_text() + "\n")
        return result

    monkeypatch.setattr(comparison, "_exclusion_comparison", mutate_after_read)
    output = tmp_path / "comparison"
    with pytest.raises(ValueError, match="frozen comparison input changed"):
        compare_variants(left, right, output)
    assert not (output / "completion_receipt.json").exists()
